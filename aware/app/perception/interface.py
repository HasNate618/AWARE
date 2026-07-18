from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class Detection:
    label: str
    confidence: float
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class PerceptionSnapshot:
    detections: list[Detection] = field(default_factory=list)
    sounds: list[Detection] = field(default_factory=list)
    entered: list[str] = field(default_factory=list)
    exited: list[str] = field(default_factory=list)
    sensors: dict[str, float] = field(default_factory=dict)
    source: str = "unknown"
    timestamp: float = 0.0


@dataclass
class SensorCache:
    """Holds latest sensor readings, written by sensor_loop, read by perception_loop."""
    readings: dict[str, float] = field(default_factory=dict)

    def update(self, sensors: dict[str, float]) -> None:
        self.readings.update(sensors)


@runtime_checkable
class PerceptionSource(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def snapshot(self) -> PerceptionSnapshot: ...
