from __future__ import annotations

SENSOR_THRESHOLDS: dict[str, float] = {
    "temperature_c": 0.5,
    "distance_cm": 5.0,
    "movement_intensity": 0.1,
    "accel_x": 0.2,
    "accel_y": 0.2,
    "accel_z": 0.2,
}


def should_log_sensor(
    name: str,
    value: float,
    now: float,
    last_logged: dict[str, tuple[float, float]],
    log_interval: float,
) -> bool:
    """Return True if this sensor reading should be persisted to the event log."""
    last_val, last_ts = last_logged.get(name, (value, 0.0))
    if now - last_ts >= log_interval:
        return True
    threshold = SENSOR_THRESHOLDS.get(name, 0.0)
    return abs(value - last_val) >= threshold


def should_log_chart(
    name: str,
    now: float,
    last_chart: dict[str, float],
    chart_interval: float,
) -> bool:
    """Return True if this sensor reading should be logged for dashboard charts."""
    return now - last_chart.get(name, 0.0) >= chart_interval
