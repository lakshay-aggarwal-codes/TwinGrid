#!/usr/bin/env python3
"""One-time setup: register the public dashboard's read-only demo viewer
account against the deployed backend.

Run this once after deploying the backend (or after a DB reset). The
resulting username/password go into the frontend's .env as
VITE_DEMO_USERNAME / VITE_DEMO_PASSWORD (see
twin-stream-insight-main/.env.example).

This is a script, not an app startup step, so that account creation is
an explicit, auditable action -- not something that happens silently
every time the API boots.

Usage:
    python scripts/create_demo_user.py --base-url https://your-backend.up.railway.app \
        --username demo_viewer --password <a-real-password>
"""

import argparse
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="Deployed backend base URL, e.g. https://...railway.app")
    parser.add_argument("--username", default="demo_viewer")
    parser.add_argument("--password", required=True, help="Use a real, unique password -- this account is public-facing")
    args = parser.parse_args()

    response = requests.post(
        f"{args.base_url}/auth/register",
        json={"username": args.username, "password": args.password, "role": "viewer"},
        timeout=15,
    )
    if response.status_code == 400 and "already registered" in response.text:
        print(f"Account '{args.username}' already exists -- nothing to do.")
        return 0
    response.raise_for_status()
    print(f"Created viewer account '{args.username}'.")

    # Sanity check: confirm it can actually log in before you go update .env.
    login = requests.post(
        f"{args.base_url}/auth/login",
        json={"username": args.username, "password": args.password},
        timeout=15,
    )
    login.raise_for_status()
    print("Login check succeeded -- safe to put these credentials in .env.")
    return 0


if __name__ == "__main__":
    sys.exit(main())