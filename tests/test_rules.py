from aware.app.memory.db import EventDB
from aware.app.rules.store import RulesStore


async def test_shared_connection_with_event_log(tmp_path) -> None:
    """Rules and events on the same file must share one SQLite connection."""
    db_path = tmp_path / "aware.db"
    db = EventDB(db_path)
    await db.open()
    store = RulesStore(db_path)
    await store.open(connection=db.connection, on_commit=db.note_external_commit)

    await db.log("detection_enter", {"label": "person", "confidence": 0.9})
    name = await store.add("person_rule", "person", "log event", "normal", [], [])
    assert name == "person_rule"

    rules = await store.get_active()
    assert len(rules) == 1
    deleted = await store.deactivate_by_id(int(rules[0]["id"]))
    assert deleted == "person_rule"

    await store.close()
    await db.close()


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


async def test_deactivate_by_id(store: RulesStore) -> None:
    await store.add("r2", "a", "b", "normal", [], [])
    rules = await store.get_active()
    rule_id = int(rules[0]["id"])
    name = await store.deactivate_by_id(rule_id)
    assert name == "r2"
    assert len(await store.get_active()) == 0


async def test_deactivate_missing_returns_false(store: RulesStore) -> None:
    assert await store.deactivate("no_such_rule") is False


async def test_unique_name_with_suffix(store: RulesStore) -> None:
    await store.add("dup", "a", "b", "normal", [], [])
    final = await store.add("dup", "c", "d", "normal", [], [])
    assert final != "dup"  # suffix appended
    assert final.startswith("dup_")
    rules = await store.get_active()
    assert len(rules) == 2
