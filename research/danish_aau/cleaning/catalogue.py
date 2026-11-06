"""Reason-code and flag catalogue (Task 12 PROPOSAL; the owner approves it).

Every code matches the contract pattern ``[a-z][a-z0-9_]{0,63}``. ``status`` says whether v1 of the cleaning code can
produce the code with the evidence on file:

* ``active``        produced by the locked protocol or by a rule that needs no new owner input
* ``needs_owner``   implemented, but OFF until the owner supplies the missing input (limits, run length switch)
* ``reserved``      defined so the vocabulary is closed; v1 never produces it

Nothing here changes the locked protocol or the approved contract.
"""

from __future__ import annotations

import re
from typing import NamedTuple

REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ReasonCode(NamedTuple):
    code: str
    used_for: str  # record_missing | record_flagged | ledger | record_invalid
    status: str  # active | needs_owner | reserved
    meaning: str
    v5_expectation: str


CATALOGUE: tuple[ReasonCode, ...] = (
    ReasonCode(
        "conflict_unresolved_tie",
        "record_missing",
        "active",
        "Two or more different canonical values for one cell inside one repeated-timestamp group and no documented "
        "authority field: the cell is missing (observed=false). Locked protocol [duplicates].tie_reason.",
        "Tier 1 count is produced by the owner-run local script (Task 6 all-channel total: 10,602 cells)",
    ),
    ReasonCode(
        "blank_cell",
        "record_missing",
        "active",
        "Every row of the group has a blank cell: not observed. A blank never conflicts with a value (protocol).",
        "0 in the 51 power/temperature columns (Task 4: no blanks there)",
    ),
    ReasonCode(
        "out_of_range",
        "record_flagged",
        "needs_owner",
        "Canonical value outside owner-supplied limits. Flagged, value kept, never clipped. No limits are "
        "established (Task 4 ranges are descriptive, not limits), so the range check is NOT evaluated by default.",
        "0 until the owner supplies limits",
    ),
    ReasonCode(
        "flatline_run",
        "record_flagged",
        "needs_owner",
        "Cell inside a run of at least N identical canonical values at consecutive stored seconds (step <= the "
        "protocol gap step). N defaults to the protocol screening value (10) but the flag is applied only when the "
        "owner switches it on; the local script reports how many cells it WOULD flag.",
        "reported as aggregates only; not applied",
    ),
    ReasonCode(
        "source_authority_rule",
        "ledger",
        "reserved",
        "Conflict resolved by a documented source authority field. The protocol's authority_fields list is empty, "
        "so the code is never produced.",
        "0",
    ),
    ReasonCode(
        "non_numeric_value",
        "record_invalid",
        "reserved",
        "A cell that is not a finite number. The Task 11 adapter refuses such a file (typed error) instead of "
        "emitting an invalid record, so v1 never produces it.",
        "0 (Task 4: 0 malformed rows)",
    ),
    ReasonCode(
        "dropped_row_reason_undefined",
        "ledger",
        "reserved",
        "Placeholder name for the dropped_with_reason disposition: the locked protocol defines no drop rule, so no "
        "row is dropped and no drop reason exists. Defined only so a future rule must add its own code.",
        "0",
    ),
)

CODES = tuple(c.code for c in CATALOGUE)

# small integer codes used inside arrays (never written to L1 files, which carry the text)
REASON_NONE, REASON_TIE, REASON_BLANK = 0, 1, 2
REASON_TEXT = {REASON_TIE: "conflict_unresolved_tie", REASON_BLANK: "blank_cell"}
FLAG_NONE, FLAG_OUT_OF_RANGE, FLAG_FLATLINE = 0, 1, 2  # lower number wins when both apply
FLAG_TEXT = {FLAG_OUT_OF_RANGE: "out_of_range", FLAG_FLATLINE: "flatline_run"}

ROW_DISPOSITIONS = (
    "retained",
    "exact_duplicate",
    "conflict_resolved_by_source_rule",
    "conflict_cell_missing",
    "flagged",
    "dropped_with_reason",
)
D_RETAINED, D_EXACT_DUP, D_CONFLICT_RULE, D_CONFLICT_MISSING, D_FLAGGED, D_DROPPED = range(6)


def validate_catalogue() -> None:
    seen = set()
    for c in CATALOGUE:
        if not REASON_RE.match(c.code) or c.code in seen:
            raise ValueError(f"bad or duplicate reason code {c.code!r}")
        if c.status not in ("active", "needs_owner", "reserved"):
            raise ValueError(f"bad status for {c.code}")
        seen.add(c.code)
