from aware.app.memory.witness import (
    WITNESS_SOUND_LABELS,
    build_witness_log,
    is_ai_narrative,
    summaries_for_witness_display,
    witness_log_to_text,
)


def _event(ts: float, topic: str, data: dict[str, object]) -> dict[str, object]:
    return {"id": 1, "timestamp": ts, "topic": topic, "data": data}


def test_witness_log_person_and_sound() -> None:
    events = [
        _event(100.0, "detection_enter", {"label": "person", "confidence": 0.9}),
        _event(101.0, "detection_enter", {"label": "train", "confidence": 0.8}),
        _event(102.0, "sound", {"label": "speech", "confidence": 0.7}),
        _event(103.0, "sound", {"label": "Animal", "confidence": 0.4}),
    ]
    log = build_witness_log(events)
    assert len(log) == 2
    assert "person entered" in log[0].line
    assert "speech heard" in log[1].line


def test_witness_log_sensor_change_only() -> None:
    events = [
        _event(100.0, "sensor:temperature_c", {"value": 22.0}),
        _event(110.0, "sensor:temperature_c", {"value": 22.2}),
        _event(120.0, "sensor:temperature_c", {"value": 23.0}),
        _event(130.0, "sensor:distance_cm", {"value": 30.0}),
        _event(140.0, "sensor:distance_cm", {"value": 32.0}),
        _event(150.0, "sensor:distance_cm", {"value": 10.0}),
    ]
    log = build_witness_log(events)
    kinds = [e.kind for e in log]
    assert kinds == ["sensor", "sensor"]
    assert "temperature" in log[0].line
    assert "distance" in log[1].line
    assert "10.0cm" in log[1].line


def test_witness_log_to_text_caps_lines() -> None:
    events = [
        _event(float(i), "detection_enter", {"label": "person"})
        for i in range(60)
    ]
    log = build_witness_log(events)
    text = witness_log_to_text(log, max_lines=5)
    assert text.count("\n") == 4


def test_witness_sound_labels_cover_venue_map() -> None:
    assert "speech" in WITNESS_SOUND_LABELS
    assert "doorbell" in WITNESS_SOUND_LABELS


def test_is_ai_narrative_rejects_digest() -> None:
    assert not is_ai_narrative("04:20–04:31 | entered: person×7, train×79 | accel_x 0.0→0.0")
    assert not is_ai_narrative("12:34:56 person entered frame\n12:35:01 speech heard")
    assert is_ai_narrative("Two people passed by the booth and speech was heard.")


def test_is_ai_narrative_rejects_llm_junk() -> None:
    junk = (
        "The log contains entries of 1-2 short sentences. "
        "Conclusion: The analysis of the speech samples is complete."
    )
    assert not is_ai_narrative(junk)
    assert not is_ai_narrative("Next Question: What is the purpose of this activity log?")
    assert not is_ai_narrative("Task 2: Create a table with the following columns: Name, Age")


def test_witness_events_for_display() -> None:
    from aware.app.memory.witness import witness_events_for_display

    events = [
        _event(100.0, "detection_enter", {"label": "person"}),
        _event(200.0, "sound", {"label": "speech"}),
    ]
    log = build_witness_log(events)
    rows = witness_events_for_display(log)
    assert len(rows) == 2
    assert rows[0]["kind"] == "person"
    assert rows[0]["text"] == "person entered frame"
    assert rows[1]["text"] == "speech heard"


def test_summaries_for_witness_display_filters_noise() -> None:
    rows = [
        {
            "period_start": 100.0,
            "period_end": 200.0,
            "narrative": "04:20 | entered: person×3 | accel_x 0.0→0.0",
        },
        {
            "period_start": 200.0,
            "period_end": 300.0,
            "narrative": "A person entered and speech was heard near the booth.",
        },
    ]
    logs = summaries_for_witness_display(rows)
    assert len(logs) == 1
    assert "–" in str(logs[0]["period_label"])
    assert "person entered" in str(logs[0]["text"])
