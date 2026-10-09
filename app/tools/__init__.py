"""Tools package: what the agent is actually able to do.

    impl/      pure Python logic, no SDK imports, tested directly
    builtin/   thin @function_tool wrappers + their risk declarations
    registry   discovery and risk metadata
    errors     ToolInputError and model-facing failure messages
    context    AppContext (workspace root and byte limits)
"""

from __future__ import annotations

from app.tools.context import AppContext
from app.tools.errors import ToolInputError, WorkspaceBoundaryError
from app.tools.registry import (
    RISK_LEVELS,
    DuplicateToolError,
    Registry,
    RegistryIntegrityError,
    UnknownToolError,
    build_registry,
    default_registry,
    discover_tools,
)

__all__ = [
    "RISK_LEVELS",
    "AppContext",
    "DuplicateToolError",
    "Registry",
    "RegistryIntegrityError",
    "ToolInputError",
    "UnknownToolError",
    "WorkspaceBoundaryError",
    "build_registry",
    "default_registry",
    "discover_tools",
]
