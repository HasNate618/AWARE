from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from aware.app.action.bt_speaker import ensure_bt_speaker_connected
from aware.app.action.speaker import speak as speak_text
from aware.app.action.speaker import warmup_tts
from aware.app.config import Settings, get_settings, setup_logging
from aware.app.core.event_bus import EventBus
from aware.app.core.loop import RulesLoop
from aware.app.llm.interface import LLMClient, RuleSpec
from aware.app.llm.llama import LlamaLLM
from aware.app.llm.stub import StubLLM
from aware.app.mcu.bus import ActuatorBus, SensorBus
from aware.app.memory.db import EventDB
from aware.app.memory.query import answer_question
from aware.app.memory.sensors import should_log_sensor
from aware.app.memory.summarizer import MemorySummarizer
from aware.app.memory.witness import (
    WITNESS_SOUND_LABELS,
    build_witness_log,
    summaries_for_witness_display,
    witness_events_for_display,
)
from aware.app.parser.nl_parser import parse_rule
from aware.app.perception.interface import PerceptionSnapshot, PerceptionSource, SensorCache
from aware.app.perception.mock_camera import MockCamera
from aware.app.perception.yamnet import YAMNetMic
from aware.app.perception.yolo import YOLOCamera
from aware.app.rules.engine import RulesEngine
from aware.app.rules.store import RulesStore

logger = logging.getLogger(__name__)

MOCK_SNAPSHOT_INTERVAL = 0.5  # seconds
SOUND_LOG_COOLDOWN = 2.0  # seconds


async def perception_loop(
    bus: EventBus,
    camera: PerceptionSource,
    db: EventDB,
    mic: YAMNetMic | None = None,
    sensor_cache: SensorCache | None = None,
) -> None:
    """Run camera + mic in background, publishing snapshots to event bus."""
    await camera.start()
    if isinstance(camera, YOLOCamera):
        asyncio.create_task(camera.run_inference_loop())
    if mic is not None:
        await mic.start()
        asyncio.create_task(mic.run_detection_loop())

    _prev_det_labels: set[str] = set()
    _last_sound_log: dict[str, float] = {}

    try:
        while True:
            cam_snap = await camera.snapshot()
            sounds_snap = await mic.snapshot() if mic else None

            curr_det_labels = {d.label for d in cam_snap.detections}

            merged = PerceptionSnapshot(
                detections=cam_snap.detections,
                sounds=sounds_snap.sounds if sounds_snap else [],
                entered=list(curr_det_labels - _prev_det_labels),
                exited=list(_prev_det_labels - curr_det_labels),
                sensors=dict(sensor_cache.readings) if sensor_cache else {},
                source=cam_snap.source,
                timestamp=cam_snap.timestamp,
            )

            for label in merged.entered:
                conf = max(
                    (d.confidence for d in merged.detections if d.label == label),
                    default=1.0,
                )
                await db.log("detection_enter", {"label": label, "confidence": conf})
            for label in merged.exited:
                await db.log("detection_exit", {"label": label})
            for sound in merged.sounds:
                last = _last_sound_log.get(sound.label, 0.0)
                if merged.timestamp - last >= SOUND_LOG_COOLDOWN:
                    await db.log(
                        "sound",
                        {"label": sound.label, "confidence": sound.confidence},
                    )
                    _last_sound_log[sound.label] = merged.timestamp

            _prev_det_labels = curr_det_labels

            await bus.publish("perception", {"snapshot": merged})
            await asyncio.sleep(MOCK_SNAPSHOT_INTERVAL)
    except asyncio.CancelledError:
        await camera.stop()
        if mic:
            await mic.stop()


