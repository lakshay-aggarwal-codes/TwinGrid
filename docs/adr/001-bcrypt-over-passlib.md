# ADR 001: bcrypt directly, not passlib

## Status
Accepted (already implemented before this documentation pass).

## Context
The original auth implementation used `passlib`'s bcrypt wrapper.
`passlib` is unmaintained and breaks with `bcrypt>=4.1` (a version
mismatch that surfaces as a runtime error on password hashing/verification
once a newer bcrypt gets pulled in).

## Decision
Call `bcrypt` directly. bcrypt truncates input at 72 bytes; this is
handled explicitly rather than relying on a wrapper library to do it
transparently.

## Consequences
- One fewer dependency in the auth path, and no exposure to `passlib`'s
  unmaintained status.
- The 72-byte truncation behavior is now the team's own responsibility to
  keep correct (it was previously implicit inside passlib) — see
  `api/auth.py` for where this is handled.
- `requirements.txt` pins `bcrypt>=4.0.1,<6` with no passlib entry at all.
