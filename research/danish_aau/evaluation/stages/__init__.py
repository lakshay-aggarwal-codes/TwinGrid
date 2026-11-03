"""Stage implementations. Importing this package registers every stage that exists in the current phase.

Phase 1: ``preflight``. Phase 2: ``prepare``. Later phases add modules here and import them below.
"""

from . import preflight, prepare  # noqa: F401  (importing registers the stages)
