from __future__ import annotations

import re
from typing import Final

OBJECTS: Final[dict[str, str]] = {
    "person": "person",
    "someone": "person",
    "people": "person",
    "visitor": "person",
    "intruder": "person",
    "man": "person",
    "woman": "person",
    "cat": "cat",
    "dog": "dog",
    "car": "car",
    "vehicle": "car",
    "truck": "car",
    "bus": "car",
    "package": "package",
    "box": "package",
    "backpack": "package",
    "bicycle": "bicycle",
    "bike": "bicycle",
    "laptop": "laptop",
    "computer": "laptop",
    "keyboard": "keyboard",
    "phone": "phone",
    "cell phone": "phone",
    "tv": "tv",
    "television": "tv",
    "chair": "chair",
    "bottle": "bottle",
    "cup": "cup",
    "book": "book",
}

SOUNDS: Final[dict[str, str]] = {
    "doorbell": "doorbell",
    "door bell": "doorbell",
    "knock": "knock",
    "knocking": "knock",
    "glass break": "glass_break",
    "glass breaks": "glass_break",
    "glass breaking": "glass_break",
    "breaking glass": "glass_break",
    "voice": "voice",
    "speech": "voice",
    "talking": "voice",
    "music": "music",
    "dog bark": "dog_bark",
    "barking": "dog_bark",
    "alarm": "alarm",
    "siren": "siren",
    "baby cry": "baby_cry",
    "crying": "baby_cry",
}

TIMES: Final[dict[str, tuple[int, int]]] = {
    "morning": (6, 12),
    "afternoon": (12, 17),
    "evening": (17, 21),
    "night": (21, 6),
    "after 10pm": (22, 24),
    "after 10 pm": (22, 24),
    "before 6am": (0, 6),
    "before 6 am": (0, 6),
    "after midnight": (0, 6),
}

ACTIONS: Final[dict[str, dict[str, str]]] = {
    "say": {"type": "speak", "param": "text"},
    "speak": {"type": "speak", "param": "text"},
    "announce": {"type": "speak", "param": "text"},
    "play": {"type": "speak", "param": "text"},
    "flash": {"type": "led_flash", "param": "color"},
    "turn on": {"type": "led_on", "param": "color"},
    "turn off": {"type": "led_off", "param": ""},
    "notify": {"type": "telegram", "param": "text"},
    "send telegram": {"type": "telegram", "param": "text"},
    "alert": {"type": "telegram", "param": "text"},
    "sound alarm": {"type": "alarm", "param": ""},
    "alarm": {"type": "alarm", "param": ""},
    "beep": {"type": "tone", "param": ""},
    "chime": {"type": "tone", "param": ""},
    "tone": {"type": "tone", "param": ""},
    "log": {"type": "log", "param": ""},
    "record": {"type": "record", "param": ""},
}

TIME_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:after|before)\s+(\d{1,2})\s*(am|pm)",
    re.IGNORECASE,
)

COLORS: Final[dict[str, tuple[int, int, int]]] = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
}

TRANSITIONS: Final[dict[str, str]] = {
    "enters": "enter",
    "entered": "enter",
    "comes in": "enter",
    "walks in": "enter",
    "arrives": "enter",
    "leaves": "exit",
    "left": "exit",
    "exits": "exit",
    "exited": "exit",
    "goes out": "exit",
    "walks out": "exit",
    "departs": "exit",
}

# Sensor conditions: keyword -> (sensor_key, operator, default_threshold)
# Operators: "lt" (less than), "gt" (greater than)
SENSOR_CONDITIONS: Final[dict[str, tuple[str, str, float]]] = {
    "within": ("distance_cm", "lt", 100),
    "closer than": ("distance_cm", "lt", 50),
    "near": ("distance_cm", "lt", 100),
    "farther than": ("distance_cm", "gt", 200),
    "further than": ("distance_cm", "gt", 200),
    "far": ("distance_cm", "gt", 200),
    "hot": ("temperature_c", "gt", 30),
    "warm": ("temperature_c", "gt", 25),
    "cold": ("temperature_c", "lt", 10),
    "chilly": ("temperature_c", "lt", 15),
    "moving": ("movement_intensity", "gt", 0.3),
    "motion": ("movement_intensity", "gt", 0.3),
    "still": ("movement_intensity", "lt", 0.05),
}

_DISTANCE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:within|closer than|farther than|further than)\s+(\d+)\s*(cm|m|mm)",
    re.IGNORECASE,
)
