"""
MQTT sensor ingestion for the digital twin.

- Subscribes to sensor topics, parses JSON into SensorReading, validates and stores to PostgreSQL.
- Handles connection drops with exponential backoff retry.
- Mock mode: generates synthetic sensor data when no broker is available.

Usage:
    python -m src.sensor_ingestion
    MQTT_BROKER=localhost MQTT_TOPIC=digital_twin/sensors  (optional)
    MOCK_SENSORS=1  to force mock mode
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

from .logging_config import log_function_entry, log_function_exit, log_error

load_dotenv()

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Config (env)
# -----------------------------------------------------------------------------

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "digital_twin/sensors")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "digital_twin_ingestion")
MOCK_SENSORS = os.getenv("MOCK_SENSORS", "0").lower() in ("1", "true", "yes")
FRESHNESS_SECONDS = int(os.getenv("SENSOR_FRESHNESS_SECONDS", "300"))  # reject payloads older than 5 min
MOCK_INTERVAL_SECONDS = float(os.getenv("MOCK_INTERVAL_SECONDS", "5.0"))
BACKOFF_INITIAL = float(os.getenv("MQTT_BACKOFF_INITIAL", "1.0"))
BACKOFF_MAX = float(os.getenv("MQTT_BACKOFF_MAX", "60.0"))

# Required keys for a valid sensor payload (same shape as DataCentreState.to_dict)
REQUIRED_KEYS = [
    "timestamp",
    "server_utilisation",
    "outside_temp_C",
    "server_inlet_temp_C",
    "server_outlet_temp_C",
    "it_power_kw",
    "cooling_power_kw",
    "total_power_kw",
    "pue",
    "water_flow_lpm",
    "water_consumed_L",
    "wue",
    "humidity_pct",
    "water_pressure_bar",
    "cooling_mode",
]

# Range checks: (min, max) or None to skip
RANGES: dict[str, tuple[float, float] | None] = {
    "server_utilisation": (0.0, 1.0),
    "outside_temp_C": (-10.0, 55.0),
    "server_inlet_temp_C": (10.0, 35.0),
    "server_outlet_temp_C": (15.0, 55.0),
    "it_power_kw": (0.0, 600.0),
    "cooling_power_kw": (0.0, 300.0),
    "total_power_kw": (0.0, 900.0),
    "pue": (1.0, 5.0),
    "water_flow_lpm": (0.0, 500.0),
    "water_consumed_L": (0.0, 1e6),
    "wue": (0.0, 20.0),
    "humidity_pct": (0.0, 100.0),
    "water_pressure_bar": (0.0, 10.0),
}


def _parse_timestamp(ts: Any) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str) and ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    return None


def validate_sensor_payload(payload: dict[str, Any]) -> tuple[bool, str | None]:
    """
    Validate JSON sensor payload: required keys, range checks, timestamp freshness.
    Returns (True, None) if valid, (False, error_message) otherwise.
    """
    for key in REQUIRED_KEYS:
        if key not in payload:
            return False, f"Missing key: {key}"

    for key, range_spec in RANGES.items():
        if range_spec is None or key not in payload:
            continue
        try:
            v = float(payload[key])
        except (TypeError, ValueError):
            return False, f"Invalid number for {key}: {payload[key]!r}"
        lo, hi = range_spec
        if not (lo <= v <= hi):
            return False, f"{key} out of range [{lo}, {hi}]: {v}"

    ts = _parse_timestamp(payload.get("timestamp"))
    if ts is None:
        return False, "Missing or invalid timestamp"
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = (now - ts).total_seconds()
    if age < -60:
        return False, "Timestamp too far in the future"
    if age > FRESHNESS_SECONDS:
        return False, f"Timestamp too old (age {age:.0f}s > {FRESHNESS_SECONDS}s)"

    cooling_mode = payload.get("cooling_mode")
    if cooling_mode is not None and not isinstance(cooling_mode, str):
        return False, "cooling_mode must be a string"
    if cooling_mode and len(cooling_mode) > 32:
        return False, "cooling_mode too long"

    return True, None


def payload_to_state_dict(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure payload has correct types and keys for SensorReading.from_state_dict."""
    d = dict(payload)
    ts = _parse_timestamp(d.get("timestamp")) or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    d["timestamp"] = ts
    d["server_utilisation"] = float(d["server_utilisation"])
    d["outside_temp_C"] = float(d["outside_temp_C"])
    d["server_inlet_temp_C"] = float(d["server_inlet_temp_C"])
    d["server_outlet_temp_C"] = float(d["server_outlet_temp_C"])
    d["it_power_kw"] = float(d["it_power_kw"])
    d["cooling_power_kw"] = float(d["cooling_power_kw"])
    d["total_power_kw"] = float(d["total_power_kw"])
    d["pue"] = float(d["pue"])
    d["water_flow_lpm"] = float(d["water_flow_lpm"])
    d["water_consumed_L"] = float(d["water_consumed_L"])
    d["wue"] = float(d["wue"])
    d["humidity_pct"] = float(d["humidity_pct"])
    d["water_pressure_bar"] = float(d["water_pressure_bar"])
    d["cooling_mode"] = str(d.get("cooling_mode", "closed_loop"))
    d["anomaly"] = int(d.get("anomaly", 0))
    return d


