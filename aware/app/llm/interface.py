from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class LLMStats:
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    max_latencies: int = 100

    @property
    def avg_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return sum(self.latencies_ms) / len(self.latencies_ms)

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.successful_calls / self.total_calls

    def record(self, latency_ms: float, success: bool) -> None:
        self.total_calls += 1
        if success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1
        self.latencies_ms.append(latency_ms)
        if len(self.latencies_ms) > self.max_latencies:
            self.latencies_ms.pop(0)

    def to_dict(self) -> dict[str, object]:
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "success_rate": round(self.success_rate, 3),
        }


@dataclass
class RuleSpec:
    name: str
    when: str
    then: str
    priority: str = "normal"
    raw: str = ""


@runtime_checkable
class LLMClient(Protocol):
    async def create_rule(self, user_input: str) -> RuleSpec: ...

    async def query_memory(self, question: str, context: str) -> str: ...

    @property
    def stats(self) -> LLMStats: ...
