from __future__ import annotations

import time

from aware.app.perception.interface import SensorCache


def test_sensor_cache_history() -> None:
    cache = SensorCache(history_maxlen=5)
    now = time.time()
    cache.update({"temperature_c": 21.0})
    cache.update({"temperature_c": 21.5})
    history = cache.get_history("temperature_c", window_seconds=60)
    assert len(history) == 2
    assert history[-1]["value"] == 21.5
    assert history[-1]["timestamp"] >= now
