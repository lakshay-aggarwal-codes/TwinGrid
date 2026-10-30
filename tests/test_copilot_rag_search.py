"""CP-6: tokenizer, index build/load/staleness and BM25 search over the Copilot docs corpus. No network, no model."""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

import pytest

from src.copilot.rag import corpus
from src.copilot.rag import index as rag_index
from src.copilot.rag import search as rag_search
from src.copilot.rag.tokenize import MAX_QUERY_CHARS, MAX_QUERY_TERMS, normalize_query, query_terms, stem, tokenize

REPO = Path(__file__).resolve().parents[1]

DOCS = {
    "docs/runbooks/api-down.md": "# API down\n\nThe API returns 502 and the health check fails. Restart the backend container and read the logs.\n",
    "docs/runbooks/stale-feed.md": "# Stale live feed\n\nThe websocket broadcast heartbeat is old. Restart the broadcaster after reading readyz.\n",
    "docs/runbooks/rotating-secrets.md": "# Rotating secrets\n\nRotate the JWT signing key and the database password. Every session ends after rotation.\n",
    "docs/model_cards/forecaster.md": "# Forecaster\n\n## Limitations\n\nThe forecaster predicts thermal state thirty minutes ahead. Evaluated on simulator data only.\n",
    "docs/copilot/LIMITS.md": "# Copilot limits\n\nThe assistant answers from evidence. It cannot change settings or approve proposals.\n",
}


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for rel in corpus.ALLOWED_FILES:
        name = Path(rel).stem
        _write(tmp_path, rel, f"# {name}\n\nGeneric placeholder paragraph for {name}.\n")
    for rel, text in DOCS.items():
        _write(tmp_path, rel, text)
    return tmp_path


@pytest.fixture
def built(tree: Path, tmp_path: Path):
    out = tmp_path / "idx" / "docs_index.sqlite"
    result = rag_index.build_index(out, tree)
    return tree, out, result, rag_index.load_index(out)


# --- tokenizer ------------------------------------------------------------------------------------------------------


def test_related_word_forms_share_a_stem_and_digits_are_kept():
    assert len({stem(w) for w in ("rotate", "rotating", "rotated", "rotates")}) == 1
    assert len({stem(w) for w in ("proposal", "proposals")}) == 1
    assert len({stem(w) for w in ("policy", "policies")}) == 1
    assert tokenize("Physics v2 and p95 in 2026") == ["physic", "v2", "p95", "2026"]


def test_tokenize_drops_stop_words_single_letters_and_folds_accents():
    assert tokenize("The café is a place") == ["cafe", stem("place")]
    assert tokenize("Température of the rack") == [stem("temperature"), "rack"]
    assert tokenize("api_down-and/stale.feed") == ["api", "down", stem("stale"), "feed"]


def test_normalize_query_bounds_and_cleans_anything():
    assert normalize_query(None) == "" and normalize_query(42) == "" and normalize_query(b"x") == ""
    assert normalize_query("  A \t\n B\x00C  ") == "a b c"
    assert len(normalize_query("x" * 10_000)) == MAX_QUERY_CHARS
    assert len(query_terms(" ".join(f"term{i}" for i in range(200)))) == MAX_QUERY_TERMS
    assert query_terms("down down DOWN") == ["down"]


# --- build, load, failure modes -------------------------------------------------------------------------------------


def test_build_and_load_roundtrip(built):
    tree, out, result, index = built
    assert out.is_file() and result.documents == len(corpus.ALLOWED_FILES) + len(DOCS)
    assert index.chunk_count == result.chunks and index.vocabulary_size == result.terms
    assert index.fingerprint == result.fingerprint
    assert {c.source_path for c in index.chunks} == set(index.doc_hashes)
    assert list(out.parent.iterdir()) == [out]  # no temporary file left behind


