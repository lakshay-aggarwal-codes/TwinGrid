"""Reference values from approved evidence (Task 4 profile, Task 6 screen). Used ONLY to compare the adapter / cleaning
output on the owner's machine; they never feed any rule. Source: Tasks 2-8 Completed Context section 5, the Task 6
report and ``reports/task6_screen/task6_screen_output.txt``.
"""

from __future__ import annotations

# key -> rows, first, last, repeated timestamps (groups), extra rows
TASK4: dict[str, dict] = {
    "temperature_power": dict(
        rows=1_371_363, first="2024-09-16 16:58:30", last="2024-10-02 13:53:02", groups=499, extra=575
    ),
    "temperature_power_idle_1": dict(
        rows=58_202, first="2024-09-16 16:59:59", last="2024-09-17 09:10:00", groups=0, extra=0
    ),
    "temperature_power_25": dict(
        rows=90_902, first="2024-09-17 09:40:00", last="2024-09-18 10:55:00", groups=46, extra=46
    ),
    "temperature_power_50": dict(
        rows=77_102, first="2024-09-18 11:25:00", last="2024-09-19 08:50:00", groups=44, extra=44
    ),
    "temperature_power_75": dict(
        rows=88_261, first="2024-09-19 09:20:00", last="2024-09-20 09:51:00", groups=0, extra=0
    ),
    "temperature_power_100": dict(
        rows=258_123, first="2024-09-20 10:21:00", last="2024-09-23 10:03:00", groups=78, extra=78
    ),
    "temperature_power_idle_2": dict(
        rows=789_610, first="2024-09-23 10:33:00", last="2024-10-02 13:53:02", groups=290, extra=290
    ),
    "surrounding_temperatures": dict(
        rows=1_526, first="2024-09-16 16:45:00", last="2024-10-02 14:00:00", groups=0, extra=0
    ),
    "ventilation": dict(rows=4_576, first="2024-09-16 16:45:00", last="2024-10-02 14:05:00", groups=0, extra=0),
}
# Task 4 gives the air-speed files only as a row range, "same span", 10 s nominal cadence and 0 repeats.
TASK4_AIR_SPEED = dict(rows_min=5_822, rows_max=137_027, groups=0, extra=0)

# Task 6 ledger per temperature/power file (all 51 columns): raw rows, unique seconds, retained, exact_duplicate,
# conflict_cell_missing rows, group sizes, cells made missing by ties, blank cells, near-tie cells re-rounded.
TASK6: dict[str, dict] = {
    "temperature_power": dict(
        raw=1_371_363,
        unique=1_370_788,
        retained=1_370_289,
        dup=0,
        conflict=1_074,
        sizes={2: 497, 6: 1, 74: 1},
        ties=10_602,
        blanks=0,
        rerounded=7_032,
    ),
    "temperature_power_100": dict(
        raw=258_123,
        unique=258_045,
        retained=257_967,
        dup=0,
        conflict=156,
        sizes={2: 78},
        ties=1_822,
        blanks=0,
        rerounded=1_405,
    ),
    "temperature_power_25": dict(
        raw=90_902, unique=90_856, retained=90_810, dup=0, conflict=92, sizes={2: 46}, ties=940, blanks=0, rerounded=422
    ),
    "temperature_power_50": dict(
        raw=77_102,
        unique=77_058,
        retained=77_014,
        dup=0,
        conflict=88,
        sizes={2: 44},
        ties=1_077,
        blanks=0,
        rerounded=373,
    ),
    "temperature_power_75": dict(
        raw=88_261, unique=88_261, retained=88_261, dup=0, conflict=0, sizes={}, ties=0, blanks=0, rerounded=469
    ),
    "temperature_power_idle_1": dict(
        raw=58_202, unique=58_202, retained=58_202, dup=0, conflict=0, sizes={}, ties=0, blanks=0, rerounded=344
    ),
    "temperature_power_idle_2": dict(
        raw=789_610,
        unique=789_320,
        retained=789_030,
        dup=0,
        conflict=580,
        sizes={2: 290},
        ties=5_825,
        blanks=0,
        rerounded=3_976,
    ),
}


def compare_profile(key: str, rows: int, first: str, last: str, groups: int, extra: int) -> list[str]:
    ref = TASK4.get(key)
    if ref is None:
        return []
    diffs = []
    for name, obs, exp in (
        ("rows", rows, ref["rows"]),
        ("first", first, ref["first"]),
        ("last", last, ref["last"]),
        ("repeated_timestamp_groups", groups, ref["groups"]),
        ("extra_rows", extra, ref["extra"]),
    ):
        if obs != exp:
            diffs.append(f"{key}: {name} observed {obs!r} vs Task 4 {exp!r}")
    return diffs


def compare_ledger(key: str, stats: dict, counts: dict, unique: int) -> list[str]:
    ref = TASK6.get(key)
    if ref is None:
        return []
    obs = dict(
        raw=stats["raw_rows"],
        unique=unique,
        retained=counts["retained"],
        dup=counts["exact_duplicate"],
        conflict=counts["conflict_cell_missing"],
        sizes=stats["group_sizes"],
        ties=stats["cells_made_missing_all_columns"],
        blanks=stats.get("blank_cells_all_columns"),
    )
    diffs = [f"{key}: {k} observed {obs[k]!r} vs Task 6 {ref[k]!r}" for k in obs if obs[k] != ref[k]]
    return diffs