async def sensor_loop(
    sensors: SensorBus,
    bus: EventBus,
    db: EventDB,
    settings: Settings,
    sensor_cache: SensorCache | None = None,
) -> None:
    """Read sensors periodically; log to DB on interval or significant change."""
    last_logged: dict[str, tuple[float, float]] = {}
    try:
        while True:
            readings = await sensors.read_all()
            now = time.time()
            sensor_data: dict[str, float] = {}
            for r in readings:
                sensor_data[r.sensor] = r.value
                if should_log_sensor(
                    r.sensor,
                    r.value,
                    now,
                    last_logged,
                    settings.sensor_log_interval,
                ):
                    await db.log(
                        f"sensor:{r.sensor}",
                        {
                            "label": r.sensor,
                            "value": r.value,
                            "unit": r.unit,
                        },
                    )
                    last_logged[r.sensor] = (r.value, now)
            if sensor_cache is not None:
                sensor_cache.update(sensor_data)
            await asyncio.sleep(settings.sensor_read_interval)
    except asyncio.CancelledError:
        pass


def action_handler_factory(db: EventDB, bus: EventBus, actuators: ActuatorBus | None = None) -> Any:
    """Create a handler that logs actions with detection context to the database."""

    async def handle_action(event: dict[str, Any]) -> None:
        rule_name = event.get("rule", "unknown")
        action_type = event.get("action", "log")
        params = event.get("params", {})
        detection = event.get("detection", {})
        action_params = params.get("params", {})
        logger.info(
            "[action] rule=%s action=%s detection=%s",
            rule_name,
            action_type,
            detection.get("label", "none"),
        )

        # Execute the action
        if action_type == "speak":
            text = action_params.get("text", "")
            asyncio.create_task(speak_text(text))

        elif action_type in ("led_flash", "led_on") and actuators:
            rgb_str = action_params.get("rgb", "255,255,255")
            try:
                parts = [int(x.strip()) for x in rgb_str.strip("()").split(",")]
                r, g, b = parts[0], parts[1], parts[2]
            except Exception:
                r, g, b = 255, 255, 255
            if action_type == "led_flash":
                # Flash 3 times
                for _ in range(3):
                    await actuators.set_rgb(r, g, b)
                    await asyncio.sleep(0.15)
                    await actuators.set_rgb(0, 0, 0)
                    await asyncio.sleep(0.15)
            else:
                await actuators.set_rgb(r, g, b)

        elif action_type == "led_off" and actuators:
            await actuators.set_rgb(0, 0, 0)

        elif action_type == "tone" and actuators:
            await actuators.play_tone(880, 300)

        # Build descriptive message
        det_label = detection.get("label", "unknown")
        det_conf = detection.get("confidence", 0)
        action_msg = action_params.get("text", "")
        msg = f"Rule '{rule_name}' triggered by {det_label} ({det_conf:.0%}). Action: {action_type}"
        if action_msg:
            msg += f' → "{action_msg}"'

        await db.log(
            "action_executed",
            {
                "rule": rule_name,
                "action": action_type,
                "params": action_params,
                "detection_label": det_label,
                "detection_confidence": det_conf,
                "message": msg,
            },
        )

    return handle_action


