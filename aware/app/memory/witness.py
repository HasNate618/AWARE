from __future__ import annotations

import re
from dataclasses import dataclass, field
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

_INVENTED_DETAIL_RE = re.compile(
    r"(?i)\b(backpack|laptop|smartphone|hoodie|sunglasses|man with|woman with|wearing)\b"
)


def is_brief_dump(text: str) -> bool:
    """Structured scene brief echoed as narrative — not display-ready prose."""
    lower = text.lower()
    return "traffic:" in lower and ("period:" in lower or "audio:" in lower)


def prose_from_brief_dump(text: str) -> str:
    """Turn a stored brief-format recap into readable witness prose."""
    if not is_brief_dump(text):
        return ""
    visitors = 0
    count_match = re.search(r"(\d+)\s+visitors?", text, re.I)
    if count_match:
        visitors = int(count_match.group(1))
    elif re.search(r"\bone visitor\b", text, re.I):
        visitors = 1
    has_speech = "speech" in text.lower()
    times = re.findall(r"(\d{2}:\d{2}:\d{2})", text)
    period_match = re.search(r"Period:\s*(\d{2}:\d{2}–\d{2}:\d{2})", text)
    window = period_match.group(1) if period_match else ""

    if visitors >= 8:
        start = times[0] if times else ""
        end = times[-1] if len(times) >= 2 else start
        base = (
            f"A concentrated burst between {start} and {end}: "
            f"the on-device camera logged {visitors} people passing through"
        )
        return f"{base}, with speech detected on the mic." if has_speech else f"{base}."

    if visitors >= 2:
        line = f"{visitors} people crossed the camera view"
        if window:
            line += f" during {window}"
        if has_speech:
            return f"{line}; speech was detected on the on-board mic."
        return f"{line}."

    if visitors == 1:
        when = times[0] if times else ""
        if has_speech:
            return (
                f"One person passed the camera around {when}; "
                f"speech was detected on the on-board mic."
            )
        return f"One person passed the camera around {when}."

    if has_speech:
        when = times[0] if times else ""
        return f"No camera traffic, but speech was picked up around {when}."
    return ""


def is_hallucinated_narrative(text: str) -> bool:
    """Obvious fiction — roleplay, dialogue, or details we never observed."""
    narrative = text.strip()
    if '"' in narrative or "''" in narrative:
        return True
    lower = narrative.lower()
    if re.search(r"\bi['']?m a\b", lower):
        return True
    return bool(_INVENTED_DETAIL_RE.search(narrative))


def narrative_grounded_in_brief(brief: WitnessBrief, narrative: str) -> bool:
    """True when LLM prose matches what the brief actually recorded."""
    if is_hallucinated_narrative(narrative):
        return False
    if is_brief_dump(narrative):
        return False
    if "booth" in narrative.lower():
        return False

    lower = narrative.lower()
    visitors = len(brief.visitor_times)
    sounds = len(brief.sounds)

    denies_people = any(
        phrase in lower
        for phrase in (
            "was empty",
            "booth was empty",
            "space was empty",
            "was empty and silent",
            "see no one",
            "no one was",
            "no one stopped",
            "no one here",
            "nobody",
            "nothing happened",
        )
    )
    mentions_audio = any(
        word in lower for word in ("heard", "speech", "sound", "voice", "talk", "noise")
    )
    mentions_people = any(
        word in lower
        for word in ("visitor", "person", "people", "passed", "walked", "stopped", "someone")
    )

    if visitors > 0 and denies_people:
        return False
    quiet_claim = any(word in lower for word in ("silent", "stayed quiet", "was quiet", "no one"))
    if sounds > 0 and not mentions_audio and quiet_claim:
        return False
    if visitors > 0 and not mentions_people:
        return False
    return not (sounds > 0 and visitors == 0 and not mentions_audio)


def is_ai_narrative(text: str) -> bool:
    """True when text looks like LLM prose, not a raw digest or witness log dump."""
    narrative = text.strip()
    if len(narrative) < 12 or len(narrative) > 280:
        return False
    if is_hallucinated_narrative(narrative):
        return False
    if is_brief_dump(narrative):
        return False
    if "booth" in narrative.lower():
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

_SOUND_HEARD_RE = re.compile(r"^(?P<label>.+) heard$")


@dataclass
class WitnessBrief:
    period_label: str
    period_minutes: int
    visitor_times: list[float] = field(default_factory=list)
    sounds: list[tuple[float, str]] = field(default_factory=list)
    approaches: list[tuple[float, float, float]] = field(default_factory=list)
    retreats: list[tuple[float, float]] = field(default_factory=list)
    temp_shift: tuple[float, float] | None = None
    movement_noted: bool = False
    stop_and_talk: list[float] = field(default_factory=list)


