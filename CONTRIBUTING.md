# Contributing

## Setup

See `README.md`'s Local Setup section.

## Before submitting a change

- Run `ruff check .` and `pytest tests/ -v` locally — CI will run both anyway, but faster feedback locally.
- If you're touching physics (`src/digital_twin.py`, `src/optimizer.py`, `src/data_generator.py`), check `ARCHITECTURE.md`'s "Physics: single source of truth" section — the digital twin and the RL environment intentionally have separate implementations for different reasons; know why before changing either.
- If you change the RL reward function or observation space shape, the existing `models/optimizer/ppo_model.zip` checkpoint becomes stale and must be retrained — note this in your PR description.

## Commit style

Conventional-commit-style prefixes (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `refactor:`) — see the git history for examples from this project's phased build-out.