def test_two_builds_are_logically_identical(tree: Path, tmp_path: Path):
    a = rag_index.build_index(tmp_path / "a.sqlite", tree)
    b = rag_index.build_index(tmp_path / "b.sqlite", tree)
    assert a.fingerprint == b.fingerprint
    ia, ib = rag_index.load_index(tmp_path / "a.sqlite"), rag_index.load_index(tmp_path / "b.sqlite")
    assert ia.chunks == ib.chunks and ia.postings == ib.postings and ia.lengths == ib.lengths


def test_a_directory_name_with_a_space_works(tree: Path, tmp_path: Path):
    out = tmp_path / "data center" / "copilot" / "docs_index.sqlite"
    rag_index.build_index(out, tree)
    assert rag_index.load_index(out).chunk_count > 0


def test_a_failed_build_leaves_the_old_index_and_no_temp_file(tree: Path, tmp_path: Path, monkeypatch):
    out = tmp_path / "docs_index.sqlite"
    rag_index.build_index(out, tree)
    before = out.read_bytes()

    def boom(*_a, **_k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(rag_index, "tokenize", boom)
    with pytest.raises(RuntimeError):
        rag_index.build_index(out, tree)
    assert out.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("docs_index")] == ["docs_index.sqlite"]


def test_an_empty_corpus_is_refused(tmp_path: Path):
    with pytest.raises(rag_index.IndexUnavailable) as err:
        rag_index.build_index(tmp_path / "x.sqlite", tmp_path)
    assert err.value.status == rag_index.STATUS_MISSING
    assert not (tmp_path / "x.sqlite").exists()


def test_a_missing_garbage_or_wrong_version_index_is_unavailable_not_a_crash(built, tmp_path: Path):
    _tree, out, _result, _index = built
    with pytest.raises(rag_index.IndexUnavailable) as err:
        rag_index.load_index(tmp_path / "nope.sqlite")
    assert err.value.status == rag_index.STATUS_MISSING

    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"this is not a database" * 50)
    with pytest.raises(rag_index.IndexUnavailable) as err:
        rag_index.load_index(junk)
    assert err.value.status == rag_index.STATUS_INCOMPATIBLE

    for key, value in (("tokenizer_version", "999"), ("schema_version", "999")):
        broken = tmp_path / f"{key}.sqlite"
        broken.write_bytes(out.read_bytes())
        con = sqlite3.connect(broken)
        con.execute("UPDATE meta SET value=? WHERE key=?", (value, key))
        con.commit()
        con.close()
        with pytest.raises(rag_index.IndexUnavailable) as err:
            rag_index.load_index(broken)
        assert err.value.status == rag_index.STATUS_INCOMPATIBLE and key.split("_")[0] in err.value.reason


def test_a_loaded_index_does_not_depend_on_the_file(built):
    _tree, out, _result, index = built
    out.unlink()
    assert rag_search.search(index, "restart the backend", min_score=0).found


def test_default_index_path_honours_the_environment():
    assert rag_index.default_index_path({}) == corpus.default_root() / "data" / "copilot" / "docs_index.sqlite"
    assert (
        rag_index.default_index_path({"COPILOT_DOCS_INDEX_PATH": "var/x.sqlite"})
        == corpus.default_root() / "var" / "x.sqlite"
    )
    absolute = Path(__file__).resolve()
    assert rag_index.default_index_path({"COPILOT_DOCS_INDEX_PATH": str(absolute)}) == absolute


# --- staleness ------------------------------------------------------------------------------------------------------


def test_a_fresh_index_is_fresh_and_any_document_change_makes_it_stale(built):
    tree, out, _result, _index = built
    assert rag_index.check_freshness(out, tree).usable

    _write(tree, "docs/runbooks/api-down.md", DOCS["docs/runbooks/api-down.md"] + "\nNew paragraph.\n")
    stale = rag_index.check_freshness(out, tree)
    assert (
        stale.status == rag_index.STATUS_STALE and stale.changed == ("docs/runbooks/api-down.md",) and not stale.usable
    )

    _write(tree, "docs/runbooks/new-one.md", "# New\n\nSomething new.\n")
    (tree / "docs" / "runbooks" / "stale-feed.md").unlink()
    stale = rag_index.check_freshness(out, tree)
    assert stale.added == ("docs/runbooks/new-one.md",) and stale.removed == ("docs/runbooks/stale-feed.md",)


