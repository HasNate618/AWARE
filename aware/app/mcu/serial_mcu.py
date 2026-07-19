from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import msgpack

from aware.app.mcu.bus import SensorReading

logger = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = "/var/run/arduino-router.sock"
RPC_TIMEOUT = 3.0

SENSOR_DEFAULTS: dict[str, float] = {
    "temperature_c": 22.0,
    "distance_cm": 100.0,
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
    filtered = [r for r in readings if r.sensor not in ("motion", "movement_intensity")]
    by_name = {r.sensor: r.value for r in readings}
    ax = by_name.get("accel_x")
    ay = by_name.get("accel_y")
    az = by_name.get("accel_z")
    if ax is not None and ay is not None and az is not None:
        import math

        intensity = max(0.0, math.sqrt(ax * ax + ay * ay + az * az) - 1.0)
        filtered.append(
            SensorReading(
                sensor="movement_intensity",
                value=round(intensity, 4),
                timestamp=now,
            )
        )
    else:
        intensity = _derive_movement_intensity(readings)
        if intensity is not None:
            filtered.append(
                SensorReading(sensor="movement_intensity", value=float(intensity), timestamp=now)
            )
    return filtered


def _pack_msg(msg: list[object]) -> bytes:
    """Encode a msgpack-rpc message for the arduino-router Unix socket."""
    return msgpack.packb(msg)


def _unpack_msg(data: bytes) -> object:
    return msgpack.unpackb(data, strict_map_key=False)


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
        self._rpc_lock = asyncio.Lock()
        self.using_mock = False

    async def connect(self, retries: int = 10, delay: float = 1.0) -> bool:
        import socket as _socket

        for attempt in range(retries):
            try:
                if self._sock:
                    self._sock.close()
                    self._sock = None
                s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
                s.connect(self.socket_path)
                s.setblocking(False)
                self._sock = s
                self._connected = True
                logger.info("Router MCU on %s", self.socket_path)
                return True
            except Exception:
                self._connected = False
                if attempt < retries - 1:
                    logger.debug(
                        "Router connect attempt %d/%d failed, retrying in %.0fs",
                        attempt + 1,
                        retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.exception("Router connect failed on %s", self.socket_path)
        return False

    async def ensure_connected(self) -> bool:
        if self._connected:
            return True
        return await self.connect(retries=3, delay=0.5)

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
        async with self._rpc_lock:
            self._msgid += 1
            msgid = self._msgid
            req = [0, msgid, method, list(args)]
            loop = asyncio.get_running_loop()
            deadline = loop.time() + RPC_TIMEOUT
            try:
                await loop.sock_sendall(self._sock, _pack_msg(req))
                unpacker = msgpack.Unpacker(strict_map_key=False)
                while loop.time() < deadline:
                    try:
                        resp = next(unpacker)
                    except StopIteration:
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            break
                        try:
                            chunk = await asyncio.wait_for(
                                loop.sock_recv(self._sock, 4096),
                                timeout=remaining,
                            )
                        except TimeoutError:
                            break
                        if not chunk:
                            logger.warning("RPC %s: router closed connection", method)
                            self._connected = False
                            return None
                        unpacker.feed(chunk)
                        continue
                    if not isinstance(resp, list) or len(resp) < 2:
                        continue
                    if resp[0] != 1:
                        continue
                    if resp[1] != msgid:
                        continue
                    if len(resp) < 4:
                        return None
                    error: object = resp[2]
                    result: object = resp[3]
                    if error is not None:
                        logger.warning("RPC %s error: %s", method, error)
                        return None
                    return result
                logger.warning("RPC %s timed out after %.1fs", method, RPC_TIMEOUT)
                return None
            except Exception:
                logger.warning("RPC call %s failed", method, exc_info=True)
                return None

    async def read_all(self) -> list[SensorReading]:
        if not self._connected:
            await self.ensure_connected()
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
        for axis in axes:
            val = await self._rpc_call(axis)
            if isinstance(val, (int, float)):
                readings.append(SensorReading(sensor=axis, value=float(val), timestamp=now))

        if readings:
            self.using_mock = False
            return _normalize_readings(readings)
        self.using_mock = True
        if self._connected:
            logger.warning("MCU connected but all sensor RPCs failed — using mock fallback")
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
        import math
        import random

        now = time.time()
        ax = random.uniform(-0.08, 0.08)
        ay = random.uniform(-0.08, 0.08)
        az = 1.0 + random.uniform(-0.05, 0.05)
        intensity = max(0.0, math.sqrt(ax * ax + ay * ay + az * az) - 1.0)
        return [
            SensorReading(
                sensor="temperature_c",
                value=round(self._values["temperature_c"] + random.uniform(-0.2, 0.2), 2),
                timestamp=now,
            ),
            SensorReading(
                sensor="distance_cm",
                value=round(self._values["distance_cm"] + random.uniform(-3, 3), 1),
                timestamp=now,
            ),
            SensorReading(sensor="accel_x", value=round(ax, 4), timestamp=now),
            SensorReading(sensor="accel_y", value=round(ay, 4), timestamp=now),
            SensorReading(sensor="accel_z", value=round(az, 4), timestamp=now),
            SensorReading(
                sensor="movement_intensity",
                value=round(intensity, 4),
                timestamp=now,
            ),
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
