from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from aware.app.memory.sensors import SENSOR_THRESHOLDS

# Labels worth narrating — keep in sync with YAMNet venue map.
WITNESS_SOUND_LABELS: frozenset[str] = frozenset(
    {
        "speech",
        "crying",
        "baby_cry",
        "dog",
        "dog_bark",
        "doorbell",
        "fire",
        "alarm",
        "siren",
        "knock",
        "glass_break",
    }
)

WITNESS_DETECTION_LABELS: frozenset[str] = frozenset({"person"})

_SENSOR_DISPLAY: dict[str, str] = {
    "temperature_c": "temperature",
    "distance_cm": "distance",
    "movement_intensity": "movement",
    "accel_x": "accel x",
    "accel_y": "accel y",
    "accel_z": "accel z",
}


@dataclass(frozen=True)
class WitnessEvent:
    timestamp: float
    line: str
    kind: str


def _fmt_clock(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _humanize(label: str) -> str:
    return label.replace("_", " ")


def _sensor_unit(name: str) -> str:
    if name == "temperature_c":
        return "°C"
    if name == "distance_cm":
        return "cm"
    return ""


def _sensor_line(name: str, prev: float, value: float, ts: float) -> str:
    delta = value - prev
    unit = _sensor_unit(name)
    label = _SENSOR_DISPLAY.get(name, name)
    return (
        f"{_fmt_clock(ts)} {label} {prev:.1f}{unit} → {value:.1f}{unit} ({delta:+.1f}{unit})"
    )


def build_witness_log(events: list[dict[str, object]]) -> list[WitnessEvent]:
    """Build a chronological witness log: people, venue sounds, sensor changes only."""
    witness: list[WitnessEvent] = []
    last_sensor: dict[str, float] = {}

    for event in events:
        topic = str(event["topic"])
        data = event.get("data", {})
        if not isinstance(data, dict):
            continue
        ts = float(str(event["timestamp"]))

        if topic == "detection_enter":
            label = str(data.get("label", ""))
            if label not in WITNESS_DETECTION_LABELS:
                continue
            witness.append(
                WitnessEvent(
                    timestamp=ts,
                    line=f"{_fmt_clock(ts)} person entered frame",
                    kind="person",
                )
            )
        elif topic == "sound":
            label = str(data.get("label", ""))
            if label not in WITNESS_SOUND_LABELS:
                continue
            witness.append(
                WitnessEvent(
                    timestamp=ts,
                    line=f"{_fmt_clock(ts)} {_humanize(label)} heard",
                    kind="sound",
                )
            )
        elif topic.startswith("sensor:"):
            name = topic.removeprefix("sensor:")
            value = data.get("value")
            if not isinstance(value, (int, float)):
                continue
            fval = float(value)
            prev = last_sensor.get(name)
            if prev is None:
                last_sensor[name] = fval
                continue
            threshold = SENSOR_THRESHOLDS.get(name, 0.0)
            if abs(fval - prev) < threshold:
                continue
            last_sensor[name] = fval
            witness.append(
                WitnessEvent(
                    timestamp=ts,
                    line=_sensor_line(name, prev, fval, ts),
                    kind="sensor",
                )
            )

    return witness


def witness_log_to_text(events: list[WitnessEvent], *, max_lines: int = 50) -> str:
    """Plain-text witness log for LLM prompts."""
    if not events:
        return ""
    tail = events[-max_lines:]
    return "\n".join(e.line for e in tail)


_CLOCK_LINE = re.compile(r"^\d{2}:\d{2}:\d{2} ")
_EVENT_LINE = re.compile(r"^\d{2}:\d{2}:\d{2} (.+)$")

# MiniCPM often emits meta-commentary instead of a summary.
_LLM_JUNK_RE = re.compile(
    r"(?i)"
    r"(next question|final answer|conclusion:|task\s*\d|create a table|"
    r"the log (contains|shows|entries)|analysis of|does not (provide|add)|"
    r"this activity log|purpose of (this|the) (activity )?log|"
    r"^\s*\|\s*name\s*\|)",
)


def is_ai_narrative(text: str) -> bool:
    """True when text looks like LLM prose, not a raw digest or witness log dump."""
    narrative = text.strip()
    if len(narrative) < 12 or len(narrative) > 280:
        return False
    if _LLM_JUNK_RE.search(narrative):
        return False
    if " | " in narrative:
        return False
    if "entered:" in narrative and "×" in narrative:
        return False
    if "accel_" in narrative or "movement_intensity" in narrative:
        return False
    lines = [ln for ln in narrative.splitlines() if ln.strip()]
    clock_lines = sum(1 for ln in lines if _CLOCK_LINE.match(ln))
    return clock_lines < 2 and not (len(lines) == 1 and bool(_CLOCK_LINE.match(lines[0])))


def witness_events_for_display(
    events: list[WitnessEvent],
    *,
    limit: int = 40,
) -> list[dict[str, object]]:
    """Structured witness lines for the dashboard (newest last)."""
    rows: list[dict[str, object]] = []
    for event in events[-limit:]:
        match = _EVENT_LINE.match(event.line)
        text = match.group(1) if match else event.line
        rows.append(
            {
                "timestamp": event.timestamp,
                "time": _fmt_clock(event.timestamp),
                "text": text,
                "kind": event.kind,
            }
        )
    return rows


_SENSOR_DELTA_RE = re.compile(
    r"^(?P<label>\w+) (?P<prev>[\d.]+)(?P<unit>°C|cm)? → (?P<val>[\d.]+)(?P=unit)? "
    r"\((?P<delta>[+-][\d.]+)(?P=unit)?\)$"
)


def witness_prose_from_events(events: list[WitnessEvent]) -> str:
    """Context-aware template prose when the LLM is unavailable or low quality."""
    if not events:
        return ""

    people = sum(1 for event in events if event.kind == "person")
    sound_counts: dict[str, int] = {}
    sensor_notes: list[str] = []

    for event in events:
        if event.kind == "sound":
            body = _EVENT_LINE.match(event.line)
            label = body.group(1).removesuffix(" heard") if body else "sound"
            sound_counts[label] = sound_counts.get(label, 0) + 1
            continue
        if event.kind != "sensor":
            continue
        body = _EVENT_LINE.match(event.line)
        if not body:
            continue
        parsed = _SENSOR_DELTA_RE.match(body.group(1))
        if not parsed:
            continue
        label = parsed.group("label")
        prev = float(parsed.group("prev"))
        val = float(parsed.group("val"))
        delta = float(parsed.group("delta"))
        if label == "distance":
            if delta <= -15:
                sensor_notes.append(
                    f"someone likely approached the booth (distance fell from {prev:.0f} to {val:.0f} cm)"
                )
            elif delta >= 15:
                sensor_notes.append(
                    f"movement away from the sensor (distance increased to {val:.0f} cm)"
                )
        elif label == "temperature" and abs(delta) >= 0.5:
            direction = "warmed" if delta > 0 else "cooled"
            sensor_notes.append(
                f"the area {direction} slightly ({prev:.1f} to {val:.1f} °C)"
            )
        elif label == "movement" and val >= 0.15:
            sensor_notes.append("noticeable movement was detected on the accelerometer")

    parts: list[str] = []
    if people == 1:
        parts.append("Someone passed through the camera view")
    elif people > 1:
        parts.append(f"{people} people passed through the camera view")

    if sound_counts:
        if len(sound_counts) == 1 and sum(sound_counts.values()) == 1:
            label = next(iter(sound_counts))
            parts.append(f"{label} was heard in the space")
        else:
            bits = [
                f"{label} ×{count}" if count > 1 else label
                for label, count in sound_counts.items()
            ]
            parts.append(f"Sounds in the space included {', '.join(bits)}")

    if sensor_notes:
        parts.append(sensor_notes[0])

    if not parts:
        return ""
    return ". ".join(parts) + "."


def witness_prose_from_log_text(text: str) -> str:
    """Rebuild template prose from stored witness log lines."""
    events: list[WitnessEvent] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "person entered frame" in stripped:
            kind = "person"
        elif " heard" in stripped:
            kind = "sound"
        else:
            kind = "sensor"
        events.append(WitnessEvent(timestamp=0.0, line=stripped, kind=kind))
    return witness_prose_from_events(events)


def _is_template_prose(text: str) -> bool:
    markers = (
        "passed through the camera view",
        "was heard in the space",
        "Sounds in the space included",
        "likely approached the booth",
        "movement away from the sensor",
        "noticeable movement was detected",
    )
    return any(marker in text for marker in markers)


def format_period_label(start: float, end: float) -> str:
    return (
        f"{datetime.fromtimestamp(start).strftime('%H:%M')}"
        f"–{datetime.fromtimestamp(end).strftime('%H:%M')}"
    )


def summaries_for_witness_display(
    summaries: list[dict[str, object]],
    *,
    limit: int = 12,
) -> list[dict[str, object]]:
    """Return witness recaps for the dashboard (LLM prose or contextual template fallback)."""
    logs: list[dict[str, object]] = []
    for row in summaries:
        narrative = str(row.get("narrative", "")).strip()
        if not narrative:
            continue
        if _is_template_prose(narrative):
            text = narrative
            ai = False
        elif is_ai_narrative(narrative):
            text = narrative
            ai = True
        else:
            text = witness_prose_from_log_text(narrative)
            ai = False
        if not text:
            continue
        period_start = float(str(row.get("period_start", 0)))
        period_end = float(str(row.get("period_end", 0)))
        logs.append(
            {
                "period_start": period_start,
                "period_end": period_end,
                "period_label": format_period_label(period_start, period_end),
                "text": text,
                "ai": ai,
            }
        )
    return logs[-limit:]
