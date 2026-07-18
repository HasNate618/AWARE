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