# -----------------------------------------------------------------------------
# Storage (async, uses database module)
# -----------------------------------------------------------------------------


async def store_reading(state_dict: dict[str, Any], source: str = "mqtt") -> None:
    """Persist one sensor reading to PostgreSQL via database module."""
    try:
        from database import get_session
        from models.db_models import SensorReading

        async with get_session() as session:
            session.add(SensorReading.from_state_dict(state_dict, source))
        logger.debug("Stored reading from %s", source)
    except Exception as e:
        logger.exception("Failed to store reading: %s", e)


# -----------------------------------------------------------------------------
# Mock mode: synthetic data
# -----------------------------------------------------------------------------


def generate_synthetic_payload() -> dict[str, Any]:
    """Generate one synthetic sensor payload within valid ranges."""
    now = datetime.now(timezone.utc)
    utilisation = random.uniform(0.3, 0.95)
    outside = random.uniform(18.0, 32.0)
    inlet = random.uniform(18.0, 26.0)
    outlet = random.uniform(28.0, 42.0)
    it_power = 100.0 + utilisation * 400.0 + random.uniform(-10, 10)
    cooling_power = it_power * random.uniform(0.2, 0.5)
    total_power = it_power + cooling_power
    pue = total_power / it_power if it_power > 1 else 1.0
    water_flow = 50.0 + cooling_power * 0.5 + random.uniform(-5, 5)
    water_consumed = random.uniform(0, 500)
    wue = water_consumed / (it_power * 0.083) if it_power > 1 else 0.0
    humidity = random.uniform(30.0, 60.0)
    pressure = random.uniform(2.0, 5.0)
    modes = ["free_air", "closed_loop", "evaporative", "hybrid"]
    cooling_mode = random.choice(modes)

    return {
        "timestamp": now.isoformat(),
        "server_utilisation": round(utilisation, 4),
        "outside_temp_C": round(outside, 2),
        "server_inlet_temp_C": round(inlet, 2),
        "server_outlet_temp_C": round(outlet, 2),
        "it_power_kw": round(it_power, 2),
        "cooling_power_kw": round(cooling_power, 2),
        "total_power_kw": round(total_power, 2),
        "pue": round(pue, 4),
        "water_flow_lpm": round(water_flow, 2),
        "water_consumed_L": round(water_consumed, 2),
        "wue": round(wue, 4),
        "humidity_pct": round(humidity, 2),
        "water_pressure_bar": round(pressure, 2),
        "cooling_mode": cooling_mode,
        "anomaly": 0,
    }


async def run_mock_loop() -> None:
    """Generate synthetic sensor payloads at interval and store to PostgreSQL."""
    logger.info("Mock mode: generating synthetic sensor data every %.1fs", MOCK_INTERVAL_SECONDS)
    while True:
        payload = generate_synthetic_payload()
        state_dict = payload_to_state_dict(payload)
        await store_reading(state_dict, source="mock")
        await asyncio.sleep(MOCK_INTERVAL_SECONDS)


# -----------------------------------------------------------------------------
# MQTT client (runs in thread, pushes to asyncio via queue)
# -----------------------------------------------------------------------------


def _mqtt_thread(
    queue_put: Any,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Run MQTT client with exponential backoff; on message put payload on queue for async processing."""
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        logger.error("paho-mqtt not installed. Run: pip install paho-mqtt")
        return

    backoff = BACKOFF_INITIAL
    client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            logger.warning("MQTT connect reason_code=%s", reason_code)
            return
        logger.info("MQTT connected, subscribing to %s", MQTT_TOPIC)
        client.subscribe(MQTT_TOPIC, qos=1)
        nonlocal backoff
        backoff = BACKOFF_INITIAL

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Invalid MQTT payload: %s", e)
            return
        # Schedule async handling on the main loop
        loop.call_soon_threadsafe(queue_put, payload)

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        logger.warning("MQTT disconnected: reason_code=%s", reason_code)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    while True:
        try:
            logger.info("Connecting to MQTT %s:%s (backoff=%.1fs)", MQTT_BROKER, MQTT_PORT, backoff)
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as e:
            logger.warning("MQTT connection failed: %s. Retry in %.1fs", e, backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX)


async def consume_mqtt_queue(queue: asyncio.Queue) -> None:
    """Consume payloads from queue: validate and store to DB."""
    while True:
        payload = await queue.get()
        ok, err = validate_sensor_payload(payload)
        if not ok:
            logger.warning("Validation failed: %s", err)
            continue
        state_dict = payload_to_state_dict(payload)
        await store_reading(state_dict, source="mqtt")
        logger.debug("Stored MQTT reading")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


async def main_async() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    use_mock = MOCK_SENSORS or not MQTT_BROKER
    if use_mock:
        await run_mock_loop()
        return

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def put_payload(payload: dict[str, Any]) -> None:
        queue.put_nowait(payload)

    loop = asyncio.get_running_loop()
    thread = threading.Thread(
        target=_mqtt_thread,
        args=(put_payload, loop),
        daemon=True,
    )
    thread.start()

    await consume_mqtt_queue(queue)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
