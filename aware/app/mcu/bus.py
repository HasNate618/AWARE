from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class SensorReading:
    sensor: str
    value: float
    unit: str = ""
    timestamp: float = 0.0


@runtime_checkable
class SensorBus(Protocol):
    async def read_all(self) -> list[SensorReading]: ...

    async def read_sensor(self, name: str) -> SensorReading | None: ...


@runtime_checkable
class ActuatorBus(Protocol):
    async def set_led(self, index: int, r: int, g: int, b: int, brightness: int = 255) -> None: ...

    async def play_tone(self, frequency: int, duration_ms: int) -> None: ...

    async def set_relay(self, index: int, state: bool) -> None: ...
