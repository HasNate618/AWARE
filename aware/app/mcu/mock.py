from __future__ import annotations

import logging
import random
import time

from aware.app.mcu.bus import SensorReading

logger = logging.getLogger(__name__)


class MockSensorBus:
    """Simulated sensor bus for local testing."""

    def __init__(self) -> None:
        self._sensors = {
            "motion": 0.0,
            "distance_cm": 100.0,
            "temperature_c": 22.0,
            "light": 500.0,
            "vibration": 0.0,
        }

    async def read_all(self) -> list[SensorReading]:
        now = time.time()
        return [
            SensorReading(sensor=k, value=self._jitter(v), timestamp=now)
            for k, v in self._sensors.items()
        ]

    async def read_sensor(self, name: str) -> SensorReading | None:
        if name not in self._sensors:
            return None
        return SensorReading(
            sensor=name,
            value=self._jitter(self._sensors[name]),
            timestamp=time.time(),
        )

    def _jitter(self, base: float) -> float:
        return round(base + random.uniform(-base * 0.05, base * 0.05), 2)


class MockActuatorBus:
    """Simulated actuator bus for local testing."""

    def __init__(self) -> None:
        self.leds: list[tuple[int, int, int, int]] = []
        self.tones: list[tuple[int, int]] = []
        self.relays: dict[int, bool] = {}

    async def set_led(self, index: int, r: int, g: int, b: int, brightness: int = 255) -> None:
        self.leds.append((r, g, b, brightness))
        logger.debug("LED %d -> (%d,%d,%d) @%d", index, r, g, b, brightness)

    async def set_rgb(self, r: int, g: int, b: int) -> None:
        logger.debug("RGB -> (%d,%d,%d)", r, g, b)

    async def play_tone(self, frequency: int, duration_ms: int) -> None:
        self.tones.append((frequency, duration_ms))
        logger.debug("Tone %dHz for %dms", frequency, duration_ms)

    async def set_relay(self, index: int, state: bool) -> None:
        self.relays[index] = state
        logger.debug("Relay %d -> %s", index, state)
