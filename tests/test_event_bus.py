from aware.app.core.event_bus import EventBus


async def test_publish_subscribe() -> None:
    bus = EventBus()
    received: list[dict[str, object]] = []
    bus.subscribe("test", lambda e: received.append(e))
    await bus.publish("test", {"value": 42})
    assert len(received) == 1
    assert received[0]["value"] == 42
    assert received[0]["topic"] == "test"


async def test_history() -> None:
    bus = EventBus()
    await bus.publish("a", {"n": 1})
    await bus.publish("b", {"n": 2})
    await bus.publish("a", {"n": 3})
    assert len(bus.get_history()) == 3
    assert len(bus.get_history(topic="a")) == 2


async def test_unsubscribe() -> None:
    bus = EventBus()
    received: list[dict[str, object]] = []
    handler = lambda e: received.append(e)  # noqa: E731
    bus.subscribe("x", handler)
    bus.unsubscribe("x", handler)
    await bus.publish("x", {"n": 1})
    assert len(received) == 0
