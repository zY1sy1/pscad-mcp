"""Bounded, always-on PSCAD MCP capability discovery."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.connection_manager import pscad_manager
from .catalog import FULL_TOOL_NAMES, TOOL_SPECS, ToolProfile
from .registration import (
    _BACKEND_NAME,
    _PSCAD_VERSION,
    _bounded_identifier,
    register_tool,
)


_UNKNOWN_CONNECTION = {
    "connected": False,
    "backend": None,
    "version": None,
}
_KNOWN_BACKENDS = frozenset().union(
    *(spec.backend_support for spec in TOOL_SPECS.values())
)


def _bounded_connection(connection: object) -> dict[str, bool | str | None]:
    if not isinstance(connection, Mapping):
        return dict(_UNKNOWN_CONNECTION)
    try:
        connected = connection.get("connected") is True
        backend = _bounded_identifier(connection.get("backend"), _BACKEND_NAME)
        version = _bounded_identifier(connection.get("version"), _PSCAD_VERSION)
    except Exception:
        return dict(_UNKNOWN_CONNECTION)
    if not connected or backend not in _KNOWN_BACKENDS:
        return dict(_UNKNOWN_CONNECTION)
    return {
        "connected": True,
        "backend": backend,
        "version": version,
    }


def _catalog_names(values: Iterable[object]) -> frozenset[str]:
    return frozenset(
        value
        for value in values
        if isinstance(value, str) and value in FULL_TOOL_NAMES
    )


def build_capability_payload(
    *,
    profile: ToolProfile,
    registered_names: Iterable[object],
    connection: object,
) -> dict[str, Any]:
    """Build a deterministic capability response without exposing raw values."""
    registered = _catalog_names(registered_names)
    bounded_connection = _bounded_connection(connection)
    connected = bounded_connection["connected"] is True
    backend = bounded_connection["backend"]
    records: list[dict[str, str | None]] = []

    for name in sorted(FULL_TOOL_NAMES):
        spec = TOOL_SPECS[name]
        limitation_code = None
        if not spec.backend_support:
            state = "supported"
        elif not connected:
            state = "unknown"
        elif backend in spec.backend_support:
            state = "supported"
        else:
            state = "unavailable"
            limitation_code = spec.limitation_code or "CAPABILITY_UNAVAILABLE"
        records.append(
            {
                "name": name,
                "group": spec.group,
                "state": state,
                "limitation_code": limitation_code,
            }
        )

    return {
        "profile": profile.label,
        "registered_groups": sorted(profile.groups),
        "registered_tools": sorted(registered),
        "inactive_tools": sorted(FULL_TOOL_NAMES - registered),
        "connection": bounded_connection,
        "capabilities": records,
    }


def register_capability_tool(mcp: FastMCP) -> None:
    """Register capability discovery after all profile-selected tools."""
    profile = mcp._pscad_tool_profile

    async def get_pscad_capabilities() -> dict[str, Any]:
        """Discover the active PSCAD MCP profile and bounded backend capabilities."""
        try:
            connection = await pscad_manager.get_status()
        except Exception:
            connection = _UNKNOWN_CONNECTION
        registered_names = getattr(mcp, "_pscad_registered_tool_names", set())
        return build_capability_payload(
            profile=profile,
            registered_names=registered_names,
            connection=connection,
        )

    register_tool(
        mcp,
        get_pscad_capabilities,
        record_learning=False,
        force=True,
    )
