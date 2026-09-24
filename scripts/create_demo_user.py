#!/usr/bin/env python3
"""One-time setup: register the public dashboard's read-only demo viewer
account (or, with --role operator, an operator account) against the deployed
backend.

Run this once after deploying the backend (or after a DB reset). The
resulting username/password go into the frontend's .env as
VITE_DEMO_USERNAME / VITE_DEMO_PASSWORD (see
twin-stream-insight-main/.env.example).

This is a script, not an app startup step, so that account creation is
an explicit, auditable action -- not something that happens silently
every time the API boots.

Usage:
    # viewer (default) -- what the public dashboard uses
    python scripts/create_demo_user.py --base-url https://your-backend.up.railway.app \
        --username demo_viewer --password <a-real-password>

    # operator -- the server only allows this when it has OPERATOR_REGISTRATION_KEY
    # set, and the same value is sent as the X-Admin-Key header. Prefer the
    # environment variable over --admin-key so the secret stays out of shell history.
    OPERATOR_REGISTRATION_KEY=... python scripts/create_demo_user.py \
        --base-url https://your-backend.up.railway.app \
        --username ops --password <a-real-password> --role operator
"""

import argparse
import os
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="Deployed backend base URL, e.g. https://...railway.app")
    parser.add_argument("--username", default="demo_viewer")
    parser.add_argument("--password", required=True, help="Use a real, unique password -- this account is public-facing")
    parser.add_argument("--role", choices=["viewer", "operator"], default="viewer", help="Account role (default: viewer)")
    parser.add_argument(
        "--admin-key",
        default=os.getenv("OPERATOR_REGISTRATION_KEY"),
        help="Value of the server's OPERATOR_REGISTRATION_KEY; required for --role operator "
        "(defaults to the OPERATOR_REGISTRATION_KEY environment variable)",
    )
    args = parser.parse_args()

    headers = {}
    if args.role == "operator":
        if not args.admin_key:
            parser.error("--role operator requires --admin-key (or the OPERATOR_REGISTRATION_KEY env var)")
        headers["X-Admin-Key"] = args.admin_key

    base_url = args.base_url.rstrip("/")
    response = requests.post(
        f"{base_url}/auth/register",
        json={"username": args.username, "password": args.password, "role": args.role},
        headers=headers,
        timeout=15,
    )
    if response.status_code == 400 and "already registered" in response.text:
        print(f"Account '{args.username}' already exists -- nothing to do.")
        return 0
    if response.status_code == 403 and args.role == "operator":
        print("Server rejected operator registration (403): wrong X-Admin-Key, or the server has no "
              "OPERATOR_REGISTRATION_KEY set.", file=sys.stderr)
        return 1
    response.raise_for_status()
    print(f"Created {args.role} account '{args.username}'.")

    # Sanity check: confirm it can actually log in before you go update .env.
    login = requests.post(
        f"{base_url}/auth/login",
        json={"username": args.username, "password": args.password},
        timeout=15,
    )
    login.raise_for_status()
    print("Login check succeeded -- safe to put these credentials in .env.")
    return 0


if __name__ == "__main__":
    sys.exit(main())