"""Real LLM client using llama.cpp server with few-shot prompting."""

from __future__ import annotations

import json
import logging
import re

import httpx

from aware.app.llm.interface import RuleSpec

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Create a JSON rule from the user's command.\n\n"
    "Examples:\n"
    'User: when person walks in say welcome\n'
    'Output: {"name": "greet", "when": "person detected", '
    '"then": "say welcome", "priority": "normal"}\n\n'
    'User: when glass breaks after 10pm sound alarm\n'
    'Output: {"name": "night_alert", '
    '"when": "glass breaking sound and after 10pm", '
    '"then": "sound alarm", "priority": "high"}\n\n'
    'User: when doorbell rings flash green\n'
    'Output: {"name": "doorbell_alert", '
    '"when": "doorbell sound", '
    '"then": "flash green", "priority": "normal"}'
)

# Grammar forces valid JSON with the 4 fields we need
_JSON_GRAMMAR = (
    'root ::= "{" '
    '"\\"name\\"" ":" string "," '
    '"\\"when\\"" ":" string "," '
    '"\\"then\\"" ":" string "," '
    '"\\"priority\\"" ":" string "}"\n'
    'string ::= "\\"" ("\\\\" . | [^"\\\\])* "\\""\n'
)

_NAME_RE = re.compile(r"[^a-z0-9]+", re.IGNORECASE)


def _slugify(text: str) -> str:
    return _NAME_RE.sub("_", text.lower()).strip("_")[:50]


def _extract_json(text: str) -> dict[str, object] | None:
    """Extract JSON object from LLM output."""
    try:
        result: dict[str, object] = json.loads(text)
        return result
    except json.JSONDecodeError:
        pass
    idx = text.find("{")
    if idx >= 0:
        depth = 0
        for i in range(idx, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        result = json.loads(text[idx : i + 1])
                        return result
                    except json.JSONDecodeError:
                        break
    return None


def _normalize_value(val: str | list[str] | None) -> str:
    """Normalize LLM output: join lists with ' and ', strip whitespace."""
    if val is None:
        return ""
    if isinstance(val, list):
        return " and ".join(str(v) for v in val)
    return str(val).strip()


class LlamaLLM:
    """LLM client that talks to a local llama.cpp server."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model: str = "minicpm5",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    async def create_rule(self, user_input: str) -> RuleSpec:
        prompt = f"{_SYSTEM_PROMPT}\nUser: {user_input}\nOutput: "
        payload = {
            "prompt": prompt,
            "grammar": _JSON_GRAMMAR,
            "temperature": 0.1,
            "n_predict": 64,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/completion", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.exception("LLM request failed")
            return RuleSpec(
                name=_slugify(user_input[:40]),
                when=user_input,
                then="log event",
                priority="normal",
            )

        content = data.get("content", "")
        logger.info("LLM response: %s", content)

        parsed = _extract_json(content)
        if not parsed:
            logger.warning("Failed to parse LLM JSON: %s", content[:200])
            return RuleSpec(
                name=_slugify(user_input[:40]),
                when=user_input,
                then="log event",
                priority="normal",
            )

        when_raw = parsed.get("when", user_input)
        then_raw = parsed.get("then", "log event")
        priority_raw = parsed.get("priority", "normal")

        def _coerce(val: object, default: str) -> str:
            if isinstance(val, (str, list)):
                return str(val)
            return default

        return RuleSpec(
            name=_slugify(str(parsed.get("name", user_input[:40]))),
            when=_normalize_value(_coerce(when_raw, user_input)),
            then=_normalize_value(_coerce(then_raw, "log event")),
            priority=_normalize_value(_coerce(priority_raw, "normal")),
        )

    async def query_memory(self, question: str, context: str) -> str:
        messages = [
            {
                "role": "system",
                "content": "Answer the user's question based on the context provided.",
            },
            {"role": "user", "content": f"Context: {context}\n\nQuestion: {question}"},
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 256,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/v1/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.exception("LLM memory query failed")
            return f"[error] Could not answer: {question}"

        return str(data["choices"][0]["message"].get("content", ""))
