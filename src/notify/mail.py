"""Access-request mail adapter (contract section 8.2).

``send_access_mail`` never raises and never returns exception text. Result codes are fixed; the backend that
handled the message is always reported. The ``console`` backend logs a redacted summary only; the ``file``
backend (development/tests) writes the full message, including the activation link, to a local outbox.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import secrets
import smtplib
import socket
import ssl
import time
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Literal

from src.notify.settings import NotifySettings, load_settings

logger = logging.getLogger("twingrid.notify")

Kind = Literal["owner_new_request", "activation", "rejected"]
CODES = (
    "ok",
    "not_configured",
    "timeout",
    "auth_failed",
    "refused",
    "invalid_recipient",
    "error",
    "mail_unavailable",
)
_ADDR = re.compile(r"^[^\s@<>\"',;]+@[^\s@<>\"',;]+\.[^\s@<>\"',;]+$")


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    code: str  # one of CODES
    backend: str  # smtp|console|file|disabled


def _text_and_html(kind: Kind, ctx: Mapping[str, str], base: str) -> tuple[str, str, str]:
    e = html.escape
    if kind == "owner_new_request":
        link = f"{base}/admin"
        name, purpose, ref = (
            ctx.get("name", ""),
            ctx.get("purpose", "") or "(none given)",
            ctx.get("ref", ""),
        )
        text = (
            "A new viewer access request is waiting for your decision.\n\n"
            f"Name: {name}\nPurpose: {purpose}\nReference: {ref}\n\n"
            f"Review it in the admin page (sign-in required): {link}\n\n"
            "This message contains no approve or reject link. Decisions are made only inside the signed-in admin page.\n"
        )
        body = (
            "<p>A new viewer access request is waiting for your decision.</p>"
            f"<p><b>Name:</b> {e(name)}<br><b>Purpose:</b> {e(purpose)}<br><b>Reference:</b> {e(ref)}</p>"
            f'<p><a href="{e(link, quote=True)}">Open the admin page</a> (sign-in required)</p>'
            "<p>This message contains no approve or reject link. Decisions are made only inside the signed-in admin page.</p>"
        )
        return "New TwinGrid viewer access request", text, body
    if kind == "activation":
        url, name = ctx.get("activation_url", ""), ctx.get("name", "")
        text = (
            f"Hello {name},\n\nYour TwinGrid viewer access request was approved. "
            f"Set your password here (the link works once and expires):\n{url}\n\n"
            "TwinGrid is a simulation. If you did not request access, ignore this message.\n"
        )
        body = (
            f"<p>Hello {e(name)},</p><p>Your TwinGrid viewer access request was approved. "
            f'<a href="{e(url, quote=True)}">Set your password</a> (the link works once and expires).</p>'
            "<p>TwinGrid is a simulation. If you did not request access, ignore this message.</p>"
        )
        return "Your TwinGrid viewer access was approved", text, body
    name = ctx.get("name", "")
    text = f"Hello {name},\n\nYour TwinGrid viewer access request was not approved.\n"
    body = f"<p>Hello {e(name)},</p><p>Your TwinGrid viewer access request was not approved.</p>"
    return "Your TwinGrid viewer access request", text, body


def _build_message(s: NotifySettings, to: str, subject: str, text: str, body_html: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = s.from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="twingrid.local")
    msg.set_content(text)
    msg.add_alternative(body_html, subtype="html")
    return msg


def _smtp_send_blocking(s: NotifySettings, msg: EmailMessage) -> None:
    if s.tls == "ssl":
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            s.smtp_host,
            s.smtp_port,
            timeout=s.timeout_s,
            context=ssl.create_default_context(),
        )
    else:
        client = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.timeout_s)
    try:
        if s.tls == "starttls":
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if s.smtp_user:
            client.login(s.smtp_user, s.smtp_password)
        client.send_message(msg)
    finally:
        try:
            client.quit()
        except Exception:  # noqa: BLE001 - closing a broken connection must not mask the real outcome
            client.close()


def _classify(exc: BaseException) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "auth_failed"
    # smtplib wraps a read timeout in SMTPServerDisconnected, so look through the exception chain.
    link: BaseException | None = exc
    for _ in range(4):
        if isinstance(link, (TimeoutError, socket.timeout)):
            return "timeout"
        link = link.__cause__ or link.__context__ if link else None
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "invalid_recipient"
    if isinstance(
        exc,
        (ConnectionRefusedError, smtplib.SMTPConnectError, smtplib.SMTPSenderRefused),
    ):
        return "refused"
    return "error"


async def send_access_mail(kind: Kind, to: str, ctx: Mapping[str, str]) -> DeliveryResult:
    s = load_settings()
    backend = s.backend
    if backend == "disabled":
        return DeliveryResult(False, "not_configured", "disabled")
    if not isinstance(to, str) or not _ADDR.match(to) or len(to) > 254:
        return DeliveryResult(False, "invalid_recipient", backend)
    if kind != "rejected" and not s.links_allowed:
        return DeliveryResult(False, "not_configured", backend)
    if backend == "smtp" and not (s.smtp_user and s.smtp_password and s.from_addr):
        return DeliveryResult(False, "not_configured", backend)
    try:
        subject, text, body_html = _text_and_html(kind, ctx, s.public_base_url)
        msg = _build_message(s, to, subject, text, body_html)
    except Exception as exc:  # noqa: BLE001
        logger.warning("access mail build failed kind=%s error_type=%s", kind, type(exc).__name__)
        return DeliveryResult(False, "error", backend)

    if backend == "console":
        domain = to.rsplit("@", 1)[-1]
        logger.info(
            "access mail kind=%s backend=console to=***@%s subject=%r (body not logged)",
            kind,
            domain,
            subject,
        )
        return DeliveryResult(True, "ok", "console")
    if backend == "file":
        try:
            outbox = Path(s.file_dir)
            outbox.mkdir(parents=True, exist_ok=True)
            name = f"{int(time.time() * 1000)}-{kind}-{secrets.token_hex(4)}.eml"
            (outbox / name).write_bytes(bytes(msg))
        except OSError as exc:
            logger.warning(
                "access mail file write failed kind=%s error_type=%s",
                kind,
                type(exc).__name__,
            )
            return DeliveryResult(False, "error", "file")
        return DeliveryResult(True, "ok", "file")
    try:
        await asyncio.to_thread(_smtp_send_blocking, s, msg)
    except Exception as exc:  # noqa: BLE001 - mapped to a fixed code; text is never returned or logged
        code = _classify(exc)
        logger.warning(
            "access mail smtp failed kind=%s code=%s error_type=%s",
            kind,
            code,
            type(exc).__name__,
        )
        return DeliveryResult(False, code, "smtp")
    logger.info("access mail kind=%s backend=smtp sent", kind)
    return DeliveryResult(True, "ok", "smtp")
