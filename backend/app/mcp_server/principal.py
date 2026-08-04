"""Request-local identity for the external MCP endpoint."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class MCPPrincipal:
    """The minimum authenticated identity needed by MCP tool execution."""

    user_id: int
    bank_mode: str


_principal_var: ContextVar[MCPPrincipal | None] = ContextVar(
    "mcp_principal", default=None
)


def get_mcp_principal() -> MCPPrincipal | None:
    return _principal_var.get()


def set_mcp_principal(principal: MCPPrincipal | None):
    return _principal_var.set(principal)


def reset_mcp_principal(token) -> None:
    _principal_var.reset(token)
