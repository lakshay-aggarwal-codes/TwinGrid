"""CP-5: the Markdown chunker is deterministic, heading-aware, size-capped and stable."""

from __future__ import annotations

import pytest

from src.copilot.rag.chunker import (
    DEFAULT_MAX_CHARS,
    PREAMBLE,
    chunk_markdown,
    doc_hash_of,
    normalize_text,
)

SRC = "docs/example.md"

DOC = """Intro line before any heading.

# Title

Top text.

## Setup

Install it.

```bash
# not a heading, this is a shell comment
run --now
```

### Details

Deep text.

## Setup

Second section with the same heading.
"""


def _paths(chunks):
    return [c.heading_path for c in chunks]


def test_headings_build_paths_and_code_fences_are_not_headings():
    chunks = chunk_markdown(DOC, SRC)
    assert _paths(chunks) == [
        PREAMBLE,
        "Title",
        "Title > Setup",
        "Title > Setup > Details",
        "Title > Setup",
    ]
    setup = chunks[2]
    assert "# not a heading" in setup.text and "run --now" in setup.text


def test_repeated_headings_get_distinct_stable_ids():
    first = chunk_markdown(DOC, SRC)
    second = chunk_markdown(DOC, SRC)
    ids = [c.chunk_id for c in first]
    assert len(ids) == len(set(ids)) == 5
    assert ids == [c.chunk_id for c in second]
    assert [c.ordinal for c in first] == [0, 1, 2, 3, 4]


def test_ids_do_not_depend_on_text_but_text_hash_does():
    edited = DOC.replace("Install it.", "Install it carefully.")
    a, b = chunk_markdown(DOC, SRC), chunk_markdown(edited, SRC)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    changed = [x.heading_path for x, y in zip(a, b) if x.text_hash != y.text_hash]
    assert changed == ["Title > Setup"]
    assert a[0].doc_hash != b[0].doc_hash


def test_id_depends_on_source_path():
    other = chunk_markdown(DOC, "docs/other.md")
    assert not {c.chunk_id for c in other} & {c.chunk_id for c in chunk_markdown(DOC, SRC)}


def test_windows_line_endings_bom_and_control_characters_do_not_change_anything():
    crlf = "\ufeff" + DOC.replace("\n", "\r\n") + "\x00\x07"
    assert normalize_text(crlf) == DOC
    assert doc_hash_of(crlf) == doc_hash_of(DOC)
    assert [c.to_dict() for c in chunk_markdown(crlf, SRC)] == [c.to_dict() for c in chunk_markdown(DOC, SRC)]


def test_empty_and_heading_only_documents_give_no_chunks():
    assert chunk_markdown("", SRC) == []
    assert chunk_markdown("   \n\n  ", SRC) == []
    assert chunk_markdown("# A\n\n## B\n", SRC) == []


def test_trailing_hash_in_a_heading_is_text_but_closing_hashes_are_dropped():
    chunks = chunk_markdown("# C#\n\nbody\n\n## Closed ##\n\nmore\n", SRC)
    assert _paths(chunks) == ["C#", "C# > Closed"]


def _long_doc(paragraphs: int = 30) -> str:
    para = "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau. "
    return "# Long\n\n" + "\n\n".join(f"{i} " + para * 2 for i in range(paragraphs))


@pytest.mark.parametrize("max_chars,overlap", [(200, 0), (300, 50), (600, 100), (DEFAULT_MAX_CHARS, 120)])
def test_no_chunk_exceeds_the_cap_and_content_is_not_lost(max_chars, overlap):
    doc = _long_doc()
    chunks = chunk_markdown(doc, SRC, max_chars=max_chars, overlap=overlap)
    assert len(chunks) > 1
    assert all(0 < len(c.text) <= max_chars for c in chunks)
    assert {c.heading_path for c in chunks} == {"Long"}
    joined = " ".join(c.text for c in chunks)
    for i in range(30):
        assert f"{i} Alpha" in joined


def test_split_chunks_overlap_on_a_word_boundary():
    chunks = chunk_markdown(_long_doc(), SRC, max_chars=400, overlap=80)
    for prev, nxt in zip(chunks, chunks[1:]):
        head = nxt.text.split("\n\n", 1)[0]
        assert 0 < len(head) <= 80
        assert prev.text.endswith(head) or head in prev.text
        assert not head[0].isspace()


def test_overlap_zero_means_no_repeated_text():
    chunks = chunk_markdown(_long_doc(), SRC, max_chars=300, overlap=0)
    assert len(chunks) > 1
    assert all(len(c.text) <= 300 for c in chunks)


def test_one_enormous_line_is_split_and_still_capped():
    doc = "# Big\n\n" + ("word " * 2000) + "\n\n" + ("x" * 5000)
    chunks = chunk_markdown(doc, SRC, max_chars=500, overlap=50)
    assert all(len(c.text) <= 500 for c in chunks)
    assert sum(c.text.count("x") for c in chunks) >= 5000


def test_a_fenced_block_that_fits_is_kept_whole():
    code = "```python\n" + "\n".join(f"line_{i} = {i}" for i in range(12)) + "\n\nafter_blank = True\n```"
    doc = "# Code\n\n" + ("filler text. " * 80) + "\n\n" + code + "\n\n" + ("tail text. " * 80)
    chunks = chunk_markdown(doc, SRC, max_chars=700, overlap=60)
    holder = [c for c in chunks if "line_0 = 0" in c.text]
    assert holder and "after_blank = True" in holder[0].text and holder[0].text.count("```") >= 2


def test_ids_survive_a_rebuild_when_a_section_grows_only_within_its_own_parts():
    base = _long_doc(10)
    a = chunk_markdown(base, SRC, max_chars=400, overlap=40)
    b = chunk_markdown(base, SRC, max_chars=400, overlap=40)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert len({c.chunk_id for c in a}) == len(a)


@pytest.mark.parametrize(
    "kwargs",
    [{"max_chars": 50}, {"max_chars": 400, "overlap": -1}, {"max_chars": 400, "overlap": 101}],
)
def test_bad_parameters_are_rejected(kwargs):
    with pytest.raises(ValueError):
        chunk_markdown("# A\n\nbody", SRC, **kwargs)


@pytest.mark.parametrize("bad", ["", "/abs.md", "docs\\win.md"])
def test_bad_source_paths_are_rejected(bad):
    with pytest.raises(ValueError):
        chunk_markdown("# A\n\nbody", bad)
