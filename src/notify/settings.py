"""Mail settings, read from the environment at call time (never cached at import)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from api.secrets import read_secret

BACKENDS = ("smtp", "console", "file", "disabled")
TLS_MODES = ("starttls", "ssl", "none")
GMAIL_HOST = "smtp.gmail.com"
GMAIL_PORT = 587


@dataclass(frozen=True)
class NotifySettings:
    backend: str
    owner_email: str
    from_addr: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    tls: str
    timeout_s: float
    file_dir: str
    public_base_url: str
    production: bool

    @property
    def links_allowed(self) -> bool:
        """Links are only built from an https base URL in production; http is fine for local development."""
        if not self.public_base_url:
            return False
        return self.public_base_url.startswith("https://") or not self.production


def _float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


def load_settings() -> NotifySettings:
    production = os.getenv("ENVIRONMENT", "development").strip().lower() == "production"
    raw_backend = os.getenv("ACCESS_NOTIFY_BACKEND", "").strip().lower()
    if not raw_backend:
        raw_backend = "disabled" if production else "console"
    backend = raw_backend if raw_backend in BACKENDS else "disabled"

    user = (os.getenv("ACCESS_NOTIFY_SMTP_USER") or "").strip()
    # Gmail shows app passwords in four groups separated by spaces; the spaces are not part of the password.
    password = (read_secret("ACCESS_NOTIFY_SMTP_PASSWORD") or "").replace(" ", "").strip()
    tls = (os.getenv("ACCESS_NOTIFY_SMTP_TLS") or "starttls").strip().lower()
    if tls not in TLS_MODES:
        tls = "starttls"
    try:
        port = int(os.getenv("ACCESS_NOTIFY_SMTP_PORT") or (465 if tls == "ssl" else GMAIL_PORT))
    except ValueError:
        port = GMAIL_PORT
    return NotifySettings(
        backend=backend,
        owner_email=(os.getenv("ACCESS_NOTIFY_OWNER_EMAIL") or user).strip(),
        from_addr=(os.getenv("ACCESS_NOTIFY_FROM") or user).strip(),
        smtp_host=(os.getenv("ACCESS_NOTIFY_SMTP_HOST") or GMAIL_HOST).strip(),
        smtp_port=port,
        smtp_user=user,
        smtp_password=password,
        tls=tls,
        timeout_s=_float("ACCESS_NOTIFY_TIMEOUT_S", 10.0),
        file_dir=(os.getenv("ACCESS_NOTIFY_FILE_DIR") or "reports/dev_outbox").strip(),
        public_base_url=(os.getenv("ACCESS_PUBLIC_BASE_URL") or "").strip().rstrip("/"),
        production=production,
    )


def problems(s: NotifySettings) -> list[str]:
    """Human-readable configuration problems (no secret values)."""
    out: list[str] = []
    if s.backend == "disabled":
        out.append("ACCESS_NOTIFY_BACKEND is disabled: no mail will be sent.")
    if s.backend == "smtp":
        if not s.smtp_user:
            out.append("ACCESS_NOTIFY_SMTP_USER is not set.")
        if not s.smtp_password:
            out.append("ACCESS_NOTIFY_SMTP_PASSWORD is not set.")
        if not s.from_addr:
            out.append("ACCESS_NOTIFY_FROM is not set (defaults to the SMTP user).")
    if not s.public_base_url:
        out.append("ACCESS_PUBLIC_BASE_URL is not set: emails cannot contain links.")
    elif s.production and not s.public_base_url.startswith("https://"):
        out.append("ACCESS_PUBLIC_BASE_URL must start with https:// when ENVIRONMENT=production.")
    return out