def _parse_event_timestamp(line: str) -> float | None:
    match = re.match(r"^(\d{2}):(\d{2}):(\d{2}) ", line)
    if not match:
        return None
    hour, minute, second = (int(match.group(i)) for i in range(1, 4))
    now = datetime.now()
    return datetime(now.year, now.month, now.day, hour, minute, second).timestamp()


def build_witness_brief(
    events: list[WitnessEvent],
    period_start: float,
    period_end: float,
) -> WitnessBrief | None:
    if not events:
        return None

    brief = WitnessBrief(
        period_label=format_period_label(period_start, period_end),
        period_minutes=max(1, int(round((period_end - period_start) / 60))),
    )

    for event in events:
        if event.kind == "person":
            brief.visitor_times.append(event.timestamp)
            continue
        if event.kind == "sound":
            body = _EVENT_LINE.match(event.line)
            if not body:
                continue
            heard = _SOUND_HEARD_RE.match(body.group(1))
            label = heard.group("label") if heard else body.group(1)
            brief.sounds.append((event.timestamp, label))
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
                brief.approaches.append((event.timestamp, prev, val))
            elif delta >= 15:
                brief.retreats.append((event.timestamp, val))
        elif label == "temperature" and abs(delta) >= 0.5:
            brief.temp_shift = (prev, val)
        elif label == "movement" and val >= 0.15:
            brief.movement_noted = True

    for ts, _label in brief.sounds:
        for vts in brief.visitor_times:
            if abs(ts - vts) <= 25:
                for ats, _prev, _val in brief.approaches:
                    if abs(ts - ats) <= 30 or abs(ts - vts) <= 20:
                        if ts not in brief.stop_and_talk:
                            brief.stop_and_talk.append(ts)
                        break

    return brief


def brief_significance_score(brief: WitnessBrief) -> int:
    """Higher = more worth a headline recap (not live-activity noise)."""
    score = 0
    visitors = len(brief.visitor_times)
    sounds = len(brief.sounds)
    if visitors >= 8:
        score += 12
    elif visitors >= 3:
        score += 8
    elif visitors == 2:
        score += 4
    elif visitors == 1:
        score += 1
    if sounds:
        score += 5
    if brief.stop_and_talk:
        score += 8
    if brief.approaches:
        score += 6
    if brief.movement_noted:
        score += 3
    if brief.temp_shift:
        score += 2
    return score


def witness_period_significant(brief: WitnessBrief) -> bool:
    """Only create a recap for periods worth a headline."""
    return brief_significance_score(brief) >= 6


_LOW_QUALITY_RECAP_RE = re.compile(
    r"(?i)"
    r"^(one person passed the camera around \d{2}:\d{2}:\d{2}\.?|"
    r"a person was detected on camera\.?|"
    r"\d+ visitors? between )"
)


def is_low_quality_recap(text: str) -> bool:
    """Tally dumps, brief echoes, and lone walk-bys belong in live activity only."""
    narrative = text.strip()
    if not narrative:
        return True
    if is_brief_dump(narrative):
        return False
    lower = narrative.lower()
    if "traffic:" in lower or "proximity:" in lower or "environment:" in lower:
        return True
    if _LOW_QUALITY_RECAP_RE.match(narrative):
        return True
    return len(narrative) < 24 and "visitor" not in lower and "people" not in lower


def recap_display_score(text: str, digest: str = "") -> int:
    """Rank recaps for the dashboard — show only the most notable."""
    if digest:
        events: list[WitnessEvent] = []
        for line in digest.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            ts = _parse_event_timestamp(stripped) or 0.0
            if "person entered frame" in stripped:
                kind = "person"
            elif " heard" in stripped:
                kind = "sound"
            else:
                kind = "sensor"
            events.append(WitnessEvent(timestamp=ts, line=stripped, kind=kind))
        if events:
            brief = build_witness_brief(events, events[0].timestamp, events[-1].timestamp)
            if brief:
                return brief_significance_score(brief)

    score = 0
    lower = text.lower()
    if re.search(r"\d+ people|\d+ visitors|concentrated burst|busy", lower):
        score += 10
    if any(word in lower for word in ("speech", "voice", "mic", "spoke", "talk")):
        score += 5
    if any(word in lower for word in ("closer", "sensor", "lingered", "approach")):
        score += 5
    if is_low_quality_recap(text):
        score = min(score, 2)
    return score


