from __future__ import annotations

import ast
import logging
import time
from typing import Any

from aware.app.core.event_bus import EventBus
from aware.app.memory.db import EventDB
from aware.app.perception.interface import PerceptionSnapshot
from aware.app.rules.store import RulesStore

logger = logging.getLogger(__name__)


def _parse_time_range(raw: Any) -> tuple[int, int] | None:
    """Safely parse a time_range that might be a string repr of a tuple."""
    if isinstance(raw, tuple) and len(raw) == 2:
        return (int(raw[0]), int(raw[1]))
    if isinstance(raw, str):
        try:
            val = ast.literal_eval(raw)
            if isinstance(val, tuple) and len(val) == 2:
                return (int(val[0]), int(val[1]))
        except (ValueError, SyntaxError):
            pass
    return None


class RulesEngine:
    """Evaluates active rules against latest perception data every 500ms."""

    def __init__(
        self,
        store: RulesStore,
        bus: EventBus,
        db: EventDB,
    ) -> None:
        self.store = store
        self.bus = bus
        self.db = db
        self._last_snapshot: PerceptionSnapshot | None = None
        self._snap_handler = self._on_snapshot

    def _on_snapshot(self, event: dict[str, Any]) -> None:
        self._last_snapshot = event.get("snapshot")

    async def start(self) -> None:
        self.bus.subscribe("perception", self._snap_handler)

    async def stop(self) -> None:
        self.bus.unsubscribe("perception", self._snap_handler)

    async def evaluate(self) -> None:
        if not self._last_snapshot:
            return
        rules = await self.store.get_active()
        for rule in rules:
            if self._matches(rule, self._last_snapshot):
                await self._execute(rule)

    def _matches(self, rule: dict[str, object], snapshot: PerceptionSnapshot) -> bool:
        triggers: list[dict[str, str]] = rule.get("triggers", [])  # type: ignore[assignment]
        if not triggers:
            return False
        # AND semantics: ALL triggers must match
        return all(self._trigger_matches(t, snapshot) for t in triggers)

    def _trigger_matches(self, trigger: dict[str, str], snapshot: PerceptionSnapshot) -> bool:
        t_type = trigger.get("type", "")
        t_value = trigger.get("value", "")
        if t_type == "detection":
            return any(d.label == t_value for d in snapshot.detections)
        elif t_type == "sound":
            return any(s.label == t_value for s in snapshot.sounds)
        elif t_type == "time":
            hour = time.localtime().tm_hour
            time_range = _parse_time_range(trigger.get("time_range"))
            if time_range:
                start, end = time_range
                return start <= hour < end
        return False

    async def _execute(self, rule: dict[str, object]) -> None:
        actions: list[dict[str, str]] = rule.get("actions", [])  # type: ignore[assignment]
        name: str = rule.get("name", "unknown")  # type: ignore[assignment]
        logger.info("Rule '%s' matched, executing %d actions", name, len(actions))
        for action in actions:
            action_type = action.get("type", "log")
            await self.bus.publish("action", {
                "rule": name,
                "action": action_type,
                "params": action,
                "timestamp": time.time(),
            })
            await self.db.log("action_executed", {
                "rule": name,
                "action": action_type,
                "params": action,
            })
