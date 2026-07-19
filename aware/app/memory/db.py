from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
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

_CREATE_SUMMARIES = """
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start REAL NOT NULL,
    period_end REAL NOT NULL,
    digest TEXT NOT NULL,
    narrative TEXT NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
"""

_CREATE_SUMMARIES_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_summaries_period_end ON summaries (period_end);"
)

_INSERT = "INSERT INTO events (timestamp, topic, data) VALUES (?, ?, ?);"
_SELECT = "SELECT id, timestamp, topic, data FROM events"
_SELECT_TOPIC = f"{_SELECT} WHERE topic = ? ORDER BY id DESC LIMIT ?;"
_SELECT_ALL = f"{_SELECT} ORDER BY id DESC LIMIT ?;"

ACTIVITY_TOPICS: tuple[str, ...] = (
    "detection_enter",
    "detection_exit",
    "sound",
    "action_executed",
    "rule_created",
    "summary_created",
    "memory_query",
)

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

_EVENT_COUNT_TIMESERIES = """
SELECT
    CAST((timestamp - :start) / :bucket_size AS INTEGER) AS bucket,
    MIN(timestamp) AS t_start,
    COUNT(*) AS count
FROM events
WHERE topic = :topic
  AND timestamp >= :start
  AND timestamp < :end
GROUP BY bucket
ORDER BY bucket;
"""


def _row_to_event(row: Sequence[object]) -> dict[str, object]:
    return {
        "id": row[0],
        "timestamp": row[1],
        "topic": row[2],
        "data": json.loads(str(row[3])),
    }


