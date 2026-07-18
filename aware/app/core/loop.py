from __future__ import annotations

import asyncio
import logging
import time

from aware.app.core.event_bus import EventBus
from aware.app.rules.engine import RulesEngine

logger = logging.getLogger(__name__)


class RulesLoop:
    """500ms tick loop: fetch perception snapshot, evaluate rules, execute actions."""

    def __init__(
        self,
        engine: RulesEngine,
        bus: EventBus,
        tick_ms: int = 500,
    ) -> None:
        self.engine = engine
        self.bus = bus
        self.tick_ms = tick_ms
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("Rules loop started (%dms tick)", self.tick_ms)
        while self._running:
            start = time.monotonic()
            try:
                await self.engine.evaluate()
            except Exception:
                logger.exception("Rules engine tick error")
            elapsed = (time.monotonic() - start) * 1000
            sleep_ms = max(0, self.tick_ms - elapsed)
            await asyncio.sleep(sleep_ms / 1000)

    def stop(self) -> None:
        self._running = False
        logger.info("Rules loop stopped")
