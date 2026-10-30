"""Facility-data calibration workflow for physics v2 (roadmap Task 23).

This package is the PIPELINE. It contains no facility data and no fitted parameters. A result carries the
label "calibrated to dataset <id>" only when it was produced from measured (non-synthetic) data AND the
pre-registered acceptance test on the untouched test block passed. See ``docs/tasks/Task23_calibration_REPORT.md``.
"""

from .data import CalibrationData, CalibrationDataError, from_tidy_rows
from .fit import (
    CalibrationError,
    TestBlockAlreadyScored,
    calibrate,
    make_preregistration,
)

__all__ = [
    "CalibrationData",
    "CalibrationDataError",
    "CalibrationError",
    "TestBlockAlreadyScored",
    "calibrate",
    "from_tidy_rows",
    "make_preregistration",
]
