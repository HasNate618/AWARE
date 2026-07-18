from __future__ import annotations

import logging
import re

from aware.app.llm.interface import RuleSpec

logger = logging.getLogger(__name__)

_CREATE_RULE_RE = re.compile(
    r"when\s+(.+?)(?:,\s*|\s+then\s+)(.+?)(?:\s+priority\s+(\w+))?$",
    re.IGNORECASE,
)


class StubLLM:
    """Deterministic English -> create_rule. No ML. Always returns the same output."""

    async def create_rule(self, user_input: str) -> RuleSpec:
        text = user_input.strip().rstrip(".")
        match = _CREATE_RULE_RE.search(text)
        if match:
            when, then, priority = match.groups()
            return RuleSpec(
                name=_slugify(when),
                when=when.strip(),
                then=then.strip(),
                priority=priority or "normal",
            )
        return RuleSpec(
            name=_slugify(text[:40]),
            when=text,
            then="log event",
            priority="normal",
        )

    async def query_memory(self, question: str, context: str) -> str:
        return f"[stub] I would answer: {question}\nContext: {context}"


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:50]
