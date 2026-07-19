"""Real LLM client using llama.cpp server with few-shot prompting."""

from __future__ import annotations

import json
import logging
import re
import time

import httpx

from aware.app.llm.interface import LLMStats, RuleSpec

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Create a JSON rule from the user's command.\n\n"
    "Examples:\n"
    "User: when person walks in say welcome\n"
    'Output: {"name": "greet", "when": "person detected", '
    '"then": "say welcome", "priority": "normal"}\n\n'
    "User: when person enters say hello\n"
    'Output: {"name": "greeter", "when": "person enters", '
    '"then": "say hello", "priority": "normal"}\n\n'
    "User: when dog leaves say goodbye\n"
    'Output: {"name": "farewell", "when": "dog leaves", '
    '"then": "say goodbye", "priority": "normal"}\n\n'
    "User: when glass breaks after 10pm sound alarm\n"
    'Output: {"name": "night_alert", '
    '"when": "glass breaking sound and after 10pm", '
    '"then": "sound alarm", "priority": "high"}\n\n'
    "User: when doorbell rings flash green\n"
    'Output: {"name": "doorbell_alert", '
    '"when": "doorbell sound", '
    '"then": "flash green", "priority": "normal"}\n\n'
    "User: when bottle within 1m say i am hydrophobic\n"
    'Output: {"name": "hydrophobic", '
    '"when": "bottle within 1m", '
    '"then": "say i am hydrophobic", "priority": "normal"}\n\n'
    "User: when hot flash red\n"
    'Output: {"name": "overheat", '
    '"when": "hot", '
    '"then": "flash red", "priority": "high"}'
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
        self._stats = LLMStats()

    @property
    def stats(self) -> LLMStats:
        return self._stats

    async def create_rule(self, user_input: str) -> RuleSpec:
        start = time.monotonic()
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
            elapsed = (time.monotonic() - start) * 1000
            self._stats.record(elapsed, False)
            logger.exception("LLM request failed")
            return RuleSpec(
                name=_slugify(user_input[:40]),
                when=user_input,
                then="log event",
                priority="normal",
            )

        content = data.get("content", "")
        elapsed = (time.monotonic() - start) * 1000
        logger.info("LLM response: %s", content)

        parsed = _extract_json(content)
        if not parsed:
            self._stats.record(elapsed, False)
            logger.warning("Failed to parse LLM JSON: %s", content[:200])
            return RuleSpec(
                name=_slugify(user_input[:40]),
                when=user_input,
                then="log event",
                priority="normal",
                raw=content[:500],
            )

        self._stats.record(elapsed, True)

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
            raw=content[:1000],
        )

    async def summarize_period(self, digest_text: str) -> str:
        start = time.monotonic()
        prompt = (
            "Summarize this witness log in 1-2 short sentences. "
            "Only mention people entering, sounds heard, and sensor changes listed. "
            "Do not invent events.\n\n"
            f"Log:\n{digest_text}\n\nSummary:"
        )
        payload = {
            "prompt": prompt,
            "temperature": 0.2,
            "n_predict": 128,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/completion", json=payload)
                resp.raise_for_status()
                data = resp.json()
            content = str(data.get("content", "")).strip()
            elapsed = (time.monotonic() - start) * 1000
            self._stats.record(elapsed, bool(content))
            return content or digest_text
        except Exception:
            elapsed = (time.monotonic() - start) * 1000
            self._stats.record(elapsed, False)
            logger.exception("LLM summarize_period failed")
            return digest_text

    async def query_memory(self, question: str, context: str) -> str:
        start = time.monotonic()
        prompt = (
            "You are AWARE, an on-device space monitor. "
            "Answer the question using only the activity log below. "
            "Include specific times when available. "
            "If the log does not contain the answer, say so.\n\n"
            f"Activity log:\n{context}\n\n"
            f"Question: {question}\n\nAnswer:"
        )
        payload = {
            "prompt": prompt,
            "temperature": 0.3,
            "n_predict": 256,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/completion", json=payload)
                resp.raise_for_status()
                data = resp.json()
            content = str(data.get("content", "")).strip()
            elapsed = (time.monotonic() - start) * 1000
            self._stats.record(elapsed, bool(content))
            return content or f"[error] Could not answer: {question}"
        except Exception:
            elapsed = (time.monotonic() - start) * 1000
            self._stats.record(elapsed, False)
            logger.exception("LLM memory query failed")
            return f"[error] Could not answer: {question}"
