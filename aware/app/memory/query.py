from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from aware.app.config import Settings
from aware.app.llm.interface import LLMClient
from aware.app.memory.context import build_memory_context, parse_time_window
from aware.app.memory.db import EventDB


@dataclass
class AskResult:
    answer: str
    window_start: float
    window_end: float
    summaries_used: int
    events_scanned: int
    context_preview: str
    latency_ms: float
    used_llm: bool


async def answer_question(
    question: str,
    db: EventDB,
    llm: LLMClient,
    settings: Settings,
    llm_lock: asyncio.Lock,
    *,
    since: float | None = None,
    window: int | None = None,
) -> AskResult:
    """Build context from events/summaries and query the LLM."""
    start_time = time.monotonic()
    window_start, window_end = parse_time_window(
        question,
        since=since,
        window=window,
        default_seconds=settings.memory_default_window,
    )
    summaries = await db.get_summaries(since=window_start, until=window_end)
    events = await db.query_range(window_start, window_end)
    context = build_memory_context(
        question=question,
        window_start=window_start,
        window_end=window_end,
        summaries=summaries,
        events=events,
        max_chars=settings.memory_context_max_chars,
    )

    used_llm = True
    async with llm_lock:
        answer = await llm.query_memory(question, context)
    if answer.startswith("[error]"):
        used_llm = False

    latency_ms = (time.monotonic() - start_time) * 1000
    await db.log(
        "memory_query",
        {
            "question": question,
            "answer": answer[:1000],
            "window_start": window_start,
            "window_end": window_end,
        },
    )

    preview = context[:500] + ("..." if len(context) > 500 else "")
    return AskResult(
        answer=answer,
        window_start=window_start,
        window_end=window_end,
        summaries_used=len(summaries),
        events_scanned=len(events),
        context_preview=preview,
        latency_ms=round(latency_ms, 1),
        used_llm=used_llm,
    )
