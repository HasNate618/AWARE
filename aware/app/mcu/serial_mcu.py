from __future__ import annotations

import asyncio
import logging
import struct
import time
from typing import Any

import msgpack

from aware.app.mcu.bus import SensorReading

logger = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = "/var/run/arduino-router.sock"
RPC_TIMEOUT = 1.0

SENSOR_DEFAULTS: dict[str, float] = {
    "temperature_c": 22.0,
    "distance_cm": 100.0,
    "movement_intensity": 0.05,
    "light": 500.0,
    "vibration": 0.0,
}


def _derive_movement_intensity(readings: list[SensorReading]) -> float | None:
    """Compute movement intensity from legacy motion or accelerometer axes."""
    by_name = {r.sensor: r.value for r in readings}
    if "movement_intensity" in by_name:
        return by_name["movement_intensity"]
    if "motion" in by_name:
        return by_name["motion"]
    ax = by_name.get("accel_x")
    ay = by_name.get("accel_y")
    az = by_name.get("accel_z")
    if ax is not None and ay is not None and az is not None:
        import math

        return max(0.0, math.sqrt(ax * ax + ay * ay + az * az) - 1.0)
    return None


def _normalize_readings(readings: list[SensorReading]) -> list[SensorReading]:
    """Ensure movement_intensity is present and drop legacy motion key."""
    now = readings[0].timestamp if readings else time.time()
    intensity = _derive_movement_intensity(readings)
    filtered = [r for r in readings if r.sensor != "motion"]
    if intensity is not None and not any(r.sensor == "movement_intensity" for r in filtered):
        filtered.append(
            SensorReading(sensor="movement_intensity", value=float(intensity), timestamp=now)
        )
    return filtered


def _pack_msg(msg: list[object]) -> bytes:
    body: bytes = msgpack.packb(msg)
    return struct.pack(">I", len(body)) + body


def _unpack_msg(data: bytes) -> object:
    return msgpack.unpackb(data)


class SerialMCU:
    """MCU bus over arduino-router msgpack-rpc protocol.

    Connects to arduino-router via Unix socket and makes RPC calls to the
    STM32U585. Falls back to mock data when the STM32 hasn't registered the
    requested method.
    """

    def __init__(
        self,
        port: str = "/dev/ttyACM0",
        baud: int = 115200,
        socket_path: str = DEFAULT_SOCKET_PATH,
    ) -> None:
        self.port = port
        self.baud = baud
        self.socket_path = socket_path
        self._sock: Any = None
        self._msgid = 0
        self._connected = False
        self._mock = _MockProvider()

    async def connect(self) -> None:
        import socket as _socket

        try:
            s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            s.settimeout(RPC_TIMEOUT)
            s.connect(self.socket_path)
            self._sock = s
            self._connected = True
            logger.info("Router MCU on %s", self.socket_path)
        except Exception:
            logger.exception("Router connect failed on %s", self.socket_path)
            self._connected = False

    async def disconnect(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None
        self._connected = False
        logger.info("Router MCU disconnected")

    async def _rpc_call(self, method: str, *args: object) -> object | None:
        """Send an RPC request and return the result, or None on error/timeout."""
        if not self._connected or not self._sock:
            return None
        self._msgid += 1
        req = [0, self._msgid, method, list(args)]
        loop = asyncio.get_running_loop()
        try:
            await loop.sock_sendall(self._sock, _pack_msg(req))
            header = await loop.sock_recv(self._sock, 4)
            if not header or len(header) < 4:
                return None
            (plen,) = struct.unpack(">I", header)
            data = await loop.sock_recv(self._sock, plen)
            resp: object = _unpack_msg(header + data)
            if isinstance(resp, list) and len(resp) >= 4:
                _type: object = resp[0]
                _msgid: object = resp[1]
                error: object = resp[2]
                result: object = resp[3]
                if error is not None:
                    return None
                return result
            return None
        except Exception:
            logger.debug("RPC call %s failed", method, exc_info=True)
            return None

    async def read_all(self) -> list[SensorReading]:
        now = time.time()
        readings: list[SensorReading] = []

        temp = await self._rpc_call("read_temp")
        if isinstance(temp, (int, float)) and temp > -200:
            readings.append(
                SensorReading(sensor="temperature_c", value=float(temp), timestamp=now)
            )

        dist_mm = await self._rpc_call("read_distance")
        if isinstance(dist_mm, (int, float)):
            readings.append(
                SensorReading(
                    sensor="distance_cm",
                    value=float(dist_mm) / 10.0,
                    timestamp=now,
                )
            )

        axes = ["accel_x", "accel_y", "accel_z"]
        tasks = [self._rpc_call(a) for a in axes]
        vals = await asyncio.gather(*tasks)
        for name, val in zip(axes, vals, strict=True):
            if isinstance(val, (int, float)):
                readings.append(
                    SensorReading(sensor=name, value=float(val), timestamp=now)
                )

        intensity = await self._rpc_call("movement_intensity")
        if isinstance(intensity, (int, float)):
            readings.append(
                SensorReading(sensor="movement_intensity", value=float(intensity), timestamp=now)
            )

        if readings:
            return _normalize_readings(readings)
        return _normalize_readings(self._mock.read_all())

    async def read_sensor(self, name: str) -> SensorReading | None:
        result = await self._rpc_call("read_sensor", name)
        if isinstance(result, (int, float)):
            return SensorReading(
                sensor=name, value=float(result), timestamp=time.time()
            )
        return self._mock.read_sensor(name)

    async def set_led(
        self, index: int, r: int, g: int, b: int, brightness: int = 255
    ) -> None:
        await self._rpc_call("set_led", index, r, g, b, brightness)

    async def set_rgb(self, r: int, g: int, b: int) -> None:
        await self._rpc_call("set_rgb", r, g, b)

    async def play_tone(self, frequency: int, duration_ms: int) -> None:
        await self._rpc_call("play_tone", frequency, duration_ms)

    async def set_relay(self, index: int, state: bool) -> None:
        await self._rpc_call("set_relay", index, state)


class _MockProvider:
    """Internal mock fallback that mimics real sensor behavior."""

    def __init__(self) -> None:
        self._values = dict(SENSOR_DEFAULTS)

    def read_all(self) -> list[SensorReading]:
        import random

        now = time.time()
        return [
            SensorReading(
                sensor=k,
                value=round(v + random.uniform(-v * 0.05, v * 0.05), 2),
                timestamp=now,
            )
            for k, v in self._values.items()
        ]

    def read_sensor(self, name: str) -> SensorReading | None:
        import random

        if name not in self._values:
            return None
        base = self._values[name]
        return SensorReading(
            sensor=name,
            value=round(base + random.uniform(-base * 0.05, base * 0.05), 2),
            timestamp=time.time(),
        )
