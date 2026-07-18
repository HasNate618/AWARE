from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    when_text TEXT NOT NULL,
    then_text TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normal',
    triggers_json TEXT NOT NULL DEFAULT '[]',
    actions_json TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
"""

_INSERT = """
INSERT INTO rules
    (name, when_text, then_text, priority, triggers_json, actions_json, active, created_at)
VALUES (?, ?, ?, ?, ?, ?, 1, ?);
"""

_SELECT_ACTIVE = """
SELECT id, name, when_text, then_text, priority, triggers_json, actions_json, active, created_at
FROM rules WHERE active = 1 ORDER BY id;
"""

_DELETE = "UPDATE rules SET active = 0 WHERE name = ?;"


class RulesStore:
    """SQLite-backed persistent rules storage."""

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

    async def add(
        self,
        name: str,
        when_text: str,
        then_text: str,
        priority: str,
        triggers: list[dict[str, object]],
        actions: list[dict[str, object]],
    ) -> None:
        if not self._db:
            raise RuntimeError("Store not opened")
        await self._db.execute(
            _INSERT,
            (
                name,
                when_text,
                then_text,
                priority,
                json.dumps(triggers),
                json.dumps(actions),
                time.time(),
            ),
        )
        await self._db.commit()

    async def get_active(self) -> list[dict[str, object]]:
        if not self._db:
            raise RuntimeError("Store not opened")
        cursor = await self._db.execute(_SELECT_ACTIVE)
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "name": row[1],
                "when_text": row[2],
                "then_text": row[3],
                "priority": row[4],
                "triggers": json.loads(row[5]),
                "actions": json.loads(row[6]),
                "active": bool(row[7]),
                "created_at": row[8],
            }
            for row in rows
        ]

    async def deactivate(self, name: str) -> None:
        if not self._db:
            raise RuntimeError("Store not opened")
        await self._db.execute(_DELETE, (name,))
        await self._db.commit()