class EventDB:
    """SQLite-backed event log and period summaries."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        commit_interval: float = 1.0,
    ) -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None
        self._commit_interval = commit_interval
        self._last_commit = 0.0
        self._dirty = False

    async def open(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute(_CREATE_TABLE)
        await self._db.execute(_CREATE_INDEX)
        await self._db.execute(_CREATE_SUMMARIES)
        await self._db.execute(_CREATE_SUMMARIES_INDEX)
        await self._db.commit()

    @property
    def connection(self) -> aiosqlite.Connection:
        if not self._db:
            raise RuntimeError("Database not opened")
        return self._db

    async def close(self) -> None:
        if self._db:
            await self.flush()
            await self._db.close()
            self._db = None

    async def note_external_commit(self) -> None:
        """Reset batching state after another layer commits on the shared connection."""
        self._dirty = False
        self._last_commit = time.time()

    async def flush(self) -> None:
        if self._db and self._dirty:
            await self._db.commit()
            self._dirty = False
            self._last_commit = time.time()

    async def _maybe_commit(self) -> None:
        now = time.time()
        if self._dirty and now - self._last_commit >= self._commit_interval:
            await self.flush()

    async def log(self, topic: str, data: dict[str, object]) -> None:
        if not self._db:
            raise RuntimeError("Database not opened")
        await self._db.execute(_INSERT, (time.time(), topic, json.dumps(data)))
        self._dirty = True
        await self._maybe_commit()

    async def query(self, topic: str | None = None, limit: int = 50) -> list[dict[str, object]]:
        if not self._db:
            raise RuntimeError("Database not opened")
        if topic:
            cursor = await self._db.execute(_SELECT_TOPIC, (topic, limit))
        else:
            cursor = await self._db.execute(_SELECT_ALL, (limit,))
        rows = await cursor.fetchall()
        return [_row_to_event(row) for row in rows]

    async def query_activity(self, limit: int = 30) -> list[dict[str, object]]:
        """Return recent narratable events, excluding raw sensor telemetry."""
        if not self._db:
            raise RuntimeError("Database not opened")
        placeholders = ",".join("?" for _ in ACTIVITY_TOPICS)
        sql = f"{_SELECT} WHERE topic IN ({placeholders}) ORDER BY id DESC LIMIT ?;"
        cursor = await self._db.execute(sql, (*ACTIVITY_TOPICS, limit))
        rows = await cursor.fetchall()
        return [_row_to_event(row) for row in rows]

    async def query_range(
        self,
        start: float,
        end: float,
        topics: list[str] | None = None,
        limit: int = 2000,
    ) -> list[dict[str, object]]:
        if not self._db:
            raise RuntimeError("Database not opened")
        if topics:
            placeholders = ",".join("?" for _ in topics)
            sql = f"""
                SELECT id, timestamp, topic, data FROM events
                WHERE timestamp >= ? AND timestamp < ?
                  AND topic IN ({placeholders})
                ORDER BY timestamp ASC
                LIMIT ?
            """
            params: tuple[object, ...] = (start, end, *topics, limit)
        else:
            sql = """
                SELECT id, timestamp, topic, data FROM events
                WHERE timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
                LIMIT ?
            """
            params = (start, end, limit)
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_event(row) for row in rows]

    async def query_since(
        self,
        since: float,
        topics: list[str] | None = None,
        limit: int = 2000,
    ) -> list[dict[str, object]]:
        return await self.query_range(since, time.time(), topics=topics, limit=limit)

    async def count_range(
        self,
        start: float,
        end: float,
        topic: str | None = None,
    ) -> int:
        if not self._db:
            raise RuntimeError("Database not opened")
        if topic:
            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM events WHERE timestamp >= ? AND timestamp < ? AND topic = ?",
                (start, end, topic),
            )
        else:
            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM events WHERE timestamp >= ? AND timestamp < ?",
                (start, end),
            )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def count_labels_in_range(
        self,
        start: float,
        end: float,
        topic: str,
    ) -> dict[str, int]:
        """Count events by data.label for a topic in a time window."""
        if not self._db:
            raise RuntimeError("Database not opened")
        cursor = await self._db.execute(
            """
            SELECT data FROM events
            WHERE timestamp >= ? AND timestamp < ? AND topic = ?
            """,
            (start, end, topic),
        )
        rows = await cursor.fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            raw = row[0]
            if not isinstance(raw, str):
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            label = str(data.get("label", "unknown"))
            counts[label] = counts.get(label, 0) + 1
        return counts

    async def last_summary_end(self) -> float | None:
        if not self._db:
            raise RuntimeError("Database not opened")
        cursor = await self._db.execute("SELECT MAX(period_end) FROM summaries")
        row = await cursor.fetchone()
        if row and row[0] is not None:
            return float(row[0])
        return None

    async def last_summary_narrative(self) -> str | None:
        """Most recent stored recap for witness continuity."""
        if not self._db:
            raise RuntimeError("Database not opened")
        cursor = await self._db.execute(
            "SELECT narrative FROM summaries ORDER BY period_end DESC LIMIT 1",
        )
        row = await cursor.fetchone()
        if row and row[0]:
            return str(row[0]).strip()
        return None

    async def store_summary(
        self,
        period_start: float,
        period_end: float,
        digest: str,
        narrative: str,
        event_count: int,
    ) -> int:
        if not self._db:
            raise RuntimeError("Database not opened")
        cursor =         await self._db.execute(
            """
            INSERT INTO summaries
                (period_start, period_end, digest, narrative, event_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (period_start, period_end, digest, narrative, event_count, time.time()),
        )
        self._dirty = True
        await self.flush()
        return int(cursor.lastrowid or 0)

    async def get_summaries(
        self,
        since: float,
        until: float | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        if not self._db:
            raise RuntimeError("Database not opened")
        end = until if until is not None else time.time()
        cursor = await self._db.execute(
            """
            SELECT id, period_start, period_end, digest, narrative, event_count, created_at
            FROM summaries
            WHERE period_end >= ? AND period_start < ?
            ORDER BY period_start ASC
            LIMIT ?
            """,
            (since, end, limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "period_start": row[1],
                "period_end": row[2],
                "digest": row[3],
                "narrative": row[4],
                "event_count": row[5],
                "created_at": row[6],
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

    async def event_count_timeseries(
        self,
        topic: str,
        window_seconds: float = 3600,
        bucket_seconds: float = 60,
    ) -> list[dict[str, object]]:
        """Count discrete events per time bucket (detection_enter, sound, etc.)."""
        if not self._db:
            raise RuntimeError("Database not opened")
        now = time.time()
        start = now - window_seconds
        cursor = await self._db.execute(
            _EVENT_COUNT_TIMESERIES,
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
                "count": row[2],
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
