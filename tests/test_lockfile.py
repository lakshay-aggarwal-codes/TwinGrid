"""T11 meta-tests: the lockfile and Dockerfile that CI relies on are well-formed.

These fail on the placeholder lock shipped with T11 (unhashed pins converted from a Windows ``pip freeze``) by design:
replace requirements.lock with the output of the CI ``bootstrap`` job / ``pip-compile --generate-hashes``.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements.lock"
DOCKERFILE = ROOT / "Dockerfile"


def _text() -> str:
    raw = LOCK.read_bytes()
    assert not raw.startswith((b"\xff\xfe", b"\xfe\xff")), "requirements.lock is UTF-16; it must be UTF-8"
    assert not raw.startswith(b"\xef\xbb\xbf"), "requirements.lock has a UTF-8 BOM"
    return raw.decode("utf-8")  # raises UnicodeDecodeError if it is not UTF-8


def test_lockfile_is_utf8_with_lf_line_endings():
    text = _text()
    assert "\r" not in text, "requirements.lock must use LF line endings"
    assert "\x00" not in text
    assert text.endswith("\n")


def test_lockfile_has_hash_lines():
    assert "--hash=sha256:" in _text(), "requirements.lock has no --hash= lines (regenerate with --generate-hashes)"


def test_every_pinned_requirement_has_a_hash():
    text = _text().replace("\\\n", " ")  # join pip-compile continuation lines
    requirements = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert requirements, "requirements.lock contains no requirements"
    unhashed = [line.split()[0] for line in requirements if "--hash=sha256:" not in line]
    assert not unhashed, f"requirements without a hash: {unhashed[:5]}"
    unpinned = [line.split()[0] for line in requirements if not re.match(r"^[A-Za-z0-9_.\-\[\]]+==", line.strip())]
    assert not unpinned, f"requirements that are not exact (==) pins: {unpinned[:5]}"


def test_dockerfile_installs_the_lock_with_hashes_and_stays_non_root():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"pip install .*--require-hashes.* -r requirements\.lock", text)
    assert "requirements.txt" not in re.sub(r"#.*", "", text)  # installs only from the lock
    assert re.search(r"^ARG GIT_SHA", text, re.MULTILINE) and re.search(r"^ENV GIT_SHA=", text, re.MULTILINE)
    assert re.search(r"^USER appuser$", text, re.MULTILINE)


def test_ci_markers_are_registered(pytestconfig):
    registered = {line.split(":", 1)[0].strip() for line in pytestconfig.getini("markers")}
    assert {"postgres", "slow", "requires_tf", "requires_sb3"} <= registered
