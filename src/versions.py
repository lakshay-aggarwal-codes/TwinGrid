"""Version / provenance constants stamped onto persisted records (T1b).

Kept dependency-free on purpose: importable from anywhere (including tests and
tooling) without pulling in the twin or any ML library.
"""

# Identifies the simulator physics that produced a stored number. "legacy-0" is
# the physics as it exists today (uncalibrated, not validated against measured
# data). Changed only by a deliberate physics revision (T7) -- never edited to
# relabel history.
PHYSICS_VERSION = "legacy-0"

# `origin` vocabulary used by every current writer: derived from the simulator,
# never measured. (Further values arrive with T10; see the roadmap.)
ORIGIN_SIMULATED = "simulated"
