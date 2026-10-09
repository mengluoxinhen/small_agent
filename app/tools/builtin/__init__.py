"""Builtin tool wrappers.

Each module here defines `@function_tool` functions plus a `TOOL_RISK` table naming the
risk level of every tool it defines; `app.tools.registry` discovers them and refuses to
register anything without a declaration.

Add a new tool: write the logic in `app/tools/impl/`, wrap it here, list it in `TOOL_RISK`,
and add tests. Nothing else to remember — `tests/test_tools_registry.py` fails if any of
those steps is skipped.
"""
