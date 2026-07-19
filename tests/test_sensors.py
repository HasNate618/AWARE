from aware.app.memory.sensors import should_log_chart, should_log_sensor


def test_should_log_on_interval() -> None:
    last: dict[str, tuple[float, float]] = {"temperature_c": (22.0, 100.0)}
    assert should_log_sensor("temperature_c", 22.1, 131.0, last, log_interval=30.0)


def test_should_not_log_small_delta() -> None:
    last: dict[str, tuple[float, float]] = {"temperature_c": (22.0, 100.0)}
    assert not should_log_sensor("temperature_c", 22.2, 110.0, last, log_interval=30.0)


def test_should_log_large_delta() -> None:
    last: dict[str, tuple[float, float]] = {"temperature_c": (22.0, 100.0)}
    assert should_log_sensor("temperature_c", 23.0, 110.0, last, log_interval=30.0)


def test_should_log_chart_on_interval() -> None:
    last_chart: dict[str, float] = {"distance_cm": 100.0}
    assert should_log_chart("distance_cm", 111.0, last_chart, chart_interval=10.0)
    assert not should_log_chart("distance_cm", 105.0, last_chart, chart_interval=10.0)
