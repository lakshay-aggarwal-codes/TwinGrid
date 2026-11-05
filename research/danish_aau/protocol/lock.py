"""SHA-256 lock of the protocol (Task 5 "Accept when": versioned and SHA-256 locked, owner approves CK-1)."""

from __future__ import annotations

import json
from pathlib import Path

from .protocol import LOCK_PATH, PROTOCOL_PATH, ProtocolError, load_protocol, protocol_sha256


def lock(protocol_path: Path = PROTOCOL_PATH, lock_path: Path = LOCK_PATH) -> dict[str, str]:
    proto = load_protocol(protocol_path)
    if proto["status"]["state"] != "locked":
        raise ProtocolError("set [status] state = 'locked' in the protocol file before running lock")
    open_items = proto.open_items()
    if open_items:
        raise ProtocolError("cannot lock; open items:\n  - " + "\n  - ".join(open_items))
    record = {
        "protocol_file": Path(protocol_path).name,
        "version": str(proto["version"]),
        "sha256_lf_normalised": protocol_sha256(protocol_path),
        "approved_by": proto["status"]["approved_by"],
        "approved_on": proto["status"]["approved_on"],
    }
    Path(lock_path).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return record


def verify(protocol_path: Path = PROTOCOL_PATH, lock_path: Path = LOCK_PATH) -> dict[str, str]:
    """Return the lock record if the protocol file still matches it; raise otherwise."""
    if not Path(lock_path).exists():
        raise ProtocolError("protocol is not locked (no lock file)")
    record = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    proto = load_protocol(protocol_path)
    if proto["status"]["state"] != "locked":
        raise ProtocolError("protocol file is not in state 'locked'")
    actual = protocol_sha256(protocol_path)
    if actual != record["sha256_lf_normalised"]:
        raise ProtocolError(f"protocol changed after locking: {actual} != {record['sha256_lf_normalised']}")
    if str(proto["version"]) != record["version"]:
        raise ProtocolError("protocol version differs from the lock record")
    return record
