from __future__ import annotations

import time

from aware.app.mcu.bus import SensorReading
from aware.app.mcu.serial_mcu import _derive_movement_intensity, _normalize_readings


def test_derive_from_motion() -> None:
    readings = [SensorReading(sensor="motion", value=0.42, timestamp=time.time())]
    assert _derive_movement_intensity(readings) == 0.42


def test_derive_from_accel() -> None:
    now = time.time()
    readings = [
        SensorReading(sensor="accel_x", value=0.0, timestamp=now),
        SensorReading(sensor="accel_y", value=0.0, timestamp=now),
        SensorReading(sensor="accel_z", value=1.2, timestamp=now),
    ]
    assert abs(_derive_movement_intensity(readings) - 0.2) < 0.01


def test_normalize_drops_motion_and_adds_movement_intensity() -> None:
    now = time.time()
    readings = [
        SensorReading(sensor="temperature_c", value=22.0, timestamp=now),
        SensorReading(sensor="motion", value=0.15, timestamp=now),
    ]
    normalized = _normalize_readings(readings)
    sensors = {r.sensor for r in normalized}
    assert "motion" not in sensors
    assert "movement_intensity" in sensors
    assert next(r for r in normalized if r.sensor == "movement_intensity").value == 0.15