def test_staleness_ignores_line_endings_and_reports_missing_and_incompatible(built, tmp_path: Path):
    tree, out, _result, _index = built
    (tree / "docs" / "runbooks" / "api-down.md").write_bytes(
        DOCS["docs/runbooks/api-down.md"].replace("\n", "\r\n").encode()
    )
    assert rag_index.check_freshness(out, tree).usable
    assert rag_index.check_freshness(tmp_path / "none.sqlite", tree).status == rag_index.STATUS_MISSING
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"x" * 200)
    assert rag_index.check_freshness(junk, tree).status == rag_index.STATUS_INCOMPATIBLE


def test_extra_allow_used_at_build_time_is_remembered_for_the_freshness_check(tree: Path, tmp_path: Path):
    _write(tree, "docs/security/THREAT_MODEL.md", "# Threats\n\nAn attacker may guess a password.\n")
    out = tmp_path / "i.sqlite"
    rag_index.build_index(out, tree, ("docs/security/THREAT_MODEL.md",))
    assert rag_index.load_index(out).extra_allow == ("docs/security/THREAT_MODEL.md",)
    assert rag_index.check_freshness(out, tree).usable


# --- search ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,expected",
    [
        ("how do I rotate secrets", "docs/runbooks/rotating-secrets.md"),
        ("what do I do when the API is down", "docs/runbooks/api-down.md"),
        ("the live feed is stale", "docs/runbooks/stale-feed.md"),
        ("how far ahead does the forecaster predict", "docs/model_cards/forecaster.md"),
        ("can the assistant approve proposals", "docs/copilot/LIMITS.md"),
    ],
)
def test_known_questions_rank_the_right_document_first(built, question, expected):
    result = rag_search.search(built[3], question, min_score=0)
    assert result.found and result.hits[0].chunk.source_path == expected
    assert result.hits[0].rank == 1 and result.reason == rag_search.REASON_OK


def test_hits_name_their_matched_terms_and_are_sorted(built):
    result = rag_search.search(built[3], "restart the broadcaster after readyz", min_score=0)
    top = result.hits[0]
    assert top.chunk.source_path == "docs/runbooks/stale-feed.md"
    assert set(top.matched_terms) <= set(result.terms) and {"broadcaster", "readyz"} <= set(top.matched_terms)
    assert 0 < top.coverage <= 1
    assert [h.score for h in result.hits] == sorted((h.score for h in result.hits), reverse=True)
    assert [h.rank for h in result.hits] == list(range(1, len(result.hits) + 1))


def test_a_term_only_in_the_heading_or_file_name_still_finds_the_chunk(built):
    by_heading = rag_search.search(built[3], "limitations", min_score=0)
    assert by_heading.hits[0].chunk.heading_path == "Forecaster > Limitations"
    by_name = rag_search.search(built[3], "forecaster", min_score=0)
    assert by_name.hits[0].chunk.source_path == "docs/model_cards/forecaster.md"


def test_below_the_threshold_nothing_is_returned_and_the_reason_says_so(built):
    index = built[3]
    open_result = rag_search.search(index, "restart", min_score=0)
    assert open_result.found
    best = open_result.best_score
    shut = rag_search.search(index, "restart", min_score=best + 1)
    assert shut.hits == () and shut.reason == rag_search.REASON_BELOW_THRESHOLD and shut.best_score == best
    assert rag_search.search(index, "restart", min_score=best).found


def test_unknown_terms_and_unusable_queries_find_nothing_without_raising(built):
    index = built[3]
    assert rag_search.search(index, "flux capacitor", min_score=0).reason == rag_search.REASON_NO_MATCH
    for odd in ("", "   ", "the of and", None, 42, b"bytes", ["list"], "\x00\x01", "?!?!"):
        result = rag_search.search(index, odd, min_score=0)
        assert result.hits == () and result.reason == rag_search.REASON_NO_TERMS