def witness_brief_to_text(brief: WitnessBrief) -> str:
    """Semantic brief for the LLM — patterns, not raw event dumps."""
    lines = [f"Period: {brief.period_label} (~{brief.period_minutes} min)"]

    visitors = len(brief.visitor_times)
    if visitors:
        start = _fmt_clock(min(brief.visitor_times))
        end = _fmt_clock(max(brief.visitor_times))
        if visitors == 1:
            lines.append(f"Traffic: one visitor at {start}")
        elif visitors >= 6:
            lines.append(f"Traffic: busy spell — {visitors} visitors mostly {start}–{end}")
        else:
            lines.append(f"Traffic: {visitors} visitors between {start} and {end}")
    else:
        lines.append("Traffic: no visitors")

    if brief.sounds:
        labels = sorted({label for _, label in brief.sounds})
        times = ", ".join(_fmt_clock(ts) for ts, _ in brief.sounds[:4])
        if len(brief.sounds) == 1:
            lines.append(f"Audio: {labels[0]} at {times}")
        else:
            lines.append(f"Audio: {', '.join(labels)} ({len(brief.sounds)} events, e.g. {times})")
    else:
        lines.append("Audio: quiet")

    if brief.approaches:
        ats, prev, val = brief.approaches[0]
        lines.append(
            f"Proximity: approached at {_fmt_clock(ats)} ({prev:.0f}cm → {val:.0f}cm)"
        )
    if brief.retreats:
        rts, val = brief.retreats[-1]
        lines.append(f"Proximity: moved away at {_fmt_clock(rts)} (to {val:.0f}cm)")

    if brief.stop_and_talk:
        lines.append(
            "Scene: speech overlapped with someone moving in close "
            f"around {_fmt_clock(brief.stop_and_talk[0])}"
        )
    if brief.temp_shift:
        prev, val = brief.temp_shift
        lines.append(f"Environment: temperature {prev:.1f}°C → {val:.1f}°C")
    if brief.movement_noted:
        lines.append("Environment: bump or movement on the sensor module")

    return "\n".join(lines)


def witness_prose_from_brief(brief: WitnessBrief) -> str:
    """Narrative fallback — scene description, not a tally."""
    visitors = len(brief.visitor_times)
    sounds = len(brief.sounds)
    sound_labels = sorted({label for _, label in brief.sounds})
    window = brief.period_label

    if brief.stop_and_talk:
        when = _fmt_clock(brief.stop_and_talk[0])
        return (
            f"Around {when}, someone lingered in view — speech was picked up "
            f"on the on-board mic as they moved closer to the sensor."
        )

    if visitors >= 8:
        start = _fmt_clock(min(brief.visitor_times))
        end = _fmt_clock(max(brief.visitor_times))
        base = (
            f"A concentrated burst between {start} and {end}: "
            f"the on-device camera logged {visitors} people passing through"
        )
        if sounds:
            return f"{base}, with speech detected on the mic."
        return f"{base}."

    if visitors >= 3:
        if sounds:
            label = "speech" if "speech" in sound_labels else sound_labels[0]
            return (
                f"Between {window}, {visitors} people crossed the camera view "
                f"and {label} was detected on the on-board mic."
            )
        return f"Between {window}, {visitors} people crossed the camera view."

    if visitors == 1 and sounds and brief.approaches:
        when = _fmt_clock(brief.visitor_times[0])
        return (
            f"Around {when}, one person stopped in view, spoke briefly, "
            f"and moved in toward the sensor."
        )

    if visitors == 1 and brief.approaches:
        when = _fmt_clock(brief.approaches[0][0])
        return f"Someone moved closer to the sensor around {when} without much audio activity."

    if visitors == 1:
        when = _fmt_clock(brief.visitor_times[0])
        return f"One person passed the camera around {when}."

    if visitors == 2:
        if sounds:
            label = "speech" if "speech" in sound_labels else sound_labels[0]
            return (
                f"Two people passed the camera during {window}; "
                f"{label} was detected on the on-board mic."
            )
        return f"Two people passed the camera during {window}."

    if sounds == 1:
        when = _fmt_clock(brief.sounds[0][0])
        label = brief.sounds[0][1]
        return f"No camera traffic, but {label} was picked up around {when}."

    if sounds > 1:
        label = "speech" if "speech" in sound_labels else ", ".join(sound_labels)
        return (
            f"Audio activity during {window} ({label}) without much camera traffic."
        )

    if brief.approaches:
        when = _fmt_clock(brief.approaches[0][0])
        return f"Movement near the sensor around {when} — someone moved in close."

    if brief.temp_shift:
        prev, val = brief.temp_shift
        direction = "warmed" if val > prev else "cooled"
        return f"The space {direction} slightly during {window} ({prev:.1f}°C to {val:.1f}°C)."

    return ""


