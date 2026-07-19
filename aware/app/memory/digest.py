from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class PeriodDigest:
    period_start: float
    period_end: float
    detections_entered: dict[str, int] = field(default_factory=dict)
    detections_exited: dict[str, int] = field(default_factory=dict)
    sounds: dict[str, int] = field(default_factory=dict)
    actions: list[dict[str, object]] = field(default_factory=list)
    rules_created: list[str] = field(default_factory=list)
    sensors: dict[str, dict[str, float]] = field(default_factory=dict)


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _sensor_name(topic: str) -> str:
    return topic.removeprefix("sensor:")


def _update_sensor_stats(
    sensors: dict[str, dict[str, float]],
    name: str,
    value: float,
) -> None:
    if name not in sensors:
        sensors[name] = {
            "min": value,
            "max": value,
            "avg": value,
            "first": value,
            "last": value,
            "count": 1.0,
            "sum": value,
        }
        return
    stats = sensors[name]
    stats["min"] = min(float(stats["min"]), value)
    stats["max"] = max(float(stats["max"]), value)
    stats["last"] = value
    stats["count"] = float(stats["count"]) + 1.0
    stats["sum"] = float(stats["sum"]) + value
    stats["avg"] = float(stats["sum"]) / float(stats["count"])


def build_digest(events: list[dict[str, object]]) -> PeriodDigest | None:
    if not events:
        return None

    first_ts = events[0].get("timestamp", 0)
    last_ts = events[-1].get("timestamp", 0)
    period_start = float(str(first_ts))
    period_end = float(str(last_ts))
    digest = PeriodDigest(period_start=period_start, period_end=period_end)
    seen_actions: set[tuple[str, str, int]] = set()

    for event in events:
        topic = str(event["topic"])
        data = event.get("data", {})
        if not isinstance(data, dict):
            continue
        ts = int(float(str(event["timestamp"])))

        if topic == "detection_enter":
            label = str(data.get("label", "unknown"))
            digest.detections_entered[label] = digest.detections_entered.get(label, 0) + 1
        elif topic == "detection_exit":
            label = str(data.get("label", "unknown"))
            digest.detections_exited[label] = digest.detections_exited.get(label, 0) + 1
        elif topic == "sound":
            label = str(data.get("label", "sound"))
            digest.sounds[label] = digest.sounds.get(label, 0) + 1
        elif topic == "action_executed":
            rule = str(data.get("rule", "unknown"))
            action = str(data.get("action", "log"))
            key = (rule, action, ts)
            if key in seen_actions:
                continue
            seen_actions.add(key)
            digest.actions.append(
                {
                    "rule": rule,
                    "action": action,
                    "detection": str(data.get("detection_label", "")),
                    "message": str(data.get("message", "")),
                    "timestamp": ts,
                }
            )
        elif topic == "rule_created":
            digest.rules_created.append(str(data.get("name", "unknown")))
        elif topic.startswith("sensor:"):
            value = data.get("value")
            if isinstance(value, (int, float)):
                _update_sensor_stats(digest.sensors, _sensor_name(topic), float(value))

    if (
        not digest.detections_entered
        and not digest.detections_exited
        and not digest.sounds
        and not digest.actions
        and not digest.rules_created
        and not digest.sensors
    ):
        return None

    return digest


def digest_to_text(digest: PeriodDigest) -> str:
    parts: list[str] = [
        f"{_fmt_time(digest.period_start)}–{_fmt_time(digest.period_end)}",
    ]

    if digest.detections_entered:
        entered = ", ".join(f"{k}×{v}" for k, v in sorted(digest.detections_entered.items()))
        parts.append(f"entered: {entered}")
    if digest.detections_exited:
        exited = ", ".join(f"{k}×{v}" for k, v in sorted(digest.detections_exited.items()))
        parts.append(f"exited: {exited}")
    if digest.sounds:
        sounds = ", ".join(f"{k}×{v}" for k, v in sorted(digest.sounds.items()))
        parts.append(f"sounds: {sounds}")
    for name, stats in sorted(digest.sensors.items()):
        first = float(stats["first"])
        last = float(stats["last"])
        delta = last - first
        unit = "°C" if name == "temperature_c" else ("cm" if name == "distance_cm" else "")
        parts.append(f"{name} {first:.1f}→{last:.1f}{unit} ({delta:+.1f})")
    for action in digest.actions:
        rule = str(action.get("rule", ""))
        act = str(action.get("action", ""))
        msg = str(action.get("message", ""))
        if msg:
            parts.append(f"action: {rule} {act} — {msg}")
        else:
            parts.append(f"action: {rule} {act}")
    if digest.rules_created:
        parts.append(f"rules created: {', '.join(digest.rules_created)}")

    return " | ".join(parts)


def digest_to_json(digest: PeriodDigest) -> str:
    return json.dumps(asdict(digest))


def digest_from_json(raw: str) -> PeriodDigest:
    data = json.loads(raw)
    return PeriodDigest(
        period_start=float(data["period_start"]),
        period_end=float(data["period_end"]),
        detections_entered=dict(data.get("detections_entered", {})),
        detections_exited=dict(data.get("detections_exited", {})),
        sounds=dict(data.get("sounds", {})),
        actions=list(data.get("actions", [])),
        rules_created=list(data.get("rules_created", [])),
        sensors=dict(data.get("sensors", {})),
    )
