from __future__ import annotations

import json
import logging
import time
from typing import Any

from aware.app.mcu.bus import SensorReading

logger = logging.getLogger(__name__)

DEFAULT_BAUD = 115200
DEFAULT_TIMEOUT = 0.1
RECONNECT_DELAY = 2.0


class SerialMCU:
    """Real MCU bus — reads Modulinos via /dev/ttyACMx serial protocol."""

    def __init__(self, port: str = "/dev/ttyACM0", baud: int = DEFAULT_BAUD) -> None:
        self.port = port
        self.baud = baud
        self._serial: Any = None
        self._connected = False

    async def connect(self) -> None:
        try:
            import serial  # type: ignore[import-untyped]

            self._serial = serial.Serial(self.port, self.baud, timeout=DEFAULT_TIMEOUT)
            self._connected = True
            logger.info("MCU connected on %s @ %d", self.port, self.baud)
        except ImportError:
            logger.warning("pyserial not installed — MCU unavailable")
            self._connected = False
        except Exception:
            logger.exception("MCU connect failed on %s", self.port)
            self._connected = False

    async def disconnect(self) -> None:
        if self._serial:
            self._serial.close()
            self._serial = None
        self._connected = False
        logger.info("MCU disconnected")

    async def _send_command(self, cmd: str) -> str | None:
        if not self._connected or not self._serial:
            return None
        try:
            self._serial.write((cmd + "\n").encode())
            line = self._serial.readline().decode().strip()
            return line if line else None
        except Exception:
            logger.exception("MCU serial read error")
            self._connected = False
            return None

    async def _read_json(self, cmd: str) -> dict[str, object] | None:
        raw = await self._send_command(cmd)
        if not raw:
            return None
        try:
            result: dict[str, object] = json.loads(raw)
            return result
        except json.JSONDecodeError:
            logger.warning("MCU bad JSON: %s", raw[:100])
            return None

    async def read_all(self) -> list[SensorReading]:
        data = await self._read_json("READ_ALL")
        if not data:
            return []
        now = time.time()
        readings: list[SensorReading] = []
        for name, val in data.items():
            if isinstance(val, (int, float)):
                readings.append(SensorReading(sensor=name, value=float(val), timestamp=now))
        return readings

    async def read_sensor(self, name: str) -> SensorReading | None:
        data = await self._read_json(f"READ:{name}")
        if not data or name not in data:
            return None
        val = data[name]
        if isinstance(val, (int, float)):
            return SensorReading(sensor=name, value=float(val), timestamp=time.time())
        return None

    async def set_led(self, index: int, r: int, g: int, b: int, brightness: int = 255) -> None:
        await self._send_command(f"LED:{index}:{r}:{g}:{b}:{brightness}")

    async def play_tone(self, frequency: int, duration_ms: int) -> None:
        await self._send_command(f"TONE:{frequency}:{duration_ms}")

    async def set_relay(self, index: int, state: bool) -> None:
        await self._send_command(f"RELAY:{index}:{1 if state else 0}")
