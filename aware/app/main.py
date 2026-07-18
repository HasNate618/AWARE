from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from aware.app.config import get_settings, setup_logging
from aware.app.core.event_bus import EventBus
from aware.app.core.loop import RulesLoop
from aware.app.llm.interface import RuleSpec
from aware.app.llm.llama import LlamaLLM
from aware.app.llm.stub import StubLLM
from aware.app.memory.db import EventDB
from aware.app.parser.nl_parser import parse_rule
from aware.app.perception.interface import PerceptionSource
from aware.app.perception.mock_camera import MockCamera
from aware.app.perception.yolo import YOLOCamera
from aware.app.rules.engine import RulesEngine
from aware.app.rules.store import RulesStore

logger = logging.getLogger(__name__)

MOCK_SNAPSHOT_INTERVAL = 0.5  # seconds


async def perception_loop(bus: EventBus, camera: PerceptionSource) -> None:
    """Run camera in background, publishing snapshots to event bus."""
    await camera.start()
    # If YOLO camera, run its inference loop in parallel
    if isinstance(camera, YOLOCamera):
        asyncio.create_task(camera.run_inference_loop())
    try:
        while True:
            snapshot = await camera.snapshot()
            await bus.publish("perception", {"snapshot": snapshot})
            await asyncio.sleep(MOCK_SNAPSHOT_INTERVAL)
    except asyncio.CancelledError:
        await camera.stop()


def action_handler_factory(db: EventDB) -> Any:
    """Create a handler that logs actions to the database."""

    async def handle_action(event: dict[str, Any]) -> None:
        rule_name = event.get("rule", "unknown")
        action_type = event.get("action", "log")
        params = event.get("params", {})
        logger.info(
            "[action] rule=%s action=%s params=%s",
            rule_name,
            action_type,
            params,
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
    camera_device = Path(settings.camera_device)
    if camera_device.exists():
        camera: PerceptionSource = YOLOCamera(
            device=settings.camera_device,
            confidence=0.5,
            inference_interval=0.5,
        )
        logger.info("Using YOLO camera on %s", settings.camera_device)
    else:
        camera = MockCamera()
        logger.info("Camera %s not found — using mock", settings.camera_device)

    # Choose LLM: stub (instant, deterministic) or real (llama.cpp server)
    if settings.llm_server_url:
        llm: StubLLM | LlamaLLM = LlamaLLM(base_url=settings.llm_server_url)
        logger.info("Using real LLM at %s", settings.llm_server_url)
    else:
        llm = StubLLM()
        logger.info("Using stub LLM (no server configured)")

    await db.open()
    await store.open()
    await engine.start()

    bus.subscribe("action", action_handler_factory(db))

    app.state.bus = bus
    app.state.db = db
    app.state.store = store
    app.state.engine = engine
    app.state.llm = llm
    app.state.camera = camera

    loop_task = asyncio.create_task(loop.start())
    camera_task = asyncio.create_task(perception_loop(bus, camera))
    logger.info("AWARE started on %s:%d", settings.host, settings.port)

    yield

    loop.stop()
    camera_task.cancel()
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
            {"label": d.label, "confidence": d.confidence, "bbox": d.bbox}
            for d in snap.detections
        ],
        "sounds": [
            {"label": s.label, "confidence": s.confidence}
            for s in snap.sounds
        ],
    }


@app.get("/events")
async def events(topic: str | None = None, limit: int = 50) -> list[dict[str, object]]:
    db: EventDB = app.state.db
    return await db.query(topic=topic, limit=limit)


@app.get("/rules")
async def list_rules() -> list[dict[str, object]]:
    store: RulesStore = app.state.store
    return await store.get_active()


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
        {"type": a.type, "params": a.params}
        for a in parsed.actions
    ]
    await store.add(
        name=parsed.name,
        when_text=spec.when,
        then_text=spec.then,
        priority=parsed.priority,
        triggers=triggers_dicts,
        actions=actions_dicts,
    )

    # 4. Log to memory
    await db.log("rule_created", {
        "name": parsed.name,
        "when": spec.when,
        "then": spec.then,
        "priority": parsed.priority,
    })

    # 5. Broadcast update
    await bus.publish("rules", {"event": "created", "name": parsed.name})

    logger.info("Rule created: %s", parsed.name)
    return CommandResponse(
        rule_name=parsed.name,
        when=spec.when,
        then=spec.then,
        priority=parsed.priority,
        message="Rule created and activated.",
    )


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("aware.app.main:app", host=s.host, port=s.port, reload=True)
