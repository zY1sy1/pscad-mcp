"""Shared FastMCP registration with stable PSCAD error serialization."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
import inspect
from typing import Any, ParamSpec, TypeVar, Union

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

    signature = inspect.signature(function)
    return_annotation = signature.return_annotation
    if return_annotation is inspect.Signature.empty:
        return_annotation = Any
    error_aware_return = Union[return_annotation, dict[str, Any]]
    guarded.__signature__ = signature.replace(
        return_annotation=error_aware_return
    )
    guarded.__annotations__ = dict(function.__annotations__)
    guarded.__annotations__["return"] = error_aware_return
    mcp.tool()(guarded)
