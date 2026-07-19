#!/usr/bin/env python3
"""Seed venue demo automations without calling the LLM (instant, reliable).

Run on the board:
    cd ~/aware && source .venv/bin/activate
    python scripts/seed-venue-demo.py

Options:
    --flash-only   Only LED rules (quiet booth)
    --speak        Include welcome TTS rule (needs BT speaker)
    --clear        Deactivate existing rules first
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running from repo root on board
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aware.app.config import get_settings
from aware.app.parser.nl_parser import parse_rule_from_command
from aware.app.rules.store import RulesStore

DEFAULT_RULES = [
    "when person detected flash green",
    "when person detected say happy hacking",
]

SPEAK_RULE = "when person detected say happy hacking"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed hackathon venue demo rules")
    parser.add_argument("--flash-only", action="store_true", help="LED flash only (no TTS)")
    parser.add_argument("--speak", action="store_true", help="Add welcome speak rule")
    parser.add_argument("--clear", action="store_true", help="Deactivate all active rules first")
    args = parser.parse_args()

    commands = ["when person detected flash green"] if args.flash_only else list(DEFAULT_RULES)
    if args.speak and not args.flash_only and SPEAK_RULE not in commands:
        commands.append(SPEAK_RULE)

    settings = get_settings()
    store = RulesStore(settings.db_path)
    await store.open()

    if args.clear:
        for rule in await store.get_active():
            rule_id = int(rule.get("id", 0))
            if rule_id:
                await store.deactivate_by_id(rule_id)
                print(f"cleared: {rule.get('name') or rule_id}")

    for cmd in commands:
        parsed = parse_rule_from_command(cmd)
        if not parsed.triggers or not parsed.actions:
            print(f"SKIP (unparsed): {cmd}")
            continue
        triggers = [
            {
                "type": t.type,
                "value": t.value,
                "time_range": list(t.time_range) if t.time_range else None,
                "transition": t.transition,
                "sensor_op": t.sensor_op,
                "sensor_threshold": t.sensor_threshold,
            }
            for t in parsed.triggers
        ]
        actions = [{"type": a.type, "params": a.params} for a in parsed.actions]
        when_text = ", ".join(t.value for t in parsed.triggers)
        then_parts: list[str] = []
        for action in parsed.actions:
            if action.type == "speak":
                then_parts.append(action.params.get("text", "speak"))
            elif action.type == "led_flash":
                then_parts.append(f"flash {action.params.get('color', '')}")
            elif action.type == "led_on":
                then_parts.append(f"turn on {action.params.get('color', '')}")
            else:
                then_parts.append(action.type)
        then_text = " and ".join(then_parts)
        name = await store.add(
            name=parsed.name,
            when_text=when_text,
            then_text=then_text,
            priority=parsed.priority,
            triggers=triggers,
            actions=actions,
            llm_raw="venue-demo-seed",
        )
        print(f"✓ {name}: when {when_text} → {then_text}")

    await store.close()
    print("\nDone. Point the camera at foot traffic and watch the Witness panel.")


if __name__ == "__main__":
    asyncio.run(main())
