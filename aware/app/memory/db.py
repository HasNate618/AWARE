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

_CREATE_INDEX = "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (timestamp);"

_INSERT = "INSERT INTO events (timestamp, topic, data) VALUES (?, ?, ?);"
_SELECT = "SELECT id, timestamp, topic, data FROM events"
_SELECT_TOPIC = f"{_SELECT} WHERE topic = ? ORDER BY id DESC LIMIT ?;"
_SELECT_ALL = f"{_SELECT} ORDER BY id DESC LIMIT ?;"

# Timeseries aggregation query
# Buckets events by time window, returns avg/min/max/count per bucket
_TIMESERIES = """
SELECT
    CAST((timestamp - :start) / :bucket_size AS INTEGER) AS bucket,
    MIN(timestamp) AS t_start,
    AVG(CAST(json_extract(data, '$.value') AS REAL)) AS avg_val,
    MIN(CAST(json_extract(data, '$.value') AS REAL)) AS min_val,
    MAX(CAST(json_extract(data, '$.value') AS REAL)) AS max_val,
    COUNT(*) AS count
FROM events
WHERE topic = :topic
  AND timestamp >= :start
  AND timestamp < :end
GROUP BY bucket
ORDER BY bucket;
"""


class EventDB:
    """SQLite-backed event log."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute(_CREATE_TABLE)
        await self._db.execute(_CREATE_INDEX)
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

    async def timeseries(
        self,
        topic: str,
        window_seconds: float = 3600,
        bucket_seconds: float = 60,
    ) -> list[dict[str, object]]:
        """Aggregate events into time buckets for charting."""
        if not self._db:
            raise RuntimeError("Database not opened")
        now = time.time()
        start = now - window_seconds
        cursor = await self._db.execute(
            _TIMESERIES,
            {
                "topic": topic,
                "start": start,
                "end": now,
                "bucket_size": bucket_seconds,
            },
        )
        rows = await cursor.fetchall()
        return [
            {
                "bucket": row[0],
                "timestamp": row[1],
                "avg": round(row[2], 3) if row[2] is not None else 0,
                "min": round(row[3], 3) if row[3] is not None else 0,
                "max": round(row[4], 3) if row[4] is not None else 0,
                "count": row[5],
            }
            for row in rows
        ]

    async def sensor_topics(self) -> list[str]:
        """Return all unique sensor:* topics in the DB."""
        if not self._db:
            raise RuntimeError("Database not opened")
        cursor = await self._db.execute(
            "SELECT DISTINCT topic FROM events WHERE topic LIKE 'sensor:%'"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
