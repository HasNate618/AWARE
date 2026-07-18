from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aware.app.config import get_settings, setup_logging
from aware.app.core.event_bus import EventBus
from aware.app.core.loop import RulesLoop
from aware.app.memory.db import EventDB
from aware.app.rules.engine import RulesEngine
from aware.app.rules.store import RulesStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    settings = get_settings()
    setup_logging(settings.log_level)

    bus = EventBus()
    db = EventDB(settings.db_path)
    store = RulesStore(settings.db_path)
    engine = RulesEngine(store, bus, db)
    loop = RulesLoop(engine, bus, settings.rules_tick_ms)

    await db.open()
    await store.open()
    await engine.start()

    app.state.bus = bus
    app.state.db = db
    app.state.store = store
    app.state.engine = engine

    task = __import__("asyncio").create_task(loop.start())
    logger.info("AWARE started on %s:%d", settings.host, settings.port)

    yield

    loop.stop()
    await engine.stop()
    task.cancel()
    await store.close()
    await db.close()


app = FastAPI(title="AWARE", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/events")
async def events(topic: str | None = None, limit: int = 50) -> list[dict[str, object]]:
    db: EventDB = app.state.db
    return await db.query(topic=topic, limit=limit)


@app.get("/rules")
async def rules() -> list[dict[str, object]]:
    store: RulesStore = app.state.store
    return await store.get_active()


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("aware.app.main:app", host=s.host, port=s.port, reload=True)
