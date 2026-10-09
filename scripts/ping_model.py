"""One-shot verification that the configured endpoint really answers.

This is the *only* script in the repo allowed to call a live API, and it is a manual
gate for P1 — the automated suite never needs it.

    uv run python scripts/ping_model.py
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from agents import Agent, Runner
from app.config import ConfigError, get_settings
from app.model import build_model


async def main() -> int:
    settings = get_settings()
    print(f"base_url = {settings.llm_base_url}")
    print(f"model    = {settings.llm_model}")
    print(f"backend  = {settings.model_backend}")
    try:
        model = build_model(settings)
    except ConfigError as exc:
        print(f"\n[config error] {exc}", file=sys.stderr)
        return 2

    agent = Agent(
        name="ping",
        instructions="You are a connectivity check. Reply with exactly: 连接正常",
        model=model,
    )
    result = await Runner.run(agent, input="ping", max_turns=1)
    print(f"\nreply: {result.final_output}")
    # v0.23.1 fact: RunResult has no `.usage`; per-request Usage lives on raw_responses
    total = {"requests": 0, "input": 0, "output": 0}
    for resp in result.raw_responses:
        total["requests"] += 1
        total["input"] += resp.usage.input_tokens
        total["output"] += resp.usage.output_tokens
    print(f"usage: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
