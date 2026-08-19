"""MCP registrations for the fixed Stage A MMC builder."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.connection_manager import pscad_manager
from ..hvdc.builders.mmc.service import MmcBuilderService
from .registration import register_tool


_builder_service: MmcBuilderService | None = None
_builder_backend: Any = None


def _service() -> MmcBuilderService:
    global _builder_service, _builder_backend
    backend = pscad_manager.service
    if _builder_service is None or backend is not _builder_backend:
        _builder_backend = backend
        _builder_service = MmcBuilderService(backend)
    return _builder_service


async def plan_mmc_model(
    project_name: str,
    folder: str | None = None,
    simulation_duration_s: float | None = None,
    blueprint: str = "cigre_b4_p2p_avm_v1",
) -> dict[str, Any]:
    return _service().plan_model(project_name, folder, simulation_duration_s, blueprint)


async def build_mmc_model(
    project_name: str,
    expected_plan_hash: str,
    folder: str | None = None,
    simulation_duration_s: float | None = None,
    blueprint: str = "cigre_b4_p2p_avm_v1",
    confirm: bool = False,
) -> dict[str, Any]:
    return await _service().build_model(project_name, expected_plan_hash, folder, simulation_duration_s, blueprint, confirm)


async def get_mmc_build_status(build_id: str) -> dict[str, Any]:
    return _service().get_build_status(build_id)


async def validate_mmc_model(
    project_name: str,
    blueprint: str = "cigre_b4_p2p_avm_v1",
    output_file: str | None = None,
) -> dict[str, Any]:
    return _service().validate_model(project_name, blueprint, output_file)


def register_mmc_tools(mcp: FastMCP) -> None:
    for function in (plan_mmc_model, build_mmc_model, get_mmc_build_status, validate_mmc_model):
        register_tool(mcp, function)


__all__ = [
    "build_mmc_model",
    "get_mmc_build_status",
    "plan_mmc_model",
    "register_mmc_tools",
    "validate_mmc_model",
]
