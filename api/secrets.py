"""Secret loading with support for the ``*_FILE`` convention.

Docker secrets, Kubernetes secrets mounted as files, and Vault Agent /
AWS Secrets Manager sidecars all hand a process its secrets by writing them
to a file on disk rather than injecting plaintext into the environment --
plaintext env vars are readable via ``docker inspect``, ``/proc/<pid>/environ``,
CI job logs, and crash-reporter breadcrumbs in a way a file under a
locked-down mount is not.

This module lets every secret in this app be sourced either way:
``JWT_SECRET_KEY_FILE=/run/secrets/jwt_secret`` is read from disk;
``JWT_SECRET_KEY=...`` still works unchanged for local dev / anything that
doesn't have a secrets manager in front of it yet. The ``_FILE`` variant
wins if both are set, since its presence is a deliberate choice by whatever
deployed the container.
"""

from __future__ import annotations

import os


def read_secret(env_var: str) -> str | None:
    """Return the secret named ``env_var``, preferring ``<env_var>_FILE``.

    Returns ``None`` if neither is set (callers decide whether that's fatal --
    see e.g. ``api/auth.py``'s handling of ``JWT_SECRET_KEY``).
    """
    file_path = os.getenv(f"{env_var}_FILE")
    if file_path:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError as exc:
            raise RuntimeError(
                f"{env_var}_FILE is set to {file_path!r} but could not be read: {exc}"
            ) from exc
    return os.getenv(env_var)
