"""CP-9: tests for the evaluation harness and the invariants it measures. No network; every provider is a scripted fake.

Three kinds of test:

* the question file and the checkout agree (a doc rename or a deleted file fails HERE, loudly, not as a silent score change);
* the harness arithmetic is right (replay of the product's floors, fit, leave-one-out, percentiles) on tiny synthetic data;
* the invariants the evaluation measures hold on the real docs, and the recorded floors in questions.yaml are not undercut.
  The gates in questions.yaml are TARGETS and are reported by ``scripts/copilot_eval.py``; they are not asserted here,
  because two of them are not met today. The floors are asserted: a change that makes retrieval worse fails this suite.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from src.copilot import MODE_LLM, answer, llm
from src.copilot.rag import corpus as rag_corpus
from src.copilot.rag import index as rag_index
from src.copilot.rag import search as rag_search
from tests.copilot_eval import harness as h

REPO = h.ROOT

ASSUMED_FILES = (  # what this task assumes about the checkout (CP-9 report lists the same)
    "src/copilot/answer.py",
    "src/copilot/docs_answer.py",
    "src/copilot/llm.py",
    "src/copilot/router.py",
    "src/copilot/limiter.py",
    "src/copilot/evidence.py",
    "src/copilot/rag/corpus.py",
    "src/copilot/rag/index.py",
    "src/copilot/rag/search.py",
    "scripts/build_copilot_index.py",
    "tests/fixtures/copilot/helpers.py",
)


@pytest.fixture(scope="module")
def suite() -> h.Suite:
    return h.load_suite()


@pytest.fixture(scope="module")
def index(tmp_path_factory) -> rag_index.DocsIndex:
    path = tmp_path_factory.mktemp("eval_index") / "docs_index.sqlite"
    rag_index.build_index(path, REPO)
    return rag_index.load_index(path)


@pytest.fixture(scope="module")
def ev() -> h.Evaluation:
    """One full offline evaluation (index build, 50 questions, fake rephrase and failover) shared by the tests below."""
    return h.evaluate(REPO)


# ----------------------------------------------------------------------------- the checkout matches what is assumed


def test_every_assumed_file_and_symbol_exists():
    missing = [rel for rel in ASSUMED_FILES if not (REPO / rel).is_file()]
    assert not missing, f"CP-9 assumes these files exist: {missing}"
    assert answer.DOCS_INTENT == "docs_question" and callable(llm.validate) and callable(llm.ungrounded_terms)
    assert hasattr(rag_search, "DEFAULT_MIN_SCORE") and hasattr(rag_search, "DEFAULT_MIN_COVERAGE")


def test_question_file_is_well_formed(suite):
    assert h.validate_suite(suite) == []
    assert 40 <= len(suite.questions) <= 50
    assert 8 <= len(suite.of("adversarial")) <= 10


def test_question_file_matches_the_checkout(suite, index):
    assert (
        h.check_checkout(suite, index, REPO) == []
    ), "docs changed under the golden questions: update questions.yaml and rerun the eval"


def test_validate_suite_catches_problems(suite):
    q = suite.questions
    dup = h.Suite(1, q + (q[0],), suite.gates, {}, ())
    assert any("duplicate" in p for p in h.validate_suite(dup))
    broken = h.Suite(1, q[:5], suite.gates, {}, ())
    assert any("questions; the roadmap asks" in p for p in h.validate_suite(broken))
    bad_regex = h.Suite(1, (*q[:-1], h.Question("Z1", "adversarial", "x", must_not_match=("(",))), suite.gates, {}, ())
    assert any("bad regex" in p for p in h.validate_suite(bad_regex))


def test_a_vanished_heading_or_file_fails_loudly(suite, index):
    ghost = h.Question(
        "Z9", "in_corpus", "q", intent="docs_question", sources=(h.Source("docs/SLO.md", "no such heading"),)
    )
    s = h.Suite(1, (*suite.questions, ghost), suite.gates, {}, ("docs/NOPE.md",))
    problems = h.check_checkout(s, index, REPO)
    assert any("docs/NOPE.md" in p for p in problems) and any("Z9" in p for p in problems)


# ----------------------------------------------------------------------------- arithmetic on synthetic rows


def _row(qid, group, *hits):
    return h.RetrievalRow(qid, group, tuple(h.RowHit(s, c, e, "a.md", "A") for s, c, e in hits))


def test_served_applies_floors_before_taking_k():
    row = _row("Q", "in_corpus", (9, 0.1, False), (8, 0.9, False), (7, 0.9, False), (6, 0.9, False), (5, 0.9, True))
    assert [x.score for x in h.served(row, 0, 0)] == [9, 8, 7]
    assert [x.score for x in h.served(row, 0, 0.5)] == [8, 7, 6]
    assert [x.score for x in h.served(row, 5.5, 0.5, k=5)] == [8, 7, 6]
    # a floor can PROMOTE an expected chunk into the top 3 by removing the noise above it, exactly as search() does
    row2 = _row("Q", "in_corpus", (9, 0.1, False), (8, 0.1, False), (7, 0.1, False), (6, 0.9, True))
    assert not h.row_correct(row2, 0, 0) and h.row_correct(row2, 0, 0.5)


def test_point_metrics_and_ranking():
    rows = [
        _row("I1", "in_corpus", (9, 0.9, True)),
        _row("I2", "in_corpus", (9, 0.9, False), (8, 0.9, True)),
        _row("I3", "in_corpus", (9, 0.9, False)),
        _row("O1", "out_of_corpus", (5, 0.9, False)),
        _row("O2", "out_of_corpus", (9, 0.2, False)),
    ]
    m = h.point_metrics(rows, 6, 0.5)
    assert m["hit_at_3_served"] == pytest.approx(2 / 3) and m["correct_refusal"] == pytest.approx(1.0)
    assert m["hit_misses"] == ["I3"] and m["refusal_misses"] == []
    r = h.ranking_metrics(rows)
    assert r["hit_at_1"] == pytest.approx(1 / 3) and r["hit_at_3"] == pytest.approx(2 / 3)
    assert r["ranks"] == {"I1": 1, "I2": 2, "I3": None}


def test_fit_prefers_the_middle_of_a_plateau_and_is_deterministic():
    rows = [_row("I1", "in_corpus", (10, 0.9, True)), _row("O1", "out_of_corpus", (4, 0.9, False))]
    a = h.fit(rows, h.Targets(), score_grid=tuple(range(0, 13)), coverage_grid=(0.0,))
    b = h.fit(rows, h.Targets(), score_grid=tuple(range(0, 13)), coverage_grid=(0.0,))
    assert a == b
    assert (a.hit, a.refusal) == (1.0, 1.0)
    assert a.min_score == 7  # optimal scores are 5..10; the middle is 7 or 8, the lower is taken on a tie
    assert a.n_optimal == 6


def test_fit_trades_one_gate_for_the_other_by_closeness():
    rows = [
        _row("I1", "in_corpus", (10, 0.9, True)),
        _row("I2", "in_corpus", (6, 0.9, True)),
        _row("O1", "out_of_corpus", (8, 0.9, False)),
    ]
    f = h.fit(rows, h.Targets(0.85, 0.90), score_grid=tuple(range(0, 13)), coverage_grid=(0.0,))
    assert (f.hit, f.refusal) in {(0.5, 1.0), (1.0, 0.0)}  # no point meets both; one gate is given up, not both


def test_leave_one_out_scores_only_the_left_out_row():
    rows = [_row(f"I{i}", "in_corpus", (10, 0.9, True)) for i in range(3)] + [
        _row(f"O{i}", "out_of_corpus", (3, 0.9, False)) for i in range(3)
    ]
    loo = h.leave_one_out(rows, score_grid=tuple(range(0, 13)), coverage_grid=(0.0,))
    assert loo["hit_at_3_served"] == 1.0 and loo["correct_refusal"] == 1.0 and loo["wrong"] == []
    hard = rows + [_row("O9", "out_of_corpus", (10, 0.9, False))]  # indistinguishable from an answerable question
    assert "O9" in h.leave_one_out(hard, score_grid=tuple(range(0, 13)), coverage_grid=(0.0,))["wrong"]


def test_percentile_is_nearest_rank():
    assert h.percentile([], 95) == 0.0
    assert h.percentile([5], 50) == 5
    assert h.percentile(list(range(1, 101)), 50) == 50 and h.percentile(list(range(1, 101)), 95) == 95
    assert h.percentile([3, 1, 2], 100) == 3


def test_unknown_numbers_is_independent_of_the_product_check():
    ev_items = [{"entity": "docs/SLO.md", "field": "SLO", "value": "99.9 percent over 30 days", "unit": None}]
    assert h.unknown_numbers("It is 99.9 percent [E1].", ev_items) == []
    assert h.unknown_numbers("It is 98 percent.", ev_items) == ["98"]
    assert h.unknown_numbers("Wait forty minutes.", ev_items) == ["forty"]
    assert (
        h.unknown_numbers("Wait one minute.", ev_items) == []
    )  # one..ten are not scanned (the product's own rules cover them)


# ----------------------------------------------------------------------------- the replay is the product


@pytest.mark.parametrize("floors", [(0.0, 0.0), (6.5, 0.4), (3.0, 0.0), (8.0, 0.55), (0.0, 0.7)])
def test_replay_equals_the_real_search(suite, index, floors):
    """If this fails, every fitted number in the report is about a retriever the product does not run."""
    rows = h.collect_rows(index, suite.questions)
    by_id = {q.id: q for q in suite.questions}
    for row in rows:
        found = rag_search.search(
            index,
            h.docs_answer.search_query(by_id[row.qid].question),
            h.SERVED_K,
            min_score=floors[0],
            min_coverage=floors[1],
        )
        real = [(x.chunk.source_path, x.chunk.heading_path, x.score) for x in found.hits]
        replay = [(x.source_path, x.heading_path, x.score) for x in h.served(row, *floors)]
        assert real == replay, row.qid


def test_product_defaults_are_what_the_harness_reports(ev):
    assert ev.defaults == {"min_score": rag_search.DEFAULT_MIN_SCORE, "min_coverage": rag_search.DEFAULT_MIN_COVERAGE}


def test_an_explicit_min_score_keeps_the_old_semantics(index):
    everything = rag_search.search(index, "runbook secrets", 20, min_score=0)
    assert everything.min_coverage == 0.0 and everything.found
    assert rag_search.search(index, "runbook secrets", 20).min_coverage == rag_search.DEFAULT_MIN_COVERAGE


def test_eval_report_is_never_indexed(index):
    assert not rag_corpus.is_allowed(h.REPORT_RELATIVE)
    assert rag_corpus.exclusion_reason(h.REPORT_RELATIVE, (h.REPORT_RELATIVE,)) == "evaluation output"  # not liftable
    assert all(c.source_path != h.REPORT_RELATIVE for c in index.chunks)
    scanned = rag_corpus.scan(REPO)  # present on disk after --write-report, yet neither read nor reported as skipped
    assert h.REPORT_RELATIVE not in scanned.paths and all(p != h.REPORT_RELATIVE for p, _ in scanned.skipped)


# ----------------------------------------------------------------------------- invariants on the real docs


def test_recorded_floors_are_not_undercut(ev, suite):
    floors = suite.floors
    assert ev.at_defaults["hit_at_3_served"] >= floors["hit_at_3_served"] - 1e-9
    refusal = sum(1 for j in ev.judged if j.group == "out_of_corpus" and j.refused) / len(suite.of("out_of_corpus"))
    assert refusal >= floors["correct_refusal_e2e"] - 1e-9
    routed = sum(1 for j in ev.judged if j.group == "in_corpus" and j.intent_ok) / len(suite.of("in_corpus"))
    assert routed >= floors["routed_in_corpus"] - 1e-9


def test_no_answer_cites_an_excluded_path_or_a_chunk_that_is_not_real(ev):
    assert [j.qid for j in ev.judged if j.integrity] == []
    for e in ev.e2e:
        for c in e.citations:
            assert rag_corpus.is_allowed(c["source_path"])


def test_adversarial_cases_are_all_handled(ev):
    assert [j.qid for j in ev.judged if j.group == "adversarial" and not j.passed] == []


def test_live_state_and_other_intents_never_cite(ev):
    for j in ev.judged:
        if j.group == "other_intent":
            assert j.passed and not j.cited, j.qid


def test_every_unfaithful_variant_is_rejected_and_the_standard_framing_is_accepted(ev):
    by = {v.key: v for v in ev.rephrase}
    assert by["F1"].accepted == by["F1"].n > 0
    for key in ("U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8"):
        assert by[key].rejected == by[key].n > 0, key
    assert sum(v.unknown_numbers_accepted for v in ev.rephrase) == 0


def test_the_known_lexical_hole_is_still_the_documented_one(ev):
    """H1 reverses a passage's meaning using only its own words. It is accepted today and the report says so. If this
    starts failing because H1 is now rejected, that is GOOD news: update the report text and move H1 to unfaithful."""
    h1 = next(v for v in ev.rephrase if v.key == "H1")
    assert h1.accepted > 0


def test_failover_scenarios_behave_and_nothing_raises(ev):
    assert ev.failover
    for s in ev.failover:
        assert s.raised == 0, s.key
        assert s.succeeded == s.runs, (s.key, s.attempts)
        assert s.calls_ok, (s.key, s.calls, s.expected_calls)
        assert s.unknown_numbers_accepted == 0


def test_the_report_has_the_required_fields_and_no_secrets(ev):
    text = h.render_report(ev)
    for needle in (
        "**Date:**",
        "**Commit:**",
        "Provider chain used",
        "Corpus:",
        "hit@1",
        "hit@3",
        "leave-one-out",
        "p95",
        "Known hole",
        "What this evaluation does not show",
    ):
        assert needle in text, needle
    assert h.FAKE_KEY not in text


def test_gates_are_reported_with_a_verdict(ev):
    names = [g["name"] for g in ev.gates]
    assert len(names) == 4 and all(isinstance(g["passed"], bool) for g in ev.gates)


# ----------------------------------------------------------------------------- the optional real-provider path (still fake HTTP here)


def test_real_run_refuses_when_nothing_is_configured(ev):
    cited = [(q, e) for q in ev.suite.of("in_corpus") for e in ev.e2e if e.qid == q.id and e.citations]
    with mock.patch.dict(
        os.environ, {k: v for k, v in os.environ.items() if not k.startswith("COPILOT_LLM_")}, clear=True
    ):
        with pytest.raises(h.SuiteError):
            h.run_real(cited, 3)


def test_real_run_labels_and_counts_with_a_fake_http_layer(ev):
    cited = [(q, e) for q in ev.suite.of("in_corpus") for e in ev.e2e if e.qid == q.id and e.citations]
    env = {
        "COPILOT_LLM_ENABLED": "true",
        "COPILOT_LLM_BASE_URL": h.FAKE_URL,
        "COPILOT_LLM_MODEL": "m",
        "COPILOT_LLM_API_KEY": h.FAKE_KEY,
    }

    def fake(settings, messages):
        return h.reply_for(h.VARIANTS[0], messages), "r"

    with mock.patch.dict(os.environ, env), mock.patch.object(llm, "_call_provider", fake):
        run = h.run_real(cited, 3)
    assert run.n == 3 and run.accepted == 3 and run.chain == ["default (m)"]
    assert run.unknown_numbers_accepted == 0 and h.FAKE_KEY not in " ".join(run.chain)
    assert MODE_LLM  # imported for the contract: an accepted answer is mode "llm"


def test_cli_writes_the_report_and_exit_code_reflects_the_gates(tmp_path, capsys):
    root = tmp_path / "repo"
    for rel in [*h.load_suite().corpus_assumes, "docs/runbooks/README.md"]:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((REPO / rel).read_text(encoding="utf-8"), encoding="utf-8")
    for extra in ("docs/model_cards", "docs/runbooks", "docs/copilot"):  # whole allowed folders, as in the checkout
        for src in (REPO / extra).glob("*.md"):
            dest = root / extra / src.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    code = h.main(["--root", str(root), "--no-failover", "--write-report", "--no-fail"])
    out = capsys.readouterr().out
    assert code == 0 and "wrote" in out
    assert (root / h.REPORT_RELATIVE).read_text(encoding="utf-8").startswith("# Copilot evaluation report")
    blocked = h.main(["--root", str(tmp_path / "empty"), "--no-failover"])
    assert blocked == 2 and "BLOCKED" in capsys.readouterr().out


def test_path_helper_is_a_path():
    assert isinstance(h.ROOT, Path) and (h.ROOT / "docs").is_dir()
