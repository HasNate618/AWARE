"""End-to-end integration test: command -> LLM -> parser -> rules -> evaluate -> action."""
from __future__ import annotations

from typing import Any

import pytest

from aware.app.core.event_bus import EventBus
from aware.app.llm.stub import StubLLM
from aware.app.memory.db import EventDB
from aware.app.parser.nl_parser import parse_rule
from aware.app.perception.interface import Detection, PerceptionSnapshot
from aware.app.rules.engine import RulesEngine
from aware.app.rules.store import RulesStore


@pytest.fixture
async def db() -> EventDB:
    d = EventDB(":memory:")
    await d.open()
    yield d
    await d.close()


@pytest.fixture
async def store() -> RulesStore:
    s = RulesStore(":memory:")
    await s.open()
    yield s
    await s.close()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


async def test_stub_llm_parses_command() -> None:
    llm = StubLLM()
    spec = await llm.create_rule("When someone walks in, say welcome and flash green")
    assert "someone" in spec.when.lower()
    assert "welcome" in spec.then.lower()
    assert spec.name


async def test_parser_compiles_triggers_and_actions() -> None:
    parsed = parse_rule("greet", "when someone walks in", "say welcome and flash green")
    assert len(parsed.triggers) > 0
    assert len(parsed.actions) > 0
    assert any(t.type == "detection" and t.value == "person" for t in parsed.triggers)
    action_types = {a.type for a in parsed.actions}
    assert "speak" in action_types
    assert "led_flash" in action_types


async def test_rules_store_persists_rule(store: RulesStore) -> None:
    await store.add(
        name="test_greet",
        when_text="person walks in",
        then_text="say welcome",
        priority="normal",
        triggers=[{"type": "detection", "value": "person"}],
        actions=[{"type": "speak", "params": {"text": "welcome"}}],
    )
    rules = await store.get_active()
    assert len(rules) == 1
    assert rules[0]["name"] == "test_greet"


async def test_rules_engine_matches_detection(
    bus: EventBus, store: RulesStore, db: EventDB
) -> None:
    await store.add(
        name="person_greet",
        when_text="person detected",
        then_text="say welcome",
        priority="normal",
        triggers=[{"type": "detection", "value": "person"}],
        actions=[{"type": "speak", "params": {"text": "welcome"}}],
    )

    engine = RulesEngine(store, bus, db)
    await engine.start()

    actions_received: list[dict[str, Any]] = []

    async def capture_action(event: dict[str, Any]) -> None:
        actions_received.append(event)

    bus.subscribe("action", capture_action)

    snapshot = PerceptionSnapshot(
        detections=[Detection(label="person", confidence=0.95)],
        sounds=[],
        source="test",
        timestamp=1234567890.0,
    )
    await bus.publish("perception", {"snapshot": snapshot})
    await engine.evaluate()

    assert len(actions_received) == 1
    assert actions_received[0]["rule"] == "person_greet"
    assert actions_received[0]["action"] == "speak"

    await engine.stop()


async def test_rules_engine_ignores_non_matching(
    bus: EventBus, store: RulesStore, db: EventDB
) -> None:
    await store.add(
        name="doorbell_alert",
        when_text="doorbell",
        then_text="say hello",
        priority="normal",
        triggers=[{"type": "sound", "value": "doorbell"}],
        actions=[{"type": "speak", "params": {"text": "hello"}}],
    )

    engine = RulesEngine(store, bus, db)
    await engine.start()

    actions_received: list[dict[str, Any]] = []

    async def capture_action(event: dict[str, Any]) -> None:
        actions_received.append(event)

    bus.subscribe("action", capture_action)

    snapshot = PerceptionSnapshot(
        detections=[Detection(label="person", confidence=0.9)],
        sounds=[],
        source="test",
        timestamp=1234567890.0,
    )
    await bus.publish("perception", {"snapshot": snapshot})
    await engine.evaluate()

    assert len(actions_received) == 0

    await engine.stop()


async def test_full_flow_e2e() -> None:
    """Full pipeline: LLM -> parser -> store -> evaluate -> action."""
    llm = StubLLM()
    db = EventDB(":memory:")
    store = RulesStore(":memory:")
    bus = EventBus()

    await db.open()
    await store.open()

    spec = await llm.create_rule("When doorbell rings, say welcome home")
    assert "doorbell" in spec.when.lower()

    parsed = parse_rule(spec.name, spec.when, spec.then, spec.priority)
    assert any(t.type == "sound" and t.value == "doorbell" for t in parsed.triggers)

    triggers_dicts = [
        {
            "type": t.type,
            "value": t.value,
            "time_range": list(t.time_range) if t.time_range else None,
        }
        for t in parsed.triggers
    ]
    actions_dicts = [{"type": a.type, "params": a.params} for a in parsed.actions]
    await store.add(
        name=parsed.name,
        when_text=spec.when,
        then_text=spec.then,
        priority=parsed.priority,
        triggers=triggers_dicts,
        actions=actions_dicts,
    )

    engine = RulesEngine(store, bus, db)
    await engine.start()

    actions_received: list[dict[str, Any]] = []

    async def capture_action(event: dict[str, Any]) -> None:
        actions_received.append(event)

    bus.subscribe("action", capture_action)

    snapshot = PerceptionSnapshot(
        detections=[],
        sounds=[Detection(label="doorbell", confidence=0.92)],
        source="test",
        timestamp=1234567890.0,
    )
    await bus.publish("perception", {"snapshot": snapshot})
    await engine.evaluate()

    assert len(actions_received) == 1
    assert actions_received[0]["action"] == "speak"

    events = await db.query(topic="action_executed")
    assert len(events) == 1

    await engine.stop()
    await store.close()
    await db.close()
