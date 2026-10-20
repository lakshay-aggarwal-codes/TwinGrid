"""Send one real test email so you can confirm Gmail delivery without running the whole app.

    python -m src.notify                      # sends an owner-notification test to ACCESS_NOTIFY_OWNER_EMAIL
    python -m src.notify --to me@gmail.com    # choose the recipient
    python -m src.notify --kind activation    # also: owner_new_request | rejected
    python -m src.notify --check              # print configuration problems, send nothing

Reads ``.env`` from the current directory. Never prints the password.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv

from src.notify import mail
from src.notify.settings import load_settings, problems


def _mask(addr: str) -> str:
    local, _, domain = addr.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "(not set)"


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="python -m src.notify")
    p.add_argument("--to", default="")
    p.add_argument(
        "--kind",
        default="owner_new_request",
        choices=["owner_new_request", "activation", "rejected"],
    )
    p.add_argument("--check", action="store_true")
    args = p.parse_args(argv)

    s = load_settings()
    print(f"backend={s.backend} host={s.smtp_host}:{s.smtp_port} tls={s.tls} user={_mask(s.smtp_user)}")
    print(f"owner={_mask(s.owner_email)} base_url={s.public_base_url or '(not set)'}")
    issues = problems(s)
    for line in issues:
        print(f"PROBLEM: {line}")
    if args.check:
        return 1 if issues else 0

    to = args.to or s.owner_email
    ctx = {
        "owner_new_request": {
            "ref": "TESTREF00001",
            "name": "Test Visitor",
            "purpose": "TwinGrid mail self-test",
        },
        "activation": {
            "name": "Test Visitor",
            "activation_url": f"{s.public_base_url}/activate#token=TEST-NOT-A-REAL-TOKEN",
        },
        "rejected": {"name": "Test Visitor"},
    }[args.kind]
    result = asyncio.run(mail.send_access_mail(args.kind, to, ctx))
    print(f"result: ok={result.ok} code={result.code} backend={result.backend} to={_mask(to)}")
    if result.ok and result.backend == "smtp":
        print("Delivered to the mail server. Open Gmail (phone or desktop) and check the inbox, then Spam.")
    elif result.ok:
        print(f"NOTE: backend={result.backend} does not send real email. Set ACCESS_NOTIFY_BACKEND=smtp.")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
