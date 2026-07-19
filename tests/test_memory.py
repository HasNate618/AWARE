from __future__ import annotations

import time

from aware.app.memory.db import EventDB


async def test_log_and_query(db: EventDB) -> None:
    await db.log("test", {"value": 1})
    await db.log("test", {"value": 2})
    await db.log("other", {"value": 3})
    rows = await db.query()
    assert len(rows) == 3
    rows_test = await db.query(topic="test", limit=10)
    assert len(rows_test) == 2
    assert rows_test[0]["data"]["value"] == 2


async def test_limit(db: EventDB) -> None:
    for i in range(10):
        await db.log("n", {"i": i})
    rows = await db.query(limit=3)
    assert len(rows) == 3


async def test_query_range(db: EventDB) -> None:
    await db.log("detection_enter", {"label": "person"})
    await db.log("sound", {"label": "doorbell"})
    end = time.time() + 3600
    rows = await db.query_range(0, end)
    assert len(rows) == 2


async def test_query_activity_excludes_sensors(db: EventDB) -> None:
    await db.log("sensor:temperature_c", {"label": "temperature_c", "value": 21.0})
    await db.log("sensor:distance_cm", {"label": "distance_cm", "value": 100.0})
    await db.log("detection_enter", {"label": "person", "confidence": 0.9})
    await db.log("action_executed", {"message": "Rule fired"})
    rows = await db.query_activity(limit=10)
    topics = {r["topic"] for r in rows}
    assert "sensor:temperature_c" not in topics
    assert "sensor:distance_cm" not in topics
    assert "detection_enter" in topics
    assert "action_executed" in topics


async def test_log_requires_flush_before_new_connection(db: EventDB) -> None:
    await db.log("test", {"value": 1})
    await db.flush()
    rows = await db.query(topic="test", limit=10)
    assert len(rows) == 1


async def test_summaries(db: EventDB) -> None:
    await db.store_summary(
        period_start=100.0,
        period_end=200.0,
        digest='{"period_start": 100}',
        narrative="person entered once",
        event_count=3,
    )
    assert await db.last_summary_end() == 200.0
    rows = await db.get_summaries(since=0)
    assert len(rows) == 1
    assert rows[0]["narrative"] == "person entered once"
