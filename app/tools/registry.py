"""Tool registry: auto-discovery plus risk metadata, with integrity enforced.

Discovery walks every non-underscore module in `app.tools.builtin` and collects the
`FunctionTool` objects it finds. Each module declares risk next to its tools:

    TOOL_RISK = {"read_text_file": "read", "write_text_file": "write"}

Risk levels are *not* guessed from names or inferred from the SDK object, and a tool
without a declaration is a hard error rather than a default. That is deliberate: the P4
approval policy is only as trustworthy as this table, so "no risk level declared" must
never silently mean "safe".
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import ModuleType

from agents import FunctionTool

RISK_LEVELS: tuple[str, ...] = ("read", "write", "dangerous")

RISK_TABLE_ATTRIBUTE = "TOOL_RISK"


class DuplicateToolError(RuntimeError):
    """Two tools claimed the same model-visible name."""


class RegistryIntegrityError(RuntimeError):
    """The tools and the risk table disagree."""


class UnknownToolError(KeyError):
    """Something asked about a tool that is not registered."""


@dataclass(frozen=True)
class Registry:
    tools: tuple[FunctionTool, ...]
    risk_by_tool: Mapping[str, str]
    _by_name: dict[str, FunctionTool] = field(init=False, repr=False, default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_name", {tool.name: tool for tool in self.tools})

    @property
    def names(self) -> list[str]:
        return [tool.name for tool in self.tools]

    def by_name(self, name: str) -> FunctionTool:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise UnknownToolError(f"未注册的工具：{name}") from exc

    def risk_for(self, name: str) -> str:
        if name not in self.risk_by_tool:
            raise UnknownToolError(f"未知工具，无法判定风险等级：{name}")
        return self.risk_by_tool[name]


def _iter_modules(package: ModuleType):
    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name.startswith("_") or module_info.ispkg:
            continue
        yield importlib.import_module(f"{package.__name__}.{module_info.name}")


def _scan(package: ModuleType) -> tuple[dict[str, FunctionTool], dict[str, str]]:
    tools: dict[str, FunctionTool] = {}
    risks: dict[str, str] = {}

    for module in _iter_modules(package):
        for value in vars(module).values():
            if isinstance(value, FunctionTool):
                if value.name in tools:
                    raise DuplicateToolError(
                        f"工具名重复：{value.name}（出现在同一个包的两个位置，模型无法区分）"
                    )
                tools[value.name] = value

        for name, risk in dict(getattr(module, RISK_TABLE_ATTRIBUTE, {}) or {}).items():
            if name in risks and risks[name] != risk:
                raise DuplicateToolError(f"工具 {name} 的风险等级被重复声明且不一致：{risk}")
            risks[name] = risk

    return tools, risks


def discover_tools(package: ModuleType) -> list[FunctionTool]:
    tools, _ = _scan(package)
    return list(tools.values())


def build_registry(package: ModuleType) -> Registry:
    tools, risks = _scan(package)

    undeclared = sorted(name for name in tools if name not in risks)
    if undeclared:
        raise RegistryIntegrityError(
            f"以下工具没有声明风险等级，拒绝注册：{', '.join(undeclared)}。"
            f"请在所在模块的 TOOL_RISK 中标明 {'/'.join(RISK_LEVELS)}"
        )

    orphans = sorted(set(risks) - set(tools))
    if orphans:
        raise RegistryIntegrityError(f"风险表指向了不存在的工具：{', '.join(orphans)}")

    invalid = sorted(f"{name}={risk}" for name, risk in risks.items() if risk not in RISK_LEVELS)
    if invalid:
        raise RegistryIntegrityError(f"无效的风险等级：{', '.join(invalid)}")

    return Registry(tools=tuple(tools.values()), risk_by_tool=risks)


_default: Registry | None = None


def default_registry() -> Registry:
    """The registry over `app.tools.builtin`, built once per process."""
    global _default
    if _default is None:
        from app.tools import builtin

        _default = build_registry(builtin)
    return _default