def witness_prose_from_events(
    events: list[WitnessEvent],
    *,
    period_start: float | None = None,
    period_end: float | None = None,
) -> str:
    """Context-aware template prose when the LLM is unavailable or low quality."""
    if not events:
        return ""
    start = period_start if period_start is not None else events[0].timestamp
    end = period_end if period_end is not None else events[-1].timestamp
    brief = build_witness_brief(events, start, end)
    if brief is None:
        return ""
    return witness_prose_from_brief(brief)


def witness_prose_from_log_text(text: str) -> str:
    """Rebuild template prose from stored witness log lines."""
    events: list[WitnessEvent] = []
    timestamps: list[float] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        ts = _parse_event_timestamp(stripped) or 0.0
        if ts:
            timestamps.append(ts)
        if "person entered frame" in stripped:
            kind = "person"
        elif " heard" in stripped:
            kind = "sound"
        else:
            kind = "sensor"
        events.append(WitnessEvent(timestamp=ts, line=stripped, kind=kind))
    if not events:
        return ""
    start = min(timestamps) if timestamps else 0.0
    end = max(timestamps) if timestamps else start + 300
    return witness_prose_from_events(events, period_start=start, period_end=end)


def _suspect_false_quiet(narrative: str) -> bool:
    """LLM often claims 'empty' without mentioning any real activity."""
    lower = narrative.lower()
    quiet = any(
        phrase in lower
        for phrase in ("empty", "silent", "no one", "nobody", "see no one", "quiet few")
    )
    mentions_facts = any(
        word in lower
        for word in ("heard", "speech", "sound", "voice", "visitor", "passed", "people", "talk")
    )
    return quiet and not mentions_facts


def _is_template_prose(text: str) -> bool:
    markers = (
        "passed the camera",
        "crossed the camera view",
        "on-device camera",
        "on-board mic",
        "concentrated burst",
        "lingered in view",
        "moved in toward the sensor",
        "moved in close",
        "The space warmed",
        "The space cooled",
    )
    return any(marker in text for marker in markers)


def _booth_fallback_prose(narrative: str) -> str:
    """Rewrite legacy booth-framed LLM lines into neutral witness prose."""
    lower = narrative.lower()
    if "booth" not in lower:
        return ""
    has_person = any(word in lower for word in ("person", "people", "visitor", "someone"))
    has_speech = "speech" in lower or "heard" in lower or "voice" in lower
    if has_person and has_speech:
        return "A person was detected on camera and speech was picked up on the on-board mic."
    if has_person:
        return "A person was detected on camera."
    if has_speech:
        return "Speech was picked up on the on-board mic."
    return "Activity was detected on the on-device sensors."


def format_period_label(start: float, end: float) -> str:
    return (
        f"{datetime.fromtimestamp(start).strftime('%H:%M')}"
        f"–{datetime.fromtimestamp(end).strftime('%H:%M')}"
    )


def summaries_for_witness_display(
    summaries: list[dict[str, object]],
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    """Return the most notable witness recaps for a quick-glance summary."""
    candidates: list[dict[str, object]] = []
    for row in summaries:
        narrative = str(row.get("narrative", "")).strip()
        if not narrative:
            continue
        digest = str(row.get("digest", "")).strip()
        if is_brief_dump(narrative):
            text = prose_from_brief_dump(narrative)
            ai = False
        elif "booth" in narrative.lower() or is_hallucinated_narrative(narrative):
            text = (
                prose_from_brief_dump(narrative)
                or witness_prose_from_log_text(digest)
                or witness_prose_from_log_text(narrative)
                or _booth_fallback_prose(narrative)
            )
            ai = False
        elif _is_template_prose(narrative):
            text = narrative
            ai = False
        elif _suspect_false_quiet(narrative):
            text = witness_prose_from_log_text(digest) or witness_prose_from_log_text(narrative)
            if not text:
                continue
            ai = False
        elif is_ai_narrative(narrative) and not is_low_quality_recap(narrative):
            text = narrative
            ai = True
        else:
            text = witness_prose_from_log_text(digest) or witness_prose_from_log_text(narrative)
            ai = False
        if not text or is_low_quality_recap(text):
            continue
        period_start = float(str(row.get("period_start", 0)))
        period_end = float(str(row.get("period_end", 0)))
        candidates.append(
            {
                "period_start": period_start,
                "period_end": period_end,
                "period_label": format_period_label(period_start, period_end),
                "text": text,
                "ai": ai,
                "_score": recap_display_score(text, digest),
            }
        )

    candidates.sort(
        key=lambda row: (float(str(row["_score"])), float(str(row["period_end"]))),
        reverse=True,
    )
    logs: list[dict[str, object]] = []
    for row in candidates[:limit]:
        row = dict(row)
        row.pop("_score", None)
        logs.append(row)
    logs.sort(key=lambda row: float(str(row["period_end"])))
    return logs
