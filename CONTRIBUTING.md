# Contributing

## Setup

See `README.md`'s Local Setup section.

## Before submitting a change

- Run `ruff check .` and `pytest tests/ -v` locally — CI will run both anyway, but faster feedback locally.
- If you're touching physics (`src/digital_twin.py`, `src/optimizer.py`, `src/data_generator.py`), read the Physics section of `docs/architecture/system.md` — `DigitalTwin` is the single physics implementation, and the data generator and the RL environment (`src/rl/env.py`) both run it; a physics change moves all three.
- If you change the RL reward function or observation space shape, the existing `models/optimizer/ppo_model.zip` checkpoint becomes stale and must be retrained — note this in your PR description.

## Commit style

Conventional-commit-style prefixes (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `refactor:`) — see the git history for examples from this project's phased build-out.
