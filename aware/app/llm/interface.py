from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class RuleSpec:
    name: str
    when: str
    then: str
    priority: str = "normal"


@runtime_checkable
class LLMClient(Protocol):
    async def create_rule(self, user_input: str) -> RuleSpec: ...

    async def query_memory(self, question: str, context: str) -> str: ...
