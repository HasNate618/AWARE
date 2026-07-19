from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from aware.app.llm.interface import LLMClient
from aware.app.memory.db import EventDB
from aware.app.memory.digest import build_digest, digest_to_json
from aware.app.memory.witness import (
    build_witness_brief,
    build_witness_log,
    is_ai_narrative,
    is_brief_dump,
    narrative_grounded_in_brief,
    witness_brief_to_text,
    witness_log_to_text,
    witness_period_significant,
    witness_prose_from_events,
)

logger = logging.getLogger(__name__)


@dataclass
class SummaryResult:
    period_start: float
    period_end: float
    event_count: int
    narrative: str
    used_llm: bool


class MemorySummarizer:
    """Background task that compresses event windows into stored summaries."""

    def __init__(
        self,
        db: EventDB,
        llm: LLMClient,
        interval_seconds: float = 300.0,
        llm_lock: asyncio.Lock | None = None,
        llm_timeout: float = 120.0,
        use_llm: bool = False,
    ) -> None:
        self._db = db
        self._llm = llm
        self._interval = interval_seconds
        self._llm_lock = llm_lock or asyncio.Lock()
        self._llm_timeout = llm_timeout
        self._use_llm = use_llm

    async def run(self) -> None:
        logger.info("Memory summarizer started (interval=%ds)", int(self._interval))
        try:
            while True:
                await asyncio.sleep(self._interval)
                try:
                    result = await self.summarize_once()
                    if result:
                        logger.info(
                            "Summary stored: %d events, llm=%s",
                            result.event_count,
                            result.used_llm,
                        )
                except Exception:
                    logger.exception("Summarizer tick error")
        except asyncio.CancelledError:
            logger.info("Memory summarizer stopped")

    async def summarize_once(self) -> SummaryResult | None:
        now = time.time()
        last_end = await self._db.last_summary_end()
        if last_end is None:
            last_end = now - self._interval
        if now - last_end < self._interval * 0.9:
            return None

        events = await self._db.query_range(last_end, now)
        if not events:
            return None

        witness_events = build_witness_log(events)
        if not witness_events:
            return None

        witness_text = witness_log_to_text(witness_events)
        digest = build_digest(events)
        brief = build_witness_brief(witness_events, last_end, now)
        if brief and not witness_period_significant(brief):
            digest_json = witness_text or (digest_to_json(digest) if digest is not None else "")
            await self._db.store_summary(last_end, now, digest_json, "", len(events))
            logger.debug("Skipped low-significance witness period")
            return None

        brief_text = witness_brief_to_text(brief) if brief else witness_text
        narrative = witness_prose_from_events(
            witness_events,
            period_start=last_end,
            period_end=now,
        ) or witness_text
        used_llm = False
        previous_recap = await self._db.last_summary_narrative() or ""

        if self._use_llm and self._llm_lock.locked():
            logger.warning("LLM busy — storing witness log without narration")
        elif self._use_llm:
            try:
                async with asyncio.timeout(self._llm_timeout):
                    async with self._llm_lock:
                        llm_text = await self._llm.summarize_period(brief_text, previous_recap)
                if (
                    llm_text
                    and brief
                    and not is_brief_dump(llm_text)
                    and is_ai_narrative(llm_text)
                    and narrative_grounded_in_brief(brief, llm_text)
                ):
                    narrative = llm_text
                    used_llm = True
                else:
                    logger.warning("LLM summary rejected — not grounded in scene brief")
            except Exception:
                logger.exception("LLM summarization failed — using witness log fallback")

        digest_json = witness_text or (digest_to_json(digest) if digest is not None else "")
        await self._db.store_summary(
            last_end,
            now,
            digest_json,
            narrative,
            len(events),
        )
        await self._db.log(
            "summary_created",
            {
                "period_start": last_end,
                "period_end": now,
                "narrative": narrative[:500],
                "event_count": len(events),
                "used_llm": used_llm,
            },
        )
        return SummaryResult(
            period_start=last_end,
            period_end=now,
            event_count=len(events),
            narrative=narrative,
            used_llm=used_llm,
        )
