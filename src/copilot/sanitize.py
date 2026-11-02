"""CP-8: making retrieved documentation inert, spotting instruction-like text, and scrubbing text for cloud providers.

Pure Python: no model, no network, no database. Three jobs.

* :func:`neutralize` turns quoted documentation into plain data: Unicode is normalised (NFKC, so full-width ``［Ｅ１］`` or
  ``＜script＞`` become the ASCII forms that are then removed), invisible and control characters are dropped (so
  ``ig<ZWSP>nore`` cannot dodge a check), and every control marker is removed: links, angle brackets, code fences,
  ``{{ }}`` placeholders, ``[E#]`` lookalikes, the ``BEGIN_DATA`` / ``END_DATA`` delimiters of the model prompt, chat-template
  tokens (``<|im_start|>``, ``[INST]``, ``<<SYS>>``) and ``system:`` style role labels.
* :func:`injection_cues` names the kinds of instruction-like text a passage contains ("ignore previous instructions",
  role play, asking for the prompt, forged markers, active markup). It only NAMES them. The caller decides what a cue
  means (``answer.py`` keeps quoting the passage as data but never lets a model rephrase it).
* :func:`scrub_for_cloud` removes what a remote provider must never receive from free text: emails, IP addresses, UUIDs,
  long token-like strings, ``alert 42`` references, every number, and the terms the caller names (the user's name).

This is a lexical defence. It does not understand meaning, does not map look-alike letters from other alphabets (a
Cyrillic ``а`` stays one) and cannot prove a passage is harmless; ``docs/security/COPILOT_THREATS.md`` lists that as
residual risk.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

# ----------------------------------------------------------------------------- normalisation and control markers

_WHITESPACE_CONTROLS = frozenset("\t\n\r\x0b\x0c\u2028\u2029")
_URL = re.compile(r"(?i)\b(?:https?|ftp|file|javascript|data|mailto)\s*:\S*|\bwww\.\S+")
_MARKUP = re.compile(r"[<>]|`{3,}")
_CHAT_TOKENS = re.compile(
    r"(?i)<\|[^|<>\n]{0,40}\|>|\[/?\s*(?:INST|SYS)\s*\]|<<\s*/?\s*SYS\s*>>|(?:^|\s)#{2,}\s*(?:instruction|system|assistant|user|response)\b"
)
_DATA_MARK = re.compile(r"(?i)\b(?:BEGIN|END)[_ ]DATA\b")
_ROLE_LABEL = re.compile(r"(?i)\b(system|assistant|developer|user|human)\s*:")


def normalize(text: str) -> str:
    """NFKC, then drop invisible/format/control characters (line breaks and tabs become spaces)."""
    out: list[str] = []
    for ch in unicodedata.normalize("NFKC", str(text)):
        if ch in _WHITESPACE_CONTROLS:
            out.append(" ")
        elif unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co"):
            continue  # zero-width, bidi override, BOM, private use, other controls
        else:
            out.append(ch)
    return "".join(out)


def neutralize(text: str) -> str:
    """Quoted documentation made inert: no link, markup, placeholder, evidence-marker lookalike, prompt delimiter,
    chat-template token or role label. One line, single spaces."""
    out = normalize(text)
    out = _CHAT_TOKENS.sub(" ", out)
    out = _URL.sub("(link removed)", out)
    out = _DATA_MARK.sub("data marker", out)
    out = _MARKUP.sub(" ", out).replace("{{", " ").replace("}}", " ").replace("{", "(").replace("}", ")")
    out = re.sub(r"\[(E\d+)\]", r"(\1)", out)
    out = _ROLE_LABEL.sub(lambda m: f"{m.group(1)} -", out)
    return re.sub(r"\s+", " ", out).strip()


# ----------------------------------------------------------------------------- instruction-like text

WARN_PASSAGE_FLAGGED = (
    "docs_passage_flagged"  # every passage found has cues: quoted as data only, no model may rephrase it
)
WARN_PASSAGE_WITHHELD = "docs_passage_withheld"  # a passage with cues was left out because clean passages were found

CUE_OVERRIDE = "override_instructions"
CUE_ROLE_PLAY = "role_play"
CUE_REVEAL = "reveal_prompt"
CUE_AUTHORITY = "claims_authority"
CUE_STEERING = "steers_answer"
CUE_MARKER = "forged_marker"
CUE_MARKUP = "active_markup"

_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        CUE_OVERRIDE,
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass|skip)\b[^.\n]{0,40}\b(?:instructions?|rules?|prompts?|polic(?:y|ies)|"
            r"guidelines?|constraints?|restrictions?)\b"
        ),
    ),
    (
        CUE_ROLE_PLAY,
        re.compile(
            r"\b(?:you are now|you must now|act as|pretend (?:to be|you are)|from now on,? you|new (?:instructions?|role|persona)|"
            r"role-?play|developer mode|jailbreak|do anything now)\b"
        ),
    ),
    (
        CUE_REVEAL,
        re.compile(
            r"\b(?:reveal|show|print|repeat|output|leak|disclose|display)\b[^.\n]{0,40}\b(?:system prompt|your prompt|your instructions|"
            r"hidden|secret|api key|password|token)s?\b"
        ),
    ),
    (
        CUE_AUTHORITY,
        re.compile(
            r"\b(?:system|admin(?:istrator)?|developer|operator|security team) (?:message|override|notice|instruction|command|says)\b"
        ),
    ),
    (
        CUE_STEERING,
        re.compile(
            r"\b(?:always|only|must|never|just) (?:say|respond|answer|reply|output|write|claim|state)\b"
            r"|\b(?:say|tell|claim|state|respond|reply|answer)\b[^.\n]{0,24}\b(?:everything|all|the system) (?:is|are) (?:normal|fine|ok|okay|healthy|safe)\b"
        ),
    ),
)
_MARKER_RAW = re.compile(
    r"\{\{|\}\}|\[E\d+\]|(?i:\b(?:BEGIN|END)[_ ]DATA\b)|<\|[^|<>\n]{0,40}\||\[/?\s*(?:INST|SYS)\s*\]|<<\s*/?\s*SYS\s*>>"
)
_MARKUP_ACTIVE = re.compile(
    r"(?i)<\s*/?\s*(?:script|iframe|object|embed|img|svg|style|form|link|meta)\b|\bon[a-z]{3,12}\s*=\s*[\"']|javascript\s*:"
)


def injection_cues(text: str) -> tuple[str, ...]:
    """The kinds of instruction-like text in ``text``, in a fixed order. Empty when there is none.

    Ordinary documentation can trip a cue (a security page quoting an attack is the obvious case), so a cue is a reason
    for extra caution, never a verdict."""
    folded = normalize(text)
    lowered = folded.lower()
    found = [name for name, pattern in _CUES if pattern.search(lowered)]
    if _MARKER_RAW.search(folded):
        found.append(CUE_MARKER)
    if _MARKUP_ACTIVE.search(folded):
        found.append(CUE_MARKUP)
    return tuple(found)


# ----------------------------------------------------------------------------- scrubbing free text for cloud providers

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6 = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}\b")
_TOKEN = re.compile(r"\b(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{24,}\b")  # long, has a digit: key, hash, JWT segment, id
_ALERT_REF = re.compile(r"(?i)\b(alert|incident|ticket)\s*(?:id|no\.?|number)?\s*[#:]?\s*\d+\b")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_MIN_TERM = 2


def scrub_for_cloud(text: str, private_terms: Iterable[str] = ()) -> str:
    """``text`` without identifiers or numbers a remote provider must not receive. Never raises."""
    out = normalize(text)
    out = _EMAIL.sub("[email]", out)
    out = _UUID.sub("[id]", out)
    out = _IPV4.sub("[address]", out)
    out = _IPV6.sub("[address]", out)
    out = _TOKEN.sub("[token]", out)
    for term in sorted({t.strip() for t in private_terms if t and len(t.strip()) >= _MIN_TERM}, key=len, reverse=True):
        out = re.sub(rf"(?i)(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", "[user]", out)
    out = _ALERT_REF.sub(lambda m: m.group(1), out)
    out = _NUMBER.sub("#", out)
    return re.sub(r"\s+", " ", out).strip()
