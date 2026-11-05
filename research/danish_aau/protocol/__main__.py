"""python -m research.danish_aau.protocol status|lock|verify  (read-only except `lock`, which writes the lock file)."""

from __future__ import annotations

import sys

from .lock import lock, verify
from .protocol import PROTOCOL_PATH, ProtocolError, load_protocol, protocol_sha256


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    try:
        if cmd == "status":
            proto = load_protocol()
            print(f"protocol {PROTOCOL_PATH.name} version {proto['version']} state {proto['status']['state']}")
            print(f"sha256 (LF-normalised): {protocol_sha256()}")
            items = proto.open_items()
            print(f"open items: {len(items)}")
            for item in items:
                print(f"  - {item}")
            return 0
        if cmd == "lock":
            print(lock())
            return 0
        if cmd == "verify":
            print(verify())
            return 0
        print("usage: python -m research.danish_aau.protocol [status|lock|verify]")
        return 2
    except ProtocolError as exc:
        print(f"PROTOCOL ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
