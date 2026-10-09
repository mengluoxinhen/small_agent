"""Print every registered tool with its risk tier and JSON schema.

P2 acceptance gate: `uv run python scripts/list_tools.py` must show exactly the five
builtin tools, each with a strict schema (properties == required) and a declared risk.
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")

from app.tools.registry import default_registry


def main() -> int:
    registry = default_registry()
    for name in sorted(registry.names):
        tool = registry.by_name(name)
        schema = tool.params_json_schema
        print(f"== {name} [{registry.risk_for(name)}]")
        print(f"  description: {tool.description}")
        print("  required   : " + ", ".join(schema.get("required", [])))
        print("  properties :")
        print(json.dumps(schema["properties"], ensure_ascii=False, indent=4))
    print(f"\n{len(registry.names)} tools registered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