async def bt_reconnect_loop(settings: Settings) -> None:
    """Keep trying to connect the paired BT speaker when it drops."""
    mac = settings.bt_speaker_mac.strip()
    if not mac:
        return
    interval = max(settings.bt_reconnect_interval, 15.0)
    logger.info("BT speaker reconnect loop started (every %.0fs)", interval)
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                await asyncio.to_thread(ensure_bt_speaker_connected, mac)
            except Exception:
                logger.debug("BT reconnect attempt failed", exc_info=True)
    except asyncio.CancelledError:
        logger.info("BT speaker reconnect loop stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    settings = get_settings()
    setup_logging(settings.log_level)

    bus = EventBus()
    db = EventDB(settings.db_path)
    store = RulesStore(settings.db_path)
    engine = RulesEngine(store, bus, db)
    loop = RulesLoop(engine, bus, settings.rules_tick_ms)

    # Auto-detect camera: use YOLO if device exists, else mock
    if os.path.exists(settings.camera_device) and os.path.exists(settings.camera_device):  # noqa: ASYNC240
        camera: PerceptionSource = YOLOCamera(
            device=settings.camera_device,
            model_path=settings.model_path,
            confidence=settings.yolo_confidence,
            inference_interval=settings.yolo_inference_interval,
        )
        logger.info(
            "Using YOLO camera on %s (conf=%.2f, interval=%.2fs)",
            settings.camera_device,
            settings.yolo_confidence,
            settings.yolo_inference_interval,
        )
    else:
        camera = MockCamera()
        logger.info("Camera %s not found — using mock", settings.camera_device)

    # Choose LLM: stub (instant, deterministic) or real (llama.cpp server)
    if settings.llm_server_url:
        llm: StubLLM | LlamaLLM = LlamaLLM(
            base_url=settings.llm_server_url,
            timeout=settings.llm_timeout,
        )
        logger.info("Using real LLM at %s", settings.llm_server_url)
    else:
        llm = StubLLM()
        logger.info("Using stub LLM (no server configured)")

    await db.open()
    await store.open(connection=db.connection, on_commit=db.note_external_commit)
    await engine.start()

    app.state.bus = bus
    app.state.db = db
    app.state.store = store
    app.state.engine = engine
    app.state.llm = llm
    app.state.camera = camera
    app.state.settings = settings

    llm_lock = asyncio.Lock()
    app.state.llm_lock = llm_lock

    # Start mic for sound detection
    mic: YAMNetMic | None = None
    try:
        mic = YAMNetMic()
        app.state.mic = mic
        logger.info("Mic initialized for sound detection")
    except Exception:
        logger.warning("Could not initialize mic")

    # MCU: connect via arduino-router, falls back to internal mock data
    from aware.app.mcu.serial_mcu import SerialMCU

    sensor_bus = SerialMCU(
        settings.mcu_serial_port,
        settings.mcu_baud_rate,
        socket_path="/var/run/arduino-router.sock",
    )
    await sensor_bus.connect()
    logger.info(
        "MCU bus: %s",
        "real (arduino-router)" if sensor_bus._connected else "mock fallback",
    )

    # Subscribe handlers (must be after all state is initialized)
    bus.subscribe("action", action_handler_factory(db, bus, sensor_bus))

    sensor_cache = SensorCache()
    app.state.sensor_cache = sensor_cache
    app.state.sensor_bus = sensor_bus

    summarizer_task: asyncio.Task[None] | None = None
    if settings.memory_summary_enabled:
        summarizer = MemorySummarizer(
            db,
            llm,
            interval_seconds=float(settings.memory_summary_interval),
            llm_lock=llm_lock,
            llm_timeout=min(settings.llm_timeout, 120.0),
            use_llm=settings.memory_summary_use_llm,
        )
        summarizer_task = asyncio.create_task(summarizer.run())

    loop_task = asyncio.create_task(loop.start())
    camera_task = asyncio.create_task(
        perception_loop(bus, camera, db, mic, sensor_cache),
    )
    sensor_task = asyncio.create_task(
        sensor_loop(sensor_bus, bus, db, settings, sensor_cache),
    )
    bt_task = asyncio.create_task(bt_reconnect_loop(settings))
    await warmup_tts()
    logger.info("AWARE started on %s:%d", settings.host, settings.port)

    yield

    if summarizer_task is not None:
        summarizer_task.cancel()
    loop.stop()
    camera_task.cancel()
    sensor_task.cancel()
    bt_task.cancel()
    loop_task.cancel()
    await engine.stop()
    await store.close()
    await db.close()


app = FastAPI(title="AWARE", version="0.1.0", lifespan=lifespan)

# Serve dashboard as static files
_dashboard_dir = Path(__file__).parent.parent.parent / "dashboard"
if _dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(_dashboard_dir), html=True), name="dashboard")


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "dashboard": "/dashboard/index.html"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/sensors")
async def get_sensors() -> dict[str, object]:
    """Return live sensor readings from the in-memory cache."""
    cache: SensorCache = app.state.sensor_cache
    settings: Settings = app.state.settings
    bus = app.state.sensor_bus
    source = "mock" if getattr(bus, "using_mock", False) else "live"
    return {
        "timestamp": time.time(),
        "readings": dict(cache.readings),
        "source": source,
        "interval_s": settings.sensor_read_interval,
    }


