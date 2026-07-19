from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from aware.app.parser import vocabulary as vocab

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_CMD_SPLIT = re.compile(r"\s+then\s+", re.IGNORECASE)
_WHEN_ACTION_RE = re.compile(
    r"^when\s+(.+?)\s+(say|speak|announce|play|flash|turn on|turn off|notify)\s+(.+)$",
    re.IGNORECASE,
)


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("_", text.lower()).strip("_")[:50]


@dataclass
class Trigger:
    type: str
    value: str
    time_range: tuple[int, int] | None = None
    transition: str | None = None
    sensor_op: str | None = None
    sensor_threshold: float | None = None


@dataclass
class Action:
    type: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedRule:
    name: str
    triggers: list[Trigger] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    priority: str = "normal"


def parse_when(text: str, raw: str | None = None) -> list[Trigger]:
    """Parse when text into triggers. `raw` is the original user input
    (used for transition detection, since the LLM may strip it)."""
    triggers: list[Trigger] = []
    seen: set[str] = set()
    lower = text.lower()
    parts = [p.strip() for p in lower.replace(" & ", " and ").split(" and ")]

    # Use raw input for transition detection if available (LLM may strip transitions)
    transition_source = (raw or text).lower()

    for part in parts:
        part_lower = part
        # Detect transition keyword across the full raw command
        trans: str | None = None
        for kw, t in vocab.TRANSITIONS.items():
            if kw in transition_source:
                trans = t
                break
        # Find sounds in this part
        for keyword, label in vocab.SOUNDS.items():
            if keyword in part_lower:
                skey = f"sound:{label}"
                if skey not in seen:
                    triggers.append(Trigger(type="sound", value=label))
                    seen.add(skey)
        # Find objects in this part (with optional transition)
        for keyword, label in vocab.OBJECTS.items():
            if keyword in part_lower:
                skey = f"detection:{label}:{trans or ''}"
                if skey not in seen:
                    triggers.append(Trigger(type="detection", value=label, transition=trans))
                    seen.add(skey)
        # Find times in this part
        for keyword, (start, end) in vocab.TIMES.items():
            if keyword in part_lower:
                skey = f"time:{keyword}"
                if skey not in seen:
                    triggers.append(Trigger(type="time", value=keyword, time_range=(start, end)))
                    seen.add(skey)
        # Find sensor conditions in this part (proximity, temperature, motion)
        for keyword, (sensor_key, op, default_threshold) in vocab.SENSOR_CONDITIONS.items():
            if keyword in part_lower:
                threshold = default_threshold
                dist_m = vocab._DISTANCE_RE.search(part_lower)
                if dist_m:
                    val = int(dist_m.group(1))
                    unit = dist_m.group(2)
                    if unit == "m":
                        val *= 100
                    elif unit == "mm":
                        val //= 10
                    threshold = float(val)
                skey = f"sensor:{sensor_key}:{op}:{threshold}"
                if skey not in seen:
                    triggers.append(Trigger(
                        type="sensor", value=sensor_key,
                        sensor_op=op, sensor_threshold=threshold,
                    ))
                    seen.add(skey)
    # Also check full text for absolute time patterns
    match = vocab.TIME_RE.search(text)
    if match:
        hour = int(match.group(1))
        ampm = match.group(2).lower()
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        skey = f"time:after_{hour}:00"
        if skey not in seen:
            triggers.append(Trigger(type="time", value=f"after {hour}:00", time_range=(hour, 24)))
    return triggers


def parse_then(text: str) -> list[Action]:
    actions: list[Action] = []
    lower = text.lower()
    for keyword, spec in vocab.ACTIONS.items():
        if keyword in lower:
            params: dict[str, str] = {}
            if spec["param"] == "text":
                params["text"] = text
            elif spec["param"] == "color":
                for color_name, rgb in vocab.COLORS.items():
                    if color_name in lower:
                        params["color"] = color_name
                        params["rgb"] = str(rgb)
                        break
                else:
                    params["color"] = "white"
                    params["rgb"] = str((255, 255, 255))
            actions.append(Action(type=spec["type"], params=params))
    if not actions:
        actions.append(Action(type="log", params={"text": text}))
    return actions


def parse_rule(
    name: str, when: str, then: str, priority: str = "normal", raw: str | None = None
) -> ParsedRule:
    return ParsedRule(
        name=name,
        triggers=parse_when(when, raw=raw),
        actions=parse_then(then),
        priority=priority,
    )


def parse_rule_from_command(command: str) -> ParsedRule:
    """Parse a full teach-style command without the LLM (when X then Y)."""
    text = command.strip().rstrip(".")
    when_raw = ""
    then_raw = ""
    if _CMD_SPLIT.search(text):
        when_part, then_part = _CMD_SPLIT.split(text, maxsplit=1)
        when_raw = when_part.strip()
        then_raw = then_part.strip()
    else:
        match = _WHEN_ACTION_RE.match(text)
        if not match:
            return ParsedRule(name=_slugify(text[:40]) or "rule", triggers=[], actions=[])
        when_raw, verb, rest = match.group(1).strip(), match.group(2), match.group(3).strip()
        then_raw = f"{verb} {rest}"
    if when_raw.lower().startswith("when "):
        when_raw = when_raw[5:].strip()
    name = _slugify(when_raw) or "rule"
    return parse_rule(name, when_raw, then_raw, raw=command)
