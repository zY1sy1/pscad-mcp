"""MCP lifecycle tools for blank-project LCC and MMC builders."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.connection_manager import pscad_manager
from ..hvdc.builders.lcc.blank import BlankLccRequest
from ..hvdc.builders.lcc.service import LccBuilderService
from ..hvdc.builders.mmc.blank import BlankMmcRequest
from ..hvdc.builders.mmc.service import MmcBuilderService
from .registration import register_tool

_lcc_instance: LccBuilderService | None = None
_mmc_instance: MmcBuilderService | None = None
_backend: Any = None


def _backend_services() -> Any:
    return pscad_manager.service


def _lcc_service() -> LccBuilderService:
    global _lcc_instance, _backend
    backend = _backend_services()
    if _lcc_instance is None or backend is not _backend:
        _backend = backend
        _lcc_instance = LccBuilderService(backend)
    return _lcc_instance


def _mmc_service() -> MmcBuilderService:
    global _mmc_instance, _backend
    backend = _backend_services()
    if _mmc_instance is None or backend is not _backend:
        _backend = backend
        _mmc_instance = MmcBuilderService(backend)
    return _mmc_instance


def _lcc_args(request: dict[str, Any]) -> tuple[str, str | None, float | None, str]:
    parsed = BlankLccRequest.from_dict(request)
    return (
        parsed.project_name,
        parsed.folder,
        request.get("simulation_duration_s"),
        "cigre_lcc_monopole_v1",
    )


def _mmc_args(request: dict[str, Any]) -> tuple[str, str | None, float | None, str]:
    parsed = BlankMmcRequest.from_dict(request)
    return (
        parsed.project_name,
        parsed.folder,
        request.get("simulation_duration_s"),
        "cigre_b4_p2p_avm_v1",
    )


async def plan_blank_lcc_model(request: dict[str, Any]) -> dict[str, Any]:
    """Plan a blank-project LCC model build without changing the workspace."""
    project, folder, duration, blueprint = _lcc_args(request)
    result = _lcc_service().plan_model(project, folder, duration, blueprint)
    result["blank_request"] = BlankLccRequest.from_dict(request).to_dict()
    result["fault_events"] = [
        {"kind": "inverter_ac_disturbance", "time_s": 0.5, "duration_s": 0.1}
    ]
    return result


async def build_blank_lcc_model(
    request: dict[str, Any], expected_plan_hash: str, confirm: bool = False
) -> dict[str, Any]:
    """Start a confirmed blank-project LCC model build."""
    project, folder, duration, blueprint = _lcc_args(request)
    return await _lcc_service().build_model(
        project, expected_plan_hash, folder, duration, blueprint, confirm
    )


async def get_blank_lcc_build_status(build_id: str) -> dict[str, Any]:
    """Get blank-project LCC build status."""
    return _lcc_service().get_build_status(build_id)


async def validate_blank_lcc_model(
    project_name: str,
    blueprint: str = "cigre_lcc_monopole_v1",
    output_file: str | None = None,
) -> dict[str, Any]:
    """Validate a blank-project LCC model."""
    return _lcc_service().validate_model(project_name, blueprint, output_file)


async def plan_blank_mmc_model(request: dict[str, Any]) -> dict[str, Any]:
    """Plan a blank-project MMC model build without changing the workspace."""
    project, folder, duration, blueprint = _mmc_args(request)
    result = _mmc_service().plan_model(project, folder, duration, blueprint)
    parsed = BlankMmcRequest.from_dict(request)
    result["blank_request"] = parsed.to_dict()
    result["capabilities"] = parsed.submodule_topology.capabilities(
        parsed.submodule_topology
    )
    result["fault_events"] = [
        {"kind": "dc_pole_to_pole", "time_s": 0.3, "removal_time_s": 0.5}
    ]
    return result


async def build_blank_mmc_model(
    request: dict[str, Any], expected_plan_hash: str, confirm: bool = False
) -> dict[str, Any]:
    """Start a confirmed blank-project MMC model build."""
    project, folder, duration, blueprint = _mmc_args(request)
    return await _mmc_service().build_model(
        project, expected_plan_hash, folder, duration, blueprint, confirm
    )


async def get_blank_mmc_build_status(build_id: str) -> dict[str, Any]:
    """Get blank-project MMC build status."""
    return _mmc_service().get_build_status(build_id)


async def validate_blank_mmc_model(
    project_name: str,
    blueprint: str = "cigre_b4_p2p_avm_v1",
    output_file: str | None = None,
) -> dict[str, Any]:
    """Validate a blank-project MMC model."""
    return _mmc_service().validate_model(project_name, blueprint, output_file)


def register_blank_builder_tools(mcp: FastMCP) -> None:
    for function in (
        plan_blank_lcc_model,
        build_blank_lcc_model,
        get_blank_lcc_build_status,
        validate_blank_lcc_model,
        plan_blank_mmc_model,
        build_blank_mmc_model,
        get_blank_mmc_build_status,
        validate_blank_mmc_model,
    ):
        register_tool(mcp, function)


__all__ = ["register_blank_builder_tools"]