@app.get("/api/sensors/history")
async def get_sensor_history(
    sensor: str,
    window: float = 300,
) -> list[dict[str, float]]:
    """Return rolling in-memory sensor history for live dashboard charts."""
    cache: SensorCache = app.state.sensor_cache
    return cache.get_history(sensor, window_seconds=window)


@app.get("/api/snapshot")
async def get_snapshot() -> dict[str, object]:
    """Get the latest perception snapshot from the camera."""
    camera: PerceptionSource = app.state.camera
    snap = await camera.snapshot()
    return {
        "source": snap.source,
        "timestamp": snap.timestamp,
        "detections": [
            {"label": d.label, "confidence": d.confidence, "bbox": d.bbox} for d in snap.detections
        ],
        "sounds": [{"label": s.label, "confidence": s.confidence} for s in snap.sounds],
    }


@app.get("/api/video")
async def video_stream() -> StreamingResponse:
    """MJPEG stream with YOLO bounding boxes overlaid."""
    camera = app.state.camera
    settings: Settings = app.state.settings
    frame_interval = 1.0 / settings.video_stream_fps

    async def generate() -> AsyncGenerator[bytes, None]:
        while True:
            frame_bytes = None
            if isinstance(camera, YOLOCamera):
                frame_bytes = camera.get_frame_jpeg()
            if frame_bytes is None:
                # Fallback: 1x1 black JPEG
                frame_bytes = (
                    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
                    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
                    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
                    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0"
                    b"\x00\x0b\x08\x00\x01\x00\x01\x01\x11\x02\xff\xc4\x00\x1f\x00\x00\x01\x05"
                    b"\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04"
                    b"\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x7f\x80"
                    b"\xff\xd9"
                )
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")
            await asyncio.sleep(frame_interval)

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/detections")
async def get_detections(limit: int = 50) -> list[dict[str, object]]:
    """Get recent detection history with timestamps."""
    camera = app.state.camera
    results = []
    if isinstance(camera, YOLOCamera):
        results.extend(camera.get_detection_log(limit))
    mic = getattr(app.state, "mic", None)
    if isinstance(mic, YAMNetMic):
        results.extend(mic.get_sound_log(limit))
    # Sort by timestamp, most recent first
    results.sort(key=lambda x: float(str(x.get("timestamp", 0))), reverse=True)
    return results[:limit]


@app.get("/api/objects")
async def get_objects(limit: int = 50) -> list[dict[str, object]]:
    """Get recent object detection history (YOLO only)."""
    camera = app.state.camera
    if isinstance(camera, YOLOCamera):
        return camera.get_detection_log(limit)
    return []


@app.get("/api/sounds")
async def get_sounds(limit: int = 50) -> list[dict[str, object]]:
    """Get recent sound detection history (YAMNet only)."""
    mic = getattr(app.state, "mic", None)
    if isinstance(mic, YAMNetMic):
        return mic.get_sound_log(limit)
    return []


@app.get("/api/venue/stats")
async def venue_stats(window: int = 3600) -> dict[str, object]:
    """Witness counters and AI-generated log entries for the venue panel."""
    db: EventDB = app.state.db
    camera: PerceptionSource = app.state.camera
    settings: Settings = app.state.settings

    now = time.time()
    start = now - window
    snap = await camera.snapshot()
    in_frame: dict[str, int] = {}
    for det in snap.detections:
        if det.label != "person":
            continue
        in_frame[det.label] = in_frame.get(det.label, 0) + 1

    detections = await db.count_labels_in_range(start, now, "detection_enter")
    sounds = await db.count_labels_in_range(start, now, "sound")
    detections = {k: v for k, v in detections.items() if k == "person"}
    sounds = {k: v for k, v in sounds.items() if k in WITNESS_SOUND_LABELS}
    people_passed = detections.get("person", 0)
    sound_total = sum(sounds.values())

    window_events = await db.query_range(start, now)
    summaries = await db.get_summaries(since=start, until=now)
    witness_recaps = summaries_for_witness_display(
        summaries,
        limit=settings.memory_summary_display_limit,
    )
    witness_activity = witness_events_for_display(build_witness_log(window_events))

    return {
        "timestamp": now,
        "window_seconds": window,
        "window_start": start,
        "window_end": now,
        "in_frame": in_frame,
        "people_in_frame": in_frame.get("person", 0),
        "people_passed": people_passed,
        "detections": detections,
        "sounds": sounds,
        "sound_total": sound_total,
        "witness_recaps": witness_recaps,
        "witness_activity": witness_activity,
        "witness_logs": witness_activity,
        "camera_source": snap.source,
    }


