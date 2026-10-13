# JWT key rotation (current state, honestly)

`api/auth.py` signs and verifies with the single `JWT_SECRET_KEY` (HS256, no `kid`, no second verification key).
**Rotation is therefore a hard cutover**: changing the secret invalidates every access token and every WebSocket
session at once; refresh tokens are stored server-side and are not JWTs, so users stay signed in and the client
refreshes transparently. WebSocket tickets are not signed and are unaffected (they live <= 30 s).

Procedure: (1) set the new `JWT_SECRET_KEY` (or `_FILE`) on every API instance in one deploy; (2) expect one burst of
4001/4002 closes and 401s that the frontend recovers from with a refresh; (3) revoke refresh tokens only if the old
secret was compromised AND refresh storage was exposed.

Gap (not implemented here): zero-downtime rotation needs a `kid` header and a list of accepted verification keys.
