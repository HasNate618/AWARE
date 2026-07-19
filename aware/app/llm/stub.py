from __future__ import annotations

import logging
import re
import time

from aware.app.llm.interface import LLMStats, RuleSpec

logger = logging.getLogger(__name__)

_CREATE_RULE_RE = re.compile(
    r"when\s+(.+?)(?:,\s*|\s+then\s+|\s+)(say|play|alert|notify|log|send|show|light|turn|ring|sound|speak|activate|enable|disable|start|stop|trigger)\s+(.+?)(?:\s+priority\s+(\w+))?$",
    re.IGNORECASE,
)


class StubLLM:
    """Deterministic English -> create_rule. No ML. Always returns the same output."""

    def __init__(self) -> None:
        self._stats = LLMStats()

    @property
    def stats(self) -> LLMStats:
        return self._stats

    async def create_rule(self, user_input: str) -> RuleSpec:
        start = time.monotonic()
        text = user_input.strip().rstrip(".")
        match = _CREATE_RULE_RE.search(text)
        if match:
            when, _verb, then, priority = match.groups()
            result = RuleSpec(
                name=_slugify(when),
                when=when.strip(),
                then=f"{_verb} {then.strip()}",
                priority=priority or "normal",
            )
        else:
            result = RuleSpec(
                name=_slugify(text[:40]),
                when=text,
                then="log event",
                priority="normal",
            )
        elapsed = (time.monotonic() - start) * 1000
        self._stats.record(elapsed, True)
        return result

    async def query_memory(self, question: str, context: str) -> str:
        return f"[stub] Based on the log: {context[:200]}...\n\nQ: {question}"

    async def summarize_period(self, digest_text: str) -> str:
        return digest_text


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:50]
