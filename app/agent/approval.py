"""Approval policy: the PLAN §5 mode × risk matrix as a pure function.

Keeping this pure (two strings in, one bool out) is what makes the 6-cell matrix
assertable without running anything. `attach_approval_policy` only then copies that
verdict onto tool clones — the registry's shared instances are never mutated, so two
runs with different modes can coexist in one process.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable

from agents import FunctionTool

from app.config import RunMode
from app.tools.registry import Registry

HIGH_RISK_LEVELS = frozenset({"write", "dangerous"})


def should_pause(risk: str, mode: RunMode) -> bool:
    """Does this tool risk require human approval under this run mode?"""
    if mode == "full_access":
        return False
    return risk in HIGH_RISK_LEVELS


def attach_approval_policy(
    tools: Iterable[FunctionTool], registry: Registry, mode: RunMode
) -> list[FunctionTool]:
    """Clone each builtin tool with `needs_approval` set from the matrix."""
    policy: list[FunctionTool] = []
    for tool in tools:
        if isinstance(tool, FunctionTool):
            pause = should_pause(registry.risk_for(tool.name), mode)
            policy.append(dataclasses.replace(tool, needs_approval=pause))
        else:
            policy.append(tool)
    return policy
