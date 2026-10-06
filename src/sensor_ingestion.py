"""
MQTT sensor ingestion for the digital twin.

- Subscribes to sensor topics, validates the JSON payload and stores the five anomaly features through
  ``ingest_samples()`` (T17) -- the same path the live simulator uses. With TELEMETRY_STORE_ENABLED=false the legacy
  ``sensor_readings`` write is used instead (rollback).
- Authenticated (MQTT_USERNAME / MQTT_PASSWORD, optional MQTT_TLS) and bounded: the in-process queue holds at most
  MQTT_QUEUE_MAX (default 10000) messages; on overflow the OLDEST message is dropped and counted in
  ``mqtt_dropped_total{reason="overflow"}``. Unparseable or invalid payloads are counted as ``reason="malformed"``.
- Handles connection drops with exponential backoff retry.
- Mock mode: generates synthetic sensor data (origin ``simulated``) when no broker is available.

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
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from prometheus_client import Counter

from api import config
from api.middleware.metrics import registry as _metrics_registry
from src.timeutil import TimeContractError, parse_timestamp, utc_now

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
    """Payload timestamp -> aware UTC, or None if absent/invalid.

    T12: an offset-less (naive) timestamp is NOT assumed to be UTC; it is rejected by
    ``validate_sensor_payload`` ("Missing or invalid timestamp"). Sensor clocks/zones are
    not verified here (see docs/TIME_POLICY.md).
    """
    if ts is None:
        return None
    try:
        return parse_timestamp(ts)
    except TimeContractError:
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
    now = utc_now()
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
    # T12: a missing/naive/unparseable timestamp raises TimeContractError (no substitution of "now").
    d["timestamp"] = parse_timestamp(d.get("timestamp"))
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
# Metrics and the bounded queue (T17)
# -----------------------------------------------------------------------------

DROP_OVERFLOW = "overflow"  # queue full: the oldest queued message was discarded
DROP_MALFORMED = "malformed"  # not JSON / not an object / failed payload validation
DROP_STORE_ERROR = "store_error"  # the payload could not be written (database error); not retried
DROP_REASONS = (DROP_OVERFLOW, DROP_MALFORMED, DROP_STORE_ERROR)


def _dropped_counter() -> Counter:
    existing = _metrics_registry._names_to_collectors.get("mqtt_dropped_total")  # survives module reloads in tests
    if existing is not None:
        return existing  # type: ignore[return-value]
    counter = Counter(
        "mqtt_dropped_total", "MQTT messages dropped before storage, by reason", ["reason"], registry=_metrics_registry
    )
    for reason in DROP_REASONS:
        counter.labels(reason=reason)  # pre-create so /metrics shows zeros
    return counter


MQTT_DROPPED_TOTAL = _dropped_counter()


class DropOldestQueue:
    """FIFO with a hard bound. ``offer`` never blocks and never raises: when full it discards the OLDEST item and
    counts it, so a burst cannot grow memory and the freshest data survives. Event-loop thread only."""

    def __init__(self, maxsize: int) -> None:
        if maxsize <= 0:
            raise ValueError("maxsize must be positive")
        self.maxsize = maxsize
        self._q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)

    def offer(self, item: dict[str, Any]) -> None:
        if self._q.full():
            self._q.get_nowait()
            MQTT_DROPPED_TOTAL.labels(reason=DROP_OVERFLOW).inc()
        self._q.put_nowait(item)

    async def get(self) -> dict[str, Any]:
        return await self._q.get()

    def get_nowait(self) -> dict[str, Any]:
        return self._q.get_nowait()

    def empty(self) -> bool:
        return self._q.empty()

    def qsize(self) -> int:
        return self._q.qsize()


def parse_message(raw: bytes | str) -> dict[str, Any] | None:
    """Raw MQTT payload -> dict, or ``None`` (counted as malformed). Safe to call from the MQTT thread."""
    try:
        payload = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        MQTT_DROPPED_TOTAL.labels(reason=DROP_MALFORMED).inc()
        return None
    if not isinstance(payload, dict):
        MQTT_DROPPED_TOTAL.labels(reason=DROP_MALFORMED).inc()
        return None
    return payload


def payload_to_samples(payload: dict[str, Any], *, with_sim_time: bool = False) -> list[dict[str, Any]]:
    """One ``ingest_samples`` sample per anomaly feature (the five direct measurands), all at the payload's
    timestamp. ``with_sim_time`` adds ``sim_time`` (required by the store when the origin is ``simulated``).
    Raises ``TimeContractError`` for a missing/naive timestamp."""
    ts = parse_timestamp(payload.get("timestamp"))
    samples = []
    for feature, external_id in config.telemetry_feature_sensors().items():
        sample: dict[str, Any] = {"external_id": external_id, "ts_event": ts, "value": payload.get(feature)}
        if with_sim_time:
            sample["sim_time"] = ts
        samples.append(sample)
    return samples


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
    now = utc_now()
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


async def ingest_payloads(
    payloads: list[dict[str, Any]],
    *,
    origin: str,
    session_factory: Callable[[], Any] | None = None,
    ingest: Callable[[list[dict[str, Any]]], Awaitable[Any]] | None = None,
) -> int:
    """Validate ``payloads`` and write them. Returns how many were accepted for writing.

    Invalid payloads are counted (``mqtt_dropped_total{reason="malformed"}``) and skipped. With the telemetry store
    enabled the five features of each payload go through ``ingest_samples`` in batches of at most
    ``MAX_BATCH`` samples (stream ``live``); otherwise the legacy ``sensor_readings`` row is written.
    ``ingest`` replaces the database write (tests / dry runs).
    """
    valid: list[dict[str, Any]] = []
    for payload in payloads:
        ok, err = validate_sensor_payload(payload)
        if not ok:
            logger.warning("Validation failed: %s", err)
            MQTT_DROPPED_TOTAL.labels(reason=DROP_MALFORMED).inc()
            continue
        valid.append(payload)
    if not valid:
        return 0

    if not config.telemetry_store_enabled() and ingest is None:
        for payload in valid:
            await store_reading(payload_to_state_dict(payload), source="mqtt" if origin == "measured" else "mock")
        return len(valid)

    from src.telemetry.validation import MAX_BATCH

    samples: list[dict[str, Any]] = []
    for payload in valid:
        samples.extend(payload_to_samples(payload, with_sim_time=origin == "simulated"))
    try:
        for start in range(0, len(samples), MAX_BATCH):
            chunk = samples[start : start + MAX_BATCH]
            if ingest is not None:
                await ingest(chunk)
                continue
            from database import get_session
            from src.telemetry.ingest import ingest_samples

            async with (session_factory or get_session)() as session:
                await ingest_samples(session, chunk, stream_id="live", origin=origin)
                await session.commit()
    except Exception:
        MQTT_DROPPED_TOTAL.labels(reason=DROP_STORE_ERROR).inc(len(valid))
        logger.exception("Could not store %d MQTT payload(s)", len(valid))
        return 0
    return len(valid)


async def run_mock_loop() -> None:
    """Generate synthetic sensor payloads at interval and store them (origin ``simulated``)."""
    logger.info("Mock mode: generating synthetic sensor data every %.1fs", MOCK_INTERVAL_SECONDS)
    while True:
        await ingest_payloads([generate_synthetic_payload()], origin="simulated")
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
    username, password = config.mqtt_credentials()
    if username:
        client.username_pw_set(username, password)  # never logged
    if config.mqtt_tls_enabled():
        client.tls_set()  # system CA bundle, certificate and hostname verification on

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            logger.warning("MQTT connect reason_code=%s", reason_code)
            return
        logger.info("MQTT connected, subscribing to %s", MQTT_TOPIC)
        client.subscribe(MQTT_TOPIC, qos=1)
        nonlocal backoff
        backoff = BACKOFF_INITIAL

    def on_message(client, userdata, msg):
        payload = parse_message(msg.payload)  # counts malformed payloads
        if payload is None:
            return
        # Hand over to the event loop; queue_put is DropOldestQueue.offer (bounded, never blocks).
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


async def consume_mqtt_queue(
    queue: DropOldestQueue,
    *,
    session_factory: Callable[[], Any] | None = None,
    ingest: Callable[[list[dict[str, Any]]], Awaitable[Any]] | None = None,
    batch_payloads: int = 100,
) -> None:
    """Drain ``queue`` forever: up to ``batch_payloads`` payloads (5 samples each) per transaction."""
    while True:
        batch = [await queue.get()]
        while len(batch) < batch_payloads and not queue.empty():
            batch.append(queue.get_nowait())
        await ingest_payloads(batch, origin="measured", session_factory=session_factory, ingest=ingest)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


async def main_async() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    from api.startup_checks import validate_mqtt_config

    use_mock = MOCK_SENSORS or not MQTT_BROKER
    validate_mqtt_config(consumer_running=not use_mock)  # production requires MQTT_USERNAME / MQTT_PASSWORD

    if use_mock:
        await run_mock_loop()
        return

    queue = DropOldestQueue(config.mqtt_queue_max())

    loop = asyncio.get_running_loop()
    thread = threading.Thread(
        target=_mqtt_thread,
        args=(queue.offer, loop),
        daemon=True,
    )
    thread.start()

    await consume_mqtt_queue(queue)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
