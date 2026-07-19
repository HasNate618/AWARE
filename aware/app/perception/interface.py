from __future__ import annotations

import time
from collections import deque
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
class SensorSample:
    timestamp: float
    value: float


@dataclass
class SensorCache:
    """Holds latest sensor readings and a short rolling history for live charts."""

    readings: dict[str, float] = field(default_factory=dict)
    history_maxlen: int = 150
    _history: dict[str, deque[SensorSample]] = field(default_factory=dict)

    def update(self, sensors: dict[str, float]) -> None:
        now = time.time()
        self.readings.update(sensors)
        for name, value in sensors.items():
            if name not in self._history:
                self._history[name] = deque(maxlen=self.history_maxlen)
            self._history[name].append(SensorSample(timestamp=now, value=value))

    def get_history(self, sensor: str, window_seconds: float = 300.0) -> list[dict[str, float]]:
        cutoff = time.time() - window_seconds
        samples = self._history.get(sensor, deque())
        return [
            {"timestamp": sample.timestamp, "value": sample.value}
            for sample in samples
            if sample.timestamp >= cutoff
        ]


@runtime_checkable
class PerceptionSource(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def snapshot(self) -> PerceptionSnapshot: ...