@app.get("/events")
async def events(topic: str | None = None, limit: int = 50) -> list[dict[str, object]]:
    db: EventDB = app.state.db
    return await db.query(topic=topic, limit=limit)


@app.get("/api/activity")
async def activity(limit: int = 30) -> list[dict[str, object]]:
    """Recent narratable events for the dashboard activity feed."""
    db: EventDB = app.state.db
    return await db.query_activity(limit=limit)


@app.get("/rules")
async def list_rules() -> list[dict[str, object]]:
    store: RulesStore = app.state.store
    return await store.get_active()


@app.delete("/api/rules/{rule_id:int}")
async def delete_rule_by_id(rule_id: int) -> dict[str, str]:
    """Deactivate a rule by database id (reliable for all rule names)."""
    store: RulesStore = app.state.store
    bus: EventBus = app.state.bus
    name = await store.deactivate_by_id(rule_id)
    if name is None:
        raise HTTPException(status_code=404, detail="rule not found")
    await bus.publish("rules", {"event": "deleted", "name": name, "id": rule_id})
    logger.info("Rule deactivated: %s (id=%d)", name, rule_id)
    return {"status": "deleted", "name": name, "id": str(rule_id)}


@app.delete("/rules/{name}")
async def delete_rule(name: str) -> dict[str, str]:
    """Deactivate a rule by name."""
    from urllib.parse import unquote

    store: RulesStore = app.state.store
    bus: EventBus = app.state.bus
    decoded = unquote(name)
    if not decoded:
        raise HTTPException(status_code=400, detail="rule name required")
    if not await store.deactivate(decoded):
        raise HTTPException(status_code=404, detail="rule not found")
    await bus.publish("rules", {"event": "deleted", "name": decoded})
    logger.info("Rule deactivated: %s", decoded)
    return {"status": "deleted", "name": decoded}


class CommandRequest(BaseModel):
    command: str


class CommandResponse(BaseModel):
    rule_name: str
    when: str
    then: str
    priority: str
    message: str
    llm_output: str = ""
    triggers: list[dict[str, object]] = []
    actions: list[dict[str, object]] = []


@app.post("/api/command", response_model=CommandResponse)
async def create_rule_endpoint(req: CommandRequest) -> CommandResponse:
    """Accept NL command, process through LLM -> parser -> store."""
    llm: StubLLM = app.state.llm
    store: RulesStore = app.state.store
    bus: EventBus = app.state.bus
    db: EventDB = app.state.db

    # 1. LLM parses the NL command into RuleSpec
    spec: RuleSpec = await llm.create_rule(req.command)

    # 2. NL parser compiles triggers + actions (pass raw command for transition detection)
    parsed = parse_rule(spec.name, spec.when, spec.then, spec.priority, raw=req.command)

    # 3. Store the rule
    triggers_dicts: list[dict[str, object]] = [
        {
            "type": t.type,
            "value": t.value,
            "time_range": list(t.time_range) if t.time_range else None,
            "transition": t.transition,
            "sensor_op": t.sensor_op,
            "sensor_threshold": t.sensor_threshold,
        }
        for t in parsed.triggers
    ]
    actions_dicts: list[dict[str, object]] = [
        {"type": a.type, "params": a.params} for a in parsed.actions
    ]
    final_name = await store.add(
        name=parsed.name,
        when_text=spec.when,
        then_text=spec.then,
        priority=parsed.priority,
        triggers=triggers_dicts,
        actions=actions_dicts,
        llm_raw=spec.raw,
    )

    # 4. Log to memory
    await db.log(
        "rule_created",
        {
            "name": final_name,
            "when": spec.when,
            "then": spec.then,
            "priority": parsed.priority,
            "llm_output": spec.raw,
            "triggers": triggers_dicts,
            "actions": actions_dicts,
        },
    )

    # 5. Broadcast update
    await bus.publish("rules", {"event": "created", "name": final_name})

    logger.info("Rule created: %s", final_name)
    return CommandResponse(
        rule_name=final_name,
        when=spec.when,
        then=spec.then,
        priority=parsed.priority,
        message="Rule created and activated.",
        llm_output=spec.raw,
        triggers=triggers_dicts,
        actions=actions_dicts,
    )


