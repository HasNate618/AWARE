from __future__ import annotations

import pytest

from aware.app.core.event_bus import EventBus
from aware.app.memory.db import EventDB
from aware.app.rules.store import RulesStore


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
async def db() -> EventDB:
    db = EventDB(":memory:")
    await db.open()
    yield db
    await db.close()


@pytest.fixture
async def store() -> RulesStore:
    store = RulesStore(":memory:")
    await store.open()
    yield store
    await store.close()
