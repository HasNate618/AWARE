from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

Event = dict[str, Any]
Handler = Callable[[Event], Any]


class EventBus:
    """In-process async pub/sub for decoupled communication."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._history: list[Event] = []
        self._max_history = 1000

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._handlers[topic].append(handler)
        logger.debug("Subscribed to %s: %s", topic, handler.__qualname__)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        self._handlers[topic].remove(handler)

    async def publish(self, topic: str, event: Event) -> None:
        event.setdefault("topic", topic)
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        for handler in self._handlers.get(topic, []):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Handler error on topic %s", topic)

    def get_history(self, topic: str | None = None, limit: int = 50) -> list[Event]:
        if topic:
            return [e for e in self._history if e.get("topic") == topic][-limit:]
        return self._history[-limit:]
