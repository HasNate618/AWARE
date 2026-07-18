from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    topic TEXT NOT NULL,
    data TEXT NOT NULL
);
"""

_INSERT = "INSERT INTO events (timestamp, topic, data) VALUES (?, ?, ?);"
_SELECT = "SELECT id, timestamp, topic, data FROM events"
_SELECT_TOPIC = f"{_SELECT} WHERE topic = ? ORDER BY id DESC LIMIT ?;"
_SELECT_ALL = f"{_SELECT} ORDER BY id DESC LIMIT ?;"


class EventDB:
    """SQLite-backed event log."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(_CREATE_TABLE)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def log(self, topic: str, data: dict[str, object]) -> None:
        if not self._db:
            raise RuntimeError("Database not opened")
        await self._db.execute(_INSERT, (time.time(), topic, json.dumps(data)))
        await self._db.commit()

    async def query(
        self, topic: str | None = None, limit: int = 50
    ) -> list[dict[str, object]]:
        if not self._db:
            raise RuntimeError("Database not opened")
        if topic:
            cursor = await self._db.execute(_SELECT_TOPIC, (topic, limit))
        else:
            cursor = await self._db.execute(_SELECT_ALL, (limit,))
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "timestamp": row[1],
                "topic": row[2],
                "data": json.loads(row[3]),
            }
            for row in rows
        ]
