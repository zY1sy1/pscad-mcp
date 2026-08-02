"""Shared FastMCP registration with stable PSCAD error serialization."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from mcp.server.fastmcp import FastMCP

from ..core.connection_manager import pscad_manager


P = ParamSpec("P")
R = TypeVar("R")


def register_tool(
    mcp: FastMCP,
    function: Callable[P, Awaitable[R]],
) -> None:
    """Register an async tool while preserving structured backend failures."""

    @wraps(function)
    async def guarded(*args: P.args, **kwargs: P.kwargs) -> Any:
        try:
            return await function(*args, **kwargs)
        except Exception as error:
            return pscad_manager.error_payload(error, function.__name__)

    mcp.tool()(guarded)
