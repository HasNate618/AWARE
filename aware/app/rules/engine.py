from __future__ import annotations

import ast
import logging
import time
from typing import Any

from aware.app.core.event_bus import EventBus
from aware.app.memory.db import EventDB
from aware.app.perception.interface import Detection, PerceptionSnapshot
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

    # Minimum seconds between re-executions of the same rule
    COOLDOWN: float = 5.0

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
        self._last_fired: dict[str, float] = {}  # rule name -> last execution time

    def _on_snapshot(self, event: dict[str, Any]) -> None:
        self._last_snapshot = event.get("snapshot")

    async def start(self) -> None:
        self.bus.subscribe("perception", self._snap_handler)

    async def stop(self) -> None:
        self.bus.unsubscribe("perception", self._snap_handler)

    async def evaluate(self) -> None:
        if not self._last_snapshot:
            return
        now = time.time()
        rules = await self.store.get_active()
        for rule in rules:
            name = rule.get("name", "unknown")
            # Cooldown: skip if this rule fired recently
            last = self._last_fired.get(str(name), 0.0)
            if now - last < self.COOLDOWN:
                continue
            matched_det = self._find_matching_detection(rule, self._last_snapshot)
            if matched_det:
                self._last_fired[str(name)] = now
                await self._execute(rule, matched_det)

    def _find_matching_detection(
        self, rule: dict[str, object], snapshot: PerceptionSnapshot
    ) -> Detection | None:
        """Find the first detection that matches this rule's triggers, or None."""
        triggers: list[dict[str, str]] = rule.get("triggers", [])  # type: ignore[assignment]
        if not triggers:
            return None

        # Build candidate focus items from detections, sounds, and enter/exit transitions
        candidates: list[Detection] = list(snapshot.detections)
        for label in snapshot.entered:
            if not any(d.label == label for d in candidates):
                candidates.append(Detection(label=label, confidence=1.0))
        for label in snapshot.exited:
            if not any(d.label == label for d in candidates):
                candidates.append(Detection(label=label, confidence=1.0))
        candidates.extend(snapshot.sounds)

        # AND semantics: ALL triggers must match
        for focus in candidates:
            if all(self._trigger_matches(t, snapshot, focus) for t in triggers):
                return focus
        return None

    def _matches(self, rule: dict[str, object], snapshot: PerceptionSnapshot) -> bool:
        return self._find_matching_detection(rule, snapshot) is not None

    def _trigger_matches(
        self, trigger: dict[str, str], snapshot: PerceptionSnapshot, focus: Detection | None = None
    ) -> bool:
        t_type = trigger.get("type", "")
        t_value = trigger.get("value", "")
        t_transition = trigger.get("transition")
        if t_type == "detection":
            if t_transition == "enter":
                return t_value in snapshot.entered
            elif t_transition == "exit":
                return t_value in snapshot.exited
            # No transition: match any current detection (existing behavior)
            if focus and focus.label == t_value:
                return True
            return any(d.label == t_value for d in snapshot.detections)
        elif t_type == "sound":
            if focus and focus.label == t_value:
                return True
            return any(s.label == t_value for s in snapshot.sounds)
        elif t_type == "time":
            hour = time.localtime().tm_hour
            time_range = _parse_time_range(trigger.get("time_range"))
            if time_range:
                start, end = time_range
                return start <= hour < end
        elif t_type == "sensor":
            sensor_key = t_value
            op: str = trigger.get("sensor_op", "lt")
            threshold_raw = trigger.get("sensor_threshold")
            if not isinstance(threshold_raw, (int, float)):
                return False
            threshold = float(threshold_raw)
            reading = snapshot.sensors.get(sensor_key)
            if reading is None:
                return False
            if op == "lt":
                return reading < threshold
            elif op == "gt":
                return reading > threshold
        return False

    async def _execute(self, rule: dict[str, object], detection: Detection) -> None:
        actions: list[dict[str, str]] = rule.get("actions", [])  # type: ignore[assignment]
        name: str = rule.get("name", "unknown")  # type: ignore[assignment]
        logger.info(
            "Rule '%s' matched (%s %.0f%%), executing %d actions",
            name,
            detection.label,
            detection.confidence * 100,
            len(actions),
        )
        for action in actions:
            action_type = action.get("type", "log")
            await self.bus.publish(
                "action",
                {
                    "rule": name,
                    "action": action_type,
                    "params": action,
                    "detection": {
                        "label": detection.label,
                        "confidence": detection.confidence,
                        "bbox": detection.bbox,
                    },
                    "timestamp": time.time(),
                },
            )
