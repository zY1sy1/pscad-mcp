"""MCP registrations for the fixed CIGRE LCC builder."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.connection_manager import pscad_manager
from ..hvdc.builders.lcc.service import LccBuilderService
from .registration import register_tool


_builder_service: LccBuilderService | None = None
_builder_backend: Any = None


def _service() -> LccBuilderService:
    global _builder_service, _builder_backend
    backend = pscad_manager.service
    if _builder_service is None or backend is not _builder_backend:
        _builder_backend = backend
        _builder_service = LccBuilderService(backend)
    return _builder_service


async def plan_lcc_model(
    project_name: str,
    folder: str | None = None,
    simulation_duration_s: float | None = None,
    blueprint: str = "cigre_lcc_monopole_v1",
) -> dict[str, Any]:
    """Plan a fixed CIGRE LCC model build without changing the workspace."""
    return _service().plan_model(project_name, folder, simulation_duration_s, blueprint)


async def build_lcc_model(
    project_name: str,
    expected_plan_hash: str,
    folder: str | None = None,
    simulation_duration_s: float | None = None,
    blueprint: str = "cigre_lcc_monopole_v1",
    confirm: bool = False,
) -> dict[str, Any]:
    """Start a confirmed fixed CIGRE LCC model build from a matching plan."""
    return await _service().build_model(
        project_name,
        expected_plan_hash,
        folder,
        simulation_duration_s,
        blueprint,
        confirm,
    )


async def get_lcc_build_status(build_id: str) -> dict[str, Any]:
    """Get the current status and evidence for a fixed LCC model build."""
    return _service().get_build_status(build_id)


async def validate_lcc_model(
    project_name: str,
    blueprint: str = "cigre_lcc_monopole_v1",
    output_file: str | None = None,
) -> dict[str, Any]:
    """Validate a fixed LCC model and optional output evidence."""
    return _service().validate_model(project_name, blueprint, output_file)


def register_lcc_tools(mcp: FastMCP) -> None:
    for function in (plan_lcc_model, build_lcc_model, get_lcc_build_status, validate_lcc_model):
        register_tool(mcp, function)


__all__ = [
    "build_lcc_model",
    "get_lcc_build_status",
    "plan_lcc_model",
    "register_lcc_tools",
    "validate_lcc_model",
]
