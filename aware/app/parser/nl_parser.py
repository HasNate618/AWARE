from __future__ import annotations

import logging
from dataclasses import dataclass, field

from aware.app.parser import vocabulary as vocab

logger = logging.getLogger(__name__)


@dataclass
class Trigger:
    type: str
    value: str
    time_range: tuple[int, int] | None = None
    transition: str | None = None  # "enter", "exit", or None for any presence


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
    seen: set[tuple[str, str, str]] = set()
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
                key = ("sound", label, "")
                if key not in seen:
                    triggers.append(Trigger(type="sound", value=label))
                    seen.add(key)
        # Find objects in this part (with optional transition)
        for keyword, label in vocab.OBJECTS.items():
            if keyword in part_lower:
                key = ("detection", label, trans or "")
                if key not in seen:
                    triggers.append(Trigger(type="detection", value=label, transition=trans))
                    seen.add(key)
        # Find times in this part
        for keyword, (start, end) in vocab.TIMES.items():
            if keyword in part_lower:
                key = ("time", keyword, "")
                if key not in seen:
                    triggers.append(Trigger(type="time", value=keyword, time_range=(start, end)))
                    seen.add(key)
    # Also check full text for absolute time patterns
    match = vocab.TIME_RE.search(text)
    if match:
        hour = int(match.group(1))
        ampm = match.group(2).lower()
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        key = ("time", f"after {hour}:00", "")
        if key not in seen:
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
