from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from aware.app.action.speaker import speak as speak_text
from aware.app.config import get_settings, setup_logging
from aware.app.core.event_bus import EventBus
from aware.app.core.loop import RulesLoop
from aware.app.llm.interface import RuleSpec
from aware.app.llm.llama import LlamaLLM
from aware.app.llm.stub import StubLLM
from aware.app.memory.db import EventDB
from aware.app.parser.nl_parser import parse_rule
from aware.app.perception.interface import PerceptionSnapshot, PerceptionSource
from aware.app.perception.mock_camera import MockCamera
from aware.app.perception.yamnet import YAMNetMic
from aware.app.perception.yolo import YOLOCamera
from aware.app.rules.engine import RulesEngine
from aware.app.rules.store import RulesStore

logger = logging.getLogger(__name__)

MOCK_SNAPSHOT_INTERVAL = 0.5  # seconds


def perception_logger_factory(db: EventDB) -> Any:
    """Create a handler that logs snapshot summaries to the DB."""

    async def handle_perception(event: dict[str, Any]) -> None:
        snapshot: PerceptionSnapshot | None = event.get("snapshot")
        if not snapshot:
            return
        if snapshot.detections or snapshot.sounds:
            await db.log("perception", {
                "detections": [(d.label, d.confidence) for d in snapshot.detections],
                "sounds": [(s.label, s.confidence) for s in snapshot.sounds],
                "source": snapshot.source,
            })

    return handle_perception


async def perception_loop(
    bus: EventBus, camera: PerceptionSource, mic: YAMNetMic | None = None
) -> None:
    """Run camera + mic in background, publishing snapshots to event bus."""
    await camera.start()
    # If YOLO camera, run its inference loop in parallel
    if isinstance(camera, YOLOCamera):
        asyncio.create_task(camera.run_inference_loop())
    # Start mic detection loop
    if mic is not None:
        await mic.start()
        asyncio.create_task(mic.run_detection_loop())
    try:
        while True:
            # Merge camera + mic snapshots
            cam_snap = await camera.snapshot()
            sounds_snap = await mic.snapshot() if mic else None
            merged = PerceptionSnapshot(
                detections=cam_snap.detections,
                sounds=sounds_snap.sounds if sounds_snap else [],
                source=cam_snap.source,
                timestamp=cam_snap.timestamp,
            )
            await bus.publish("perception", {"snapshot": merged})
            await asyncio.sleep(MOCK_SNAPSHOT_INTERVAL)
    except asyncio.CancelledError:
        await camera.stop()
        if mic:
            await mic.stop()


SENSOR_READ_INTERVAL = 2.0  # seconds


async def sensor_loop(bus: EventBus, db: EventDB) -> None:
    """Read mock sensors periodically and log to DB for timeseries."""
    from aware.app.mcu.mock import MockSensorBus

    sensors = MockSensorBus()
    try:
        while True:
            readings = await sensors.read_all()
            for r in readings:
                await db.log(f"sensor:{r.sensor}", {
                    "label": r.sensor,
                    "value": r.value,
                    "unit": r.unit,
                })
            await asyncio.sleep(SENSOR_READ_INTERVAL)
    except asyncio.CancelledError:
        pass


def action_handler_factory(db: EventDB, bus: EventBus) -> Any:
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
            confidence=0.75,
            inference_interval=0.5,
        )
        logger.info("Using YOLO camera on %s", settings.camera_device)
    else:
        camera = MockCamera()
        logger.info("Camera %s not found — using mock", settings.camera_device)

    # Choose LLM: stub (instant, deterministic) or real (llama.cpp server)
    if settings.llm_server_url:
        llm: StubLLM | LlamaLLM = LlamaLLM(
            base_url=settings.llm_server_url, timeout=settings.llm_timeout,
        )
        logger.info("Using real LLM at %s", settings.llm_server_url)
    else:
        llm = StubLLM()
        logger.info("Using stub LLM (no server configured)")

    await db.open()
    await store.open()
    await engine.start()

    bus.subscribe("action", action_handler_factory(db, bus))
    bus.subscribe("perception", perception_logger_factory(db))

    app.state.bus = bus
    app.state.db = db
    app.state.store = store
    app.state.engine = engine
    app.state.llm = llm
    app.state.camera = camera

    # Start mic for sound detection
    mic: YAMNetMic | None = None
    try:
        mic = YAMNetMic()
        app.state.mic = mic
        logger.info("Mic initialized for sound detection")
    except Exception:
        logger.warning("Could not initialize mic")

    loop_task = asyncio.create_task(loop.start())
    camera_task = asyncio.create_task(perception_loop(bus, camera, mic))
    sensor_task = asyncio.create_task(sensor_loop(bus, db))
    logger.info("AWARE started on %s:%d", settings.host, settings.port)

    yield

    loop.stop()
    camera_task.cancel()
    sensor_task.cancel()
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
            await asyncio.sleep(0.1)  # ~10 FPS

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


@app.get("/events")
async def events(topic: str | None = None, limit: int = 50) -> list[dict[str, object]]:
    db: EventDB = app.state.db
    return await db.query(topic=topic, limit=limit)


@app.get("/rules")
async def list_rules() -> list[dict[str, object]]:
    store: RulesStore = app.state.store
    return await store.get_active()


@app.delete("/rules/{name}")
async def delete_rule(name: str) -> dict[str, str]:
    """Deactivate a rule by name."""
    store: RulesStore = app.state.store
    await store.deactivate(name)
    logger.info("Rule deactivated: %s", name)
    return {"status": "deleted", "name": name}


class CommandRequest(BaseModel):
    command: str


class CommandResponse(BaseModel):
    rule_name: str
    when: str
    then: str
    priority: str
    message: str


@app.post("/api/command", response_model=CommandResponse)
async def create_rule_endpoint(req: CommandRequest) -> CommandResponse:
    """Accept NL command, process through LLM -> parser -> store."""
    llm: StubLLM = app.state.llm
    store: RulesStore = app.state.store
    bus: EventBus = app.state.bus
    db: EventDB = app.state.db

    # 1. LLM parses the NL command into RuleSpec
    spec: RuleSpec = await llm.create_rule(req.command)

    # 2. NL parser compiles triggers + actions
    parsed = parse_rule(spec.name, spec.when, spec.then, spec.priority)

    # 3. Store the rule
    triggers_dicts: list[dict[str, object]] = [
        {
            "type": t.type,
            "value": t.value,
            "time_range": list(t.time_range) if t.time_range else None,
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
    )

    # 4. Log to memory
    await db.log(
        "rule_created",
        {
            "name": final_name,
            "when": spec.when,
            "then": spec.then,
            "priority": parsed.priority,
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
    )


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
    topics = ["detection", "sound", "action_executed"]
    result: dict[str, list[dict[str, object]]] = {}

    for t in topics:
        ts = await db.timeseries(topic=t, window_seconds=window, bucket_seconds=bucket)
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


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("aware.app.main:app", host=s.host, port=s.port, reload=True)