class AskRequest(BaseModel):
    question: str
    since: float | None = None
    window: int | None = None


class AskResponse(BaseModel):
    answer: str
    window_start: float
    window_end: float
    summaries_used: int
    events_scanned: int
    context_preview: str = ""
    latency_ms: float
    used_llm: bool


@app.post("/api/ask", response_model=AskResponse)
async def ask_endpoint(req: AskRequest) -> AskResponse:
    """Answer a natural-language question about recent activity."""
    db: EventDB = app.state.db
    llm: LLMClient = app.state.llm
    settings: Settings = app.state.settings
    llm_lock: asyncio.Lock = app.state.llm_lock
    result = await answer_question(
        req.question,
        db,
        llm,
        settings,
        llm_lock,
        since=req.since,
        window=req.window,
    )
    return AskResponse(
        answer=result.answer,
        window_start=result.window_start,
        window_end=result.window_end,
        summaries_used=result.summaries_used,
        events_scanned=result.events_scanned,
        context_preview=result.context_preview,
        latency_ms=result.latency_ms,
        used_llm=result.used_llm,
    )


@app.get("/api/summaries")
async def get_summaries(
    limit: int = 20,
    since: float | None = None,
) -> list[dict[str, object]]:
    """Return stored period summaries."""
    db: EventDB = app.state.db
    since_ts = since if since is not None else 0.0
    rows = await db.get_summaries(since=since_ts, limit=limit)
    return [
        {
            "id": row["id"],
            "period_start": row["period_start"],
            "period_end": row["period_end"],
            "narrative": row["narrative"],
            "event_count": row["event_count"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@app.get("/api/timeseries")
async def get_timeseries(
    topic: str = "sensor",
    window: int = 3600,
    bucket: int = 60,
) -> list[dict[str, object]]:
    """Aggregate events into time buckets for charting."""
    db: EventDB = app.state.db
    return await db.timeseries(topic=topic, window_seconds=window, bucket_seconds=bucket)


@app.get("/api/timeseries/all")
async def get_all_timeseries(
    window: int = 3600,
    bucket: int = 60,
) -> dict[str, list[dict[str, object]]]:
    """Return timeseries for all data streams, grouped by label.

    Returns dict with keys: detection, sound, sensor (split by name), action_executed.
    """
    db: EventDB = app.state.db
    topics = ["detection_enter", "sound", "action_executed"]
    result: dict[str, list[dict[str, object]]] = {}

    for t in topics:
        ts = await db.event_count_timeseries(
            topic=t,
            window_seconds=window,
            bucket_seconds=bucket,
        )
        if ts:
            result[t] = [{"label": t, "data": ts}]

    # Get sensor readings split by sensor name
    sensor_topics = await db.sensor_topics()
    for st in sensor_topics:
        ts = await db.timeseries(topic=st, window_seconds=window, bucket_seconds=bucket)
        if ts:
            sensor_name = st.replace("sensor:", "")
            if "sensor" not in result:
                result["sensor"] = []
            result["sensor"].append({"label": sensor_name, "data": ts})

    return result


@app.get("/api/llm/stats")
async def llm_stats() -> dict[str, object]:
    """Return LLM performance statistics."""
    llm: StubLLM = app.state.llm
    return llm.stats.to_dict()


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    reload_enabled = os.environ.get("AWARE_UVICORN_RELOAD", "").lower() in ("1", "true", "yes")
    uvicorn.run("aware.app.main:app", host=s.host, port=s.port, reload=reload_enabled)
