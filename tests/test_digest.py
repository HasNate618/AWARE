from aware.app.memory.digest import PeriodDigest, build_digest, digest_to_json, digest_to_text


def _event(ts: float, topic: str, data: dict[str, object]) -> dict[str, object]:
    return {"id": 1, "timestamp": ts, "topic": topic, "data": data}


def test_build_digest_mixed_events() -> None:
    events = [
        _event(100.0, "detection_enter", {"label": "person", "confidence": 0.9}),
        _event(110.0, "sound", {"label": "doorbell", "confidence": 0.8}),
        _event(
            120.0,
            "action_executed",
            {
                "rule": "greet",
                "action": "speak",
                "detection_label": "person",
                "message": "Rule greet triggered",
            },
        ),
        _event(130.0, "sensor:temperature_c", {"value": 22.0}),
        _event(140.0, "sensor:temperature_c", {"value": 23.5}),
    ]
    digest = build_digest(events)
    assert digest is not None
    assert digest.detections_entered["person"] == 1
    assert digest.sounds["doorbell"] == 1
    assert len(digest.actions) == 1
    assert digest.sensors["temperature_c"]["min"] == 22.0
    assert digest.sensors["temperature_c"]["last"] == 23.5


def test_build_digest_dedupes_actions() -> None:
    events = [
        _event(100.0, "action_executed", {"rule": "a", "action": "speak"}),
        _event(100.0, "action_executed", {"rule": "a", "action": "speak"}),
    ]
    digest = build_digest(events)
    assert digest is not None
    assert len(digest.actions) == 1


def test_build_digest_empty() -> None:
    assert build_digest([]) is None


def test_digest_to_text() -> None:
    digest = PeriodDigest(
        period_start=100.0,
        period_end=200.0,
        detections_entered={"person": 1},
        sounds={"doorbell": 1},
    )
    text = digest_to_text(digest)
    assert "person×1" in text
    assert "doorbell×1" in text


def test_digest_json_roundtrip() -> None:
    digest = PeriodDigest(period_start=1.0, period_end=2.0, sounds={"knock": 2})
    raw = digest_to_json(digest)
    assert "knock" in raw
