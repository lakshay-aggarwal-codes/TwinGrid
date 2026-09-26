"""
Real-time alert system for the digital twin.

- Alert types: thermal, water leak, anomaly, PUE/WUE exceeded, cooling override.
- Channels: email (smtplib), Slack webhook, dashboard (PostgreSQL).
- Severity: INFO, WARNING, CRITICAL.
- Cooldown: same alert type at most once per 15 minutes.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Cooldown: do not send same alert type more than once per this period
COOLDOWN_MINUTES = 15


class AlertType:
    """Alert type constants for the real-time alert system."""

    THERMAL_WARNING = "THERMAL_WARNING"
    WATER_LEAK_DETECTED = "WATER_LEAK_DETECTED"
    ANOMALY_SPIKE = "ANOMALY_SPIKE"
    PUE_EXCEEDED = "PUE_EXCEEDED"
    WUE_EXCEEDED = "WUE_EXCEEDED"
    COOLING_MODE_OVERRIDE = "COOLING_MODE_OVERRIDE"


class Severity:
    """Alert severity levels."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertManager:
    """
    Manages real-time alerts: persistence to PostgreSQL, delivery via email,
    Slack webhook, and dashboard. Enforces per-type cooldown (15 min).
    """

    def __init__(
        self,
        *,
        cooldown_minutes: int = COOLDOWN_MINUTES,
        enable_email: bool = True,
        enable_slack: bool = True,
    ) -> None:
        self.cooldown_minutes = cooldown_minutes
        self._last_sent: dict[str, datetime] = {}
        self._enable_email = enable_email
        self._enable_slack = enable_slack
        self._smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self._smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self._smtp_user = os.getenv("SMTP_USER", "")
        self._smtp_password = os.getenv("SMTP_PASSWORD", "")
        self._alert_email_to = os.getenv("ALERT_EMAIL_TO", "")
        self._slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")

    def _in_cooldown(self, alert_type: str) -> bool:
        last = self._last_sent.get(alert_type)
        if last is None:
            return False
        return datetime.now(timezone.utc) - last < timedelta(minutes=self.cooldown_minutes)

    def _mark_sent(self, alert_type: str) -> None:
        self._last_sent[alert_type] = datetime.now(timezone.utc)

    def _send_email(self, subject: str, body: str, severity: str) -> None:
        if not self._enable_email or not self._smtp_user or not self._alert_email_to:
            return
        try:
            msg = MIMEMultipart()
            msg["Subject"] = f"[{severity}] {subject}"
            msg["From"] = self._smtp_user
            msg["To"] = self._alert_email_to
            msg.attach(MIMEText(body, "plain"))
            with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                server.starttls(context=ssl.create_default_context())
                if self._smtp_password:
                    server.login(self._smtp_user, self._smtp_password)
                server.sendmail(self._smtp_user, self._alert_email_to.split(","), msg.as_string())
            logger.debug("Alert email sent: %s", subject)
        except Exception as e:
            logger.warning("Failed to send alert email: %s", e)

    def _send_slack(self, alert_type: str, message: str, severity: str) -> None:
        if not self._enable_slack or not self._slack_webhook_url:
            return
        try:
            payload = {
                "text": f"[{severity}] *{alert_type}*: {message}",
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self._slack_webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status != 200:
                    logger.warning("Slack webhook returned %s", resp.status)
        except Exception as e:
            logger.warning("Failed to send Slack alert: %s", e)

    async def raise_alert(
        self,
        session: Any,
        alert_type: str,
        severity: str,
        message: str,
        *,
        score: float = 0.0,
        sensor_reading_id: int | None = None,
    ) -> bool:
        """
        Record an alert in PostgreSQL and send via enabled channels (subject to cooldown).

        Args:
            session: AsyncSession from get_db() for inserting Alert.
            alert_type: One of AlertType.* constants.
            severity: One of Severity.* constants.
            message: Human-readable description.
            score: Optional numeric value (e.g. anomaly score, PUE value).
            sensor_reading_id: Optional FK to sensor_readings.

        Returns:
            True if alert was sent to any channel (not in cooldown), False if cooldown only.
        """
        from models.db_models import Alert

        alert_row = Alert(
            score=score,
            alert=True,
            type=alert_type,
            message=message,
            severity=severity,
            sensor_reading_id=sensor_reading_id,
        )
        session.add(alert_row)
        await session.flush()

        sent = False
        if not self._in_cooldown(alert_type):
            subject = f"Digital Twin: {alert_type}"
            body = f"{alert_type} [{severity}]\n{message}\nScore: {score}"
            self._send_email(subject, body, severity)
            self._send_slack(alert_type, message, severity)
            self._mark_sent(alert_type)
            sent = True
        else:
            logger.debug("Alert %s in cooldown, stored only", alert_type)

        return sent


def get_alert_manager() -> AlertManager:
    """Return the default AlertManager instance (e.g. for dependency injection)."""
    if not hasattr(get_alert_manager, "_instance"):
        get_alert_manager._instance = AlertManager()
    return get_alert_manager._instance
