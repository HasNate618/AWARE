from aware.app.config import Settings
from aware.app.llm.stub import StubLLM
from aware.app.memory.db import EventDB
from aware.app.memory.query import answer_question
from aware.app.memory.summarizer import MemorySummarizer


async def test_summarize_once_skips_single_walkby() -> None:
    db = EventDB(":memory:")
    await db.open()
    llm = StubLLM()
    summarizer = MemorySummarizer(db, llm, interval_seconds=300.0)

    await db.log("detection_enter", {"label": "person", "confidence": 0.9})
    result = await summarizer.summarize_once()
    assert result is None

    summaries = await db.get_summaries(since=0)
    assert len(summaries) == 1
    assert summaries[0]["narrative"] == ""
    await db.close()


async def test_summarize_once_stores_notable_period() -> None:
    db = EventDB(":memory:")
    await db.open()
    llm = StubLLM()
    summarizer = MemorySummarizer(db, llm, interval_seconds=300.0)

    base = 1_000_000.0
    for i in range(4):
        await db.log(
            "detection_enter",
            {"label": "person", "confidence": 0.9, "ts": base + i},
        )
    await db.log("sound", {"label": "speech", "confidence": 0.8})
    result = await summarizer.summarize_once()
    assert result is not None
    assert result.narrative
    assert "speech" in result.narrative.lower() or "people" in result.narrative.lower()
    await db.close()


async def test_summarize_once_stores_summary() -> None:
    db = EventDB(":memory:")
    await db.open()
    llm = StubLLM()
    summarizer = MemorySummarizer(db, llm, interval_seconds=300.0)

    for _ in range(3):
        await db.log("detection_enter", {"label": "person", "confidence": 0.9})
    result = await summarizer.summarize_once()
    assert result is not None
    assert result.event_count == 3
    assert "camera" in result.narrative.lower() or "people" in result.narrative.lower()

    summaries = await db.get_summaries(since=0)
    assert len(summaries) == 1
    await db.close()


async def test_answer_question() -> None:
    import asyncio

    db = EventDB(":memory:")
    await db.open()
    llm = StubLLM()
    settings = Settings()
    lock = asyncio.Lock()

    await db.log("detection_enter", {"label": "person", "confidence": 0.9})
    result = await answer_question(
        "what happened recently?",
        db,
        llm,
        settings,
        lock,
    )
    assert result.answer
    assert result.events_scanned >= 1
    await db.close()
