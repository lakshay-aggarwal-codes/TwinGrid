#!/usr/bin/env python3
"""Delete expired ``telemetry_sample`` rows (IG-04). For cron or a worker; the live loop runs the same code.

    python scripts/telemetry_retention.py --dry-run     # count only, delete nothing
    python scripts/telemetry_retention.py               # delete until clear (batched)

Retention is ``TELEMETRY_RETENTION_DAYS`` (default 30) unless ``--days`` is given. Only the ``live`` stream is
purged unless ``--stream`` names another. Exit code 0 on success, 1 on error.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import engine, get_session  # noqa: E402
from src.telemetry import retention  # noqa: E402


async def _run(args: argparse.Namespace) -> int:
    total = 0
    try:
        while True:
            res = await retention.purge_expired(
                get_session,
                days=args.days,
                stream_id=args.stream,
                batch_size=args.batch_size,
                max_batches=args.max_batches,
                dry_run=args.dry_run,
            )
            total += res.deleted
            if args.dry_run or not res.more_remaining:
                break
        verb = "would delete" if args.dry_run else "deleted"
        print(f"{verb} {total} '{res.stream_id}' rows with ts_event < {res.cutoff.isoformat()}")
        return 0
    except Exception as exc:  # the message is the exception type only: SQL errors can carry row values
        print(f"telemetry retention failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="count rows that would be deleted; delete nothing")
    p.add_argument("--days", type=int, default=None, help="override TELEMETRY_RETENTION_DAYS")
    p.add_argument("--stream", default=retention.LIVE_STREAM, help="stream to purge (default: live)")
    p.add_argument("--batch-size", type=int, default=retention.DEFAULT_BATCH_SIZE)
    p.add_argument("--max-batches", type=int, default=retention.DEFAULT_MAX_BATCHES)
    return asyncio.run(_run(p.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
