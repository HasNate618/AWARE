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


def parse_when(text: str) -> list[Trigger]:
    triggers: list[Trigger] = []
    lower = text.lower()
    # Split on " and " / " & " for compound conditions
    parts = [p.strip() for p in lower.replace(" & ", " and ").split(" and ")]
    search_text = " ".join(parts)
    for keyword, label in vocab.SOUNDS.items():
        if keyword in search_text:
            triggers.append(Trigger(type="sound", value=label))
    for keyword, label in vocab.OBJECTS.items():
        if keyword in search_text:
            triggers.append(Trigger(type="detection", value=label))
    for keyword, (start, end) in vocab.TIMES.items():
        if keyword in search_text:
            triggers.append(Trigger(type="time", value=keyword, time_range=(start, end)))
    match = vocab.TIME_RE.search(text)
    if match:
        hour = int(match.group(1))
        ampm = match.group(2).lower()
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
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


def parse_rule(name: str, when: str, then: str, priority: str = "normal") -> ParsedRule:
    return ParsedRule(
        name=name,
        triggers=parse_when(when),
        actions=parse_then(then),
        priority=priority,
    )
