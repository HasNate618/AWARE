from __future__ import annotations

import re
import time
from datetime import datetime

from aware.app.memory.witness import build_witness_log

_TIME_PATTERNS: list[tuple[re.Pattern[str], object]] = [
    (re.compile(r"last\s+(\d+)\s+minutes?", re.I), lambda m, now: int(m.group(1)) * 60),
    (re.compile(r"last\s+(\d+)\s+hours?", re.I), lambda m, now: int(m.group(1)) * 3600),
    (re.compile(r"(?:last|past)\s+hour", re.I), lambda m, now: 3600),
    (re.compile(r"just\s+now|recently", re.I), lambda m, now: 600),
    (re.compile(r"today", re.I), lambda m, now: _seconds_since_midnight(now)),
    (re.compile(r"this\s+morning", re.I), lambda m, now: _morning_window(now)),
    (re.compile(r"(?:tonight|this\s+evening)", re.I), lambda m, now: _evening_window(now)),
]


def _seconds_since_midnight(now: float) -> int:
    dt = datetime.fromtimestamp(now)
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(now - midnight.timestamp())


def _morning_window(now: float) -> int:
    dt = datetime.fromtimestamp(now)
    morning_start = dt.replace(hour=6, minute=0, second=0, microsecond=0)
    if dt.hour < 6:
        return int(now - morning_start.timestamp()) if now > morning_start.timestamp() else 3600
    if dt.hour < 12:
        return int(now - morning_start.timestamp())
    return 6 * 3600


def _evening_window(now: float) -> int:
    dt = datetime.fromtimestamp(now)
    evening_start = dt.replace(hour=18, minute=0, second=0, microsecond=0)
    if dt.hour < 18:
        return 3600
    return int(now - evening_start.timestamp())


def parse_time_window(
    question: str,
    now: float | None = None,
    *,
    default_seconds: int = 3600,
    since: float | None = None,
    window: int | None = None,
) -> tuple[float, float]:
    """Return (start, end) unix timestamps for a memory query."""
    end = now if now is not None else time.time()
    if since is not None:
        start = since
        if window is not None:
            end = min(end, since + window)
        return start, end
    if window is not None:
        return end - window, end

    for pattern, resolver in _TIME_PATTERNS:
        match = pattern.search(question)
        if match:
            seconds = int(resolver(match, end))  # type: ignore[operator]
            return end - seconds, end

    return end - default_seconds, end


def _summary_lines(summaries: list[dict[str, object]]) -> list[str]:
    lines: list[str] = []
    for summary in summaries:
        narrative = str(summary.get("narrative", "")).strip()
        if not narrative or " | " in narrative or "accel_" in narrative:
            continue
        lines.append(narrative)
    return lines


def build_memory_context(
    *,
    question: str,
    window_start: float,
    window_end: float,
    summaries: list[dict[str, object]],
    events: list[dict[str, object]],
    max_chars: int = 6000,
) -> str:
    """Assemble a context string for query_memory. Truncates oldest content first."""
    start_str = datetime.fromtimestamp(window_start).strftime("%Y-%m-%d %H:%M")
    end_str = datetime.fromtimestamp(window_end).strftime("%Y-%m-%d %H:%M")
    sections: list[str] = [f"Activity log from {start_str} to {end_str}."]

    sections.extend(_summary_lines(summaries))

    last_summary_end = max(
        (float(str(s["period_end"])) for s in summaries),
        default=window_start,
    )
    tail_events = [e for e in events if float(str(e["timestamp"])) >= last_summary_end]
    witness_tail = build_witness_log(tail_events)
    if witness_tail:
        sections.append("Recent witness log:")
        sections.extend(e.line for e in witness_tail[-30:])

    witness_all = build_witness_log(events)
    if witness_all and not witness_tail:
        sections.append("Witness log:")
        sections.extend(e.line for e in witness_all[-40:])

    while sections and sum(len(s) + 1 for s in sections) > max_chars:
        if len(sections) <= 2:
            sections[1] = sections[1][: max(0, max_chars - len(sections[0]) - 1)]
            break
        if len(sections) > 2:
            sections.pop(2)
        else:
            break

    return "\n".join(sections)


def digest_fallback_answer(context: str, question: str) -> str:
    """Return a useful answer from the activity log when the LLM is unavailable."""
    body = context.strip()
    if not body:
        return "No activity was logged for that time period."
    return (
        "The on-device language model did not respond in time. "
        "Here is the activity log for your question:\n\n"
        f"{body}"
    )