@pytest.mark.parametrize(
    "hostile",
    [
        "'; DROP TABLE chunks; --",
        '" OR 1=1 --',
        "restart') UNION SELECT text FROM chunks --",
        'NEAR(api down, 2) OR "stale" *',
        "restart\x00; DELETE FROM postings",
        "../../etc/passwd",
        "<script>alert(1)</script> restart",
    ],
)
def test_hostile_queries_are_just_words_and_never_touch_the_database(built, hostile):
    tree, out, _result, index = built
    before = out.read_bytes()
    result = rag_search.search(index, hostile, min_score=0)
    assert all(re.fullmatch(r"[a-z0-9]+", t) for t in result.terms)
    assert out.read_bytes() == before
    assert rag_index.load_index(out).chunk_count == index.chunk_count


def test_a_huge_query_is_capped_and_fast(built):
    started = time.perf_counter()
    result = rag_search.search(built[3], "restart backend " * 5000, min_score=0)
    assert len(result.query) <= MAX_QUERY_CHARS and len(result.terms) <= MAX_QUERY_TERMS
    assert time.perf_counter() - started < 2.0


def test_k_is_bounded_and_results_are_deterministic(built):
    index = built[3]
    assert len(rag_search.search(index, "generic placeholder paragraph", k=0, min_score=0).hits) == 1
    many = rag_search.search(index, "generic placeholder paragraph", k=999, min_score=0)
    assert 1 < len(many.hits) <= rag_search.MAX_K
    again = rag_search.search(index, "generic placeholder paragraph", k=999, min_score=0)
    assert many == again
    ties = [h for h in many.hits if h.score == many.hits[0].score]
    assert [h.chunk.source_path for h in ties] == sorted(h.chunk.source_path for h in ties)


# --- the real documents (repo-drift smoke tests; thresholds are PLACEHOLDERS until CP-9) -----------------------------


@pytest.fixture(scope="module")
def real_index(tmp_path_factory):
    out = tmp_path_factory.mktemp("real") / "docs_index.sqlite"
    result = rag_index.build_index(out, REPO)
    assert result.missing == ()
    return out, rag_index.load_index(out)


def test_the_real_index_is_fresh_and_never_holds_security_or_env_text(real_index):
    out, index = real_index
    assert rag_index.check_freshness(out, REPO).usable
    assert index.chunk_count >= 50
    assert not any(p.startswith("docs/security/") or ".env" in p for p in index.doc_hashes)


@pytest.mark.parametrize(
    "question,expected",
    [
        ("how do I rotate secrets", "rotating-secrets.md"),
        ("what to do when the API is down", "api-down.md"),
        ("the live feed is stale", "stale-feed.md"),
        ("database is down", "database-down.md"),
        ("migration failed", "migration-failure.md"),
        ("what are the limits of the anomaly detector", "anomaly_detector.md"),
        ("is the forecaster better than a baseline", "forecaster.md"),
        ("does the PPO optimizer save energy", "ppo_optimizer.md"),
        ("what are the Copilot limits", "LIMITS.md"),
        ("SLO targets", "SLO.md"),
    ],
)
def test_real_questions_find_their_document_in_the_top_three_with_the_default_threshold(real_index, question, expected):
    result = rag_search.search(real_index[1], question, k=3)
    assert result.found, (question, result.best_score)
    assert expected in [Path(h.chunk.source_path).name for h in result.hits]


@pytest.mark.parametrize(
    "question", ["flux capacitor", "how do I cook rice", "capital of France", "who won the world cup"]
)
def test_real_unrelated_questions_return_nothing_with_the_default_threshold(real_index, question):
    result = rag_search.search(real_index[1], question)
    assert result.hits == (), (question, result.best_score)
