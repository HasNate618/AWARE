from aware.app.llm.stub import StubLLM


async def test_create_rule_from_natural_language() -> None:
    llm = StubLLM()
    spec = await llm.create_rule("When glass breaks after 10pm, sound the alarm")
    assert "glass" in spec.when.lower()
    assert "alarm" in spec.then.lower()


async def test_create_rule_simple() -> None:
    llm = StubLLM()
    spec = await llm.create_rule("When someone walks in, say welcome and flash green")
    assert "someone" in spec.when.lower()
    assert "welcome" in spec.then.lower()


async def test_fallback_for_unstructured_input() -> None:
    llm = StubLLM()
    spec = await llm.create_rule("do something interesting")
    assert spec.name
    assert spec.when == "do something interesting"


async def test_query_memory_stub() -> None:
    llm = StubLLM()
    result = await llm.query_memory("what happened?", "person detected at 3pm")
    assert "stub" in result.lower()
