"""Tool interface: every research tool declares its schema, permission,
cost estimate, timeout and provenance behaviour up front.

The executor may only invoke tools registered here. A tool that is not
registered cannot run, and an EXTERNAL_ACTION/HIGH_RISK tool cannot run
without explicit authorization (see security/permissions).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..security.permissions import AuthorizationError, Permission, require_authorization


@dataclass
class ToolResult:
    ok: bool
    output: str = ""
    error: str = ""
    cost_usd: float = 0.0
    provenance: dict = field(default_factory=dict)

    def preview(self) -> str:
        return (self.output or self.error)[:2000]


@dataclass
class Tool:
    name: str
    description: str
    permission: Permission
    input_schema: dict
    timeout_s: int
    run: Callable[[dict], ToolResult]

    def invoke(self, arguments: dict, authorized: bool = False) -> ToolResult:
        require_authorization(self.permission, authorized,
                              f"tool {self.name}")
        try:
            return self.run(arguments)
        except AuthorizationError:
            raise
        except Exception as exc:  # tool errors are data, not crashes
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> str:
        lines = []
        for name in self.names():
            t = self._tools[name]
            lines.append(f"- {name} [{t.permission.value}]: {t.description} "
                         f"Inputs: {t.input_schema}")
        return "\n".join(lines)


def default_registry() -> ToolRegistry:
    """Read-only research tools + local computation. No external-action tools
    are registered by default: consequential actions require a separately
    configured, explicitly authorized tool, which this release does not ship.
    """
    from . import computation, retrieval, search

    registry = ToolRegistry()
    registry.register(search.web_search_tool())
    registry.register(retrieval.fetch_page_tool())
    registry.register(computation.calculate_tool())
    return registry
