import pytest
from aiosqlite import IntegrityError

from aware.app.rules.store import RulesStore


async def test_add_and_get_active(store: RulesStore) -> None:
    await store.add(
        name="test_rule",
        when_text="person detected",
        then_text="say hello",
        priority="normal",
        triggers=[{"type": "detection", "value": "person"}],
        actions=[{"type": "speak", "params": {"text": "hello"}}],
    )
    rules = await store.get_active()
    assert len(rules) == 1
    assert rules[0]["name"] == "test_rule"


async def test_deactivate(store: RulesStore) -> None:
    await store.add("r1", "a", "b", "normal", [], [])
    await store.deactivate("r1")
    rules = await store.get_active()
    assert len(rules) == 0


async def test_unique_name_constraint(store: RulesStore) -> None:
    await store.add("dup", "a", "b", "normal", [], [])
    with pytest.raises(IntegrityError):
        await store.add("dup", "c", "d", "normal", [], [])
