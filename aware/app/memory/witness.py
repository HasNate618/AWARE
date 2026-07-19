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


def is_ai_narrative(text: str) -> bool:
    """True when text looks like LLM prose, not a raw digest or witness log dump."""
    narrative = text.strip()
    if len(narrative) < 12:
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
    """Return AI-generated witness log entries for the dashboard."""
    logs: list[dict[str, object]] = []
    for row in summaries:
        narrative = str(row.get("narrative", "")).strip()
        if not is_ai_narrative(narrative):
            continue
        period_start = float(str(row.get("period_start", 0)))
        period_end = float(str(row.get("period_end", 0)))
        logs.append(
            {
                "period_start": period_start,
                "period_end": period_end,
                "period_label": format_period_label(period_start, period_end),
                "text": narrative,
            }
        )
    return logs[-limit:]
