"""One-shot verification that the configured endpoint really answers.

This is the *only* script in the repo allowed to call a live API, and it is a manual
gate for P1 — the automated suite never needs it.

    uv run python scripts/ping_model.py
"""

from __future__ import annotations

import asyncio
import sys

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
    usage = result.usage
    print(f"usage: requests={usage.requests} in={usage.input_tokens} out={usage.output_tokens}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
