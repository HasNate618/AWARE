from aware.app.memory.context import build_memory_context, parse_time_window


def test_parse_last_hour() -> None:
    now = 1_700_000_000.0
    start, end = parse_time_window("what happened in the last hour?", now=now)
    assert end == now
    assert end - start == 3600


def test_parse_last_30_minutes() -> None:
    now = 1_700_000_000.0
    start, end = parse_time_window("last 30 minutes", now=now)
    assert end - start == 1800


def test_parse_explicit_window() -> None:
    now = 1_700_000_000.0
    start, end = parse_time_window("anything", now=now, window=600)
    assert end - start == 600


def test_build_memory_context_includes_summary() -> None:
    context = build_memory_context(
        question="what happened?",
        window_start=100.0,
        window_end=500.0,
        summaries=[{"narrative": "A person entered at 11:15.", "period_end": 400.0}],
        events=[
            {
                "id": 1,
                "timestamp": 450.0,
                "topic": "detection_enter",
                "data": {"label": "person"},
            },
        ],
        max_chars=6000,
    )
    assert "A person entered" in context
    assert "person entered" in context
