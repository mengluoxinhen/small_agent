"""Agent assembly: SDK Agent wired with our prompt, model and tool registry.

`build_agent` is the only place allowed to touch `Agent(...)`; P4/P6 will pass the same
factory a per-session model and the approval-aware run config.
"""

from __future__ import annotations

from typing import Any

from agents import Agent

from app.agent.approval import attach_approval_policy
from app.agent.prompts import SYSTEM_PROMPT
from app.config import RunMode
from app.tools.registry import Registry, default_registry


def build_agent(
    *, model: Any, registry: Registry | None = None, mode: RunMode = "review", name: str = "small-dify"
) -> Agent:
    reg = registry or default_registry()
    tools = attach_approval_policy(reg.tools, reg, mode)
    return Agent(name=name, instructions=SYSTEM_PROMPT, model=model, tools=tools)
