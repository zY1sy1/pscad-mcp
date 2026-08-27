"""MCP registrations for the generic PSCAD blueprint builder."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..builders.blueprint.service import BlueprintBuilderService
from ..core.connection_manager import pscad_manager
from .registration import register_tool


_builder_service: BlueprintBuilderService | None = None
_builder_backend: Any = None


def _service() -> BlueprintBuilderService:
    global _builder_service, _builder_backend
    backend = pscad_manager.service
    if _builder_service is None or backend is not _builder_backend:
        _builder_backend = backend
        _builder_service = BlueprintBuilderService(backend)
    return _builder_service


async def plan_pscad_project_build(
    blueprint: str | dict[str, Any],
    source_package_path: str,
    target_name: str,
    parameter_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Audit a blueprint and source package and return an immutable plan hash."""

    return await _service().plan_project(
        blueprint,
        source_package_path,
        target_name,
        parameter_overrides,
    )


async def build_pscad_project(
    expected_plan_hash: str,
    blueprint: str | dict[str, Any],
    source_package_path: str,
    target_name: str,
    parameter_overrides: dict[str, dict[str, Any]] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Start the explicitly confirmed, exact-hash blueprint build."""

    return await _service().build_project(
        expected_plan_hash,
        blueprint,
        source_package_path,
        target_name,
        parameter_overrides,
        confirm=confirm,
    )


async def get_pscad_project_build_status(build_id: str) -> dict[str, Any]:
    """Return JSON-safe asynchronous blueprint build state and evidence."""

    return _service().get_build_status(build_id)


async def validate_pscad_project_build(
    build_id: str | None = None,
    staging_path: str | None = None,
) -> dict[str, Any]:
    """Independently validate one completed build or contained staging package."""

    return await _service().validate_project_build(
        build_id=build_id,
        staging_path=staging_path,
    )


def register_blueprint_tools(mcp: FastMCP) -> None:
    for function in (
        plan_pscad_project_build,
        build_pscad_project,
        get_pscad_project_build_status,
        validate_pscad_project_build,
    ):
        register_tool(mcp, function)


__all__ = [
    "build_pscad_project",
    "get_pscad_project_build_status",
    "plan_pscad_project_build",
    "register_blueprint_tools",
    "validate_pscad_project_build",
]

