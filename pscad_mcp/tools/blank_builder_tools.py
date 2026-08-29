"""MCP lifecycle tools for blank-project LCC and MMC builders."""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.connection_manager import pscad_manager
from ..hvdc.builders.lcc.blank import BlankLccRequest
from ..hvdc.builders.lcc.blank_service import BlankLccBuilderService
from ..hvdc.builders.mmc.blank import BlankMmcRequest
from ..hvdc.builders.mmc.blank_service import BlankMmcBuilderService
from .registration import register_tool

_lcc_instance: BlankLccBuilderService | None = None
_mmc_instance: BlankMmcBuilderService | None = None
_backend: Any = None


def _backend_services() -> Any:
    return pscad_manager.service


def _lcc_service() -> BlankLccBuilderService:
    global _lcc_instance, _backend
    backend = _backend_services()
    if _lcc_instance is None or backend is not _backend:
        _backend = backend
        policy = getattr(backend, "path_policy", None)
        workspace = getattr(policy, "workspace_root", None) or os.environ.get(
            "PSCAD_MCP_WORKSPACE"
        )
        if workspace is None:
            raise ValueError(
                "PSCAD_MCP_WORKSPACE must be configured for blank LCC builds."
            )
        _lcc_instance = BlankLccBuilderService(backend, workspace_root=workspace)
    return _lcc_instance


def _mmc_service() -> BlankMmcBuilderService:
    global _mmc_instance, _backend
    backend = _backend_services()
    if _mmc_instance is None or backend is not _backend:
        _backend = backend
        policy = getattr(backend, "path_policy", None)
        workspace = getattr(policy, "workspace_root", None) or os.environ.get(
            "PSCAD_MCP_WORKSPACE"
        )
        if workspace is None:
            raise ValueError(
                "PSCAD_MCP_WORKSPACE must be configured for blank MMC builds."
            )
        _mmc_instance = BlankMmcBuilderService(backend, workspace_root=workspace)
    return _mmc_instance


def _lcc_args(
    request: dict[str, Any],
) -> tuple[str, str | None, float | None, str, BlankLccRequest]:
    parsed = BlankLccRequest.from_dict(request)
    return (
        parsed.project_name,
        parsed.folder,
        request.get("simulation_duration_s"),
        "cigre_lcc_monopole_v1",
        parsed,
    )


def _mmc_args(
    request: dict[str, Any],
) -> tuple[str, str | None, float | None, str, BlankMmcRequest]:
    parsed = BlankMmcRequest.from_dict(request)
    return (
        parsed.project_name,
        parsed.folder,
        request.get("simulation_duration_s"),
        "cigre_b4_p2p_avm_v1",
        parsed,
    )


async def plan_blank_lcc_model(request: dict[str, Any]) -> dict[str, Any]:
    """Plan a blank-project LCC model build without changing the workspace."""
    project, folder, duration, blueprint, parsed = _lcc_args(request)
    kwargs: dict[str, Any] = {"request": parsed}
    if parsed.template_path is not None:
        kwargs["template_path"] = parsed.template_path
    result = _lcc_service().plan_model(project, folder, duration, blueprint, **kwargs)
    result["blank_request"] = parsed.to_dict()
    fault = result.get("fault")
    result["fault_events"] = [
        {
            "kind": fault.get("kind", "inverter_ac_disturbance"),
            "time_s": fault.get("time_s", 0.5),
            "duration_s": fault.get("duration_s", 0.1),
        }
        if isinstance(fault, dict)
        else {"kind": "inverter_ac_disturbance", "time_s": 0.5, "duration_s": 0.1}
    ]
    return result


async def build_blank_lcc_model(
    request: dict[str, Any], expected_plan_hash: str, confirm: bool = False
) -> dict[str, Any]:
    """Start a confirmed blank-project LCC model build."""
    project, folder, duration, blueprint, parsed = _lcc_args(request)
    kwargs: dict[str, Any] = {"request": parsed}
    if parsed.template_path is not None:
        kwargs["template_path"] = parsed.template_path
    return await _lcc_service().build_model(
        project,
        expected_plan_hash,
        folder,
        duration,
        blueprint,
        confirm,
        **kwargs,
    )


async def get_blank_lcc_build_status(build_id: str) -> dict[str, Any]:
    """Get blank-project LCC build status."""
    return _lcc_service().get_build_status(build_id)


async def validate_blank_lcc_model(
    project_name: str,
    blueprint: str = "cigre_lcc_monopole_v1",
    output_file: str | None = None,
    template_path: str | None = None,
) -> dict[str, Any]:
    """Validate a blank-project LCC model."""
    return _lcc_service().validate_model(
        project_name,
        blueprint,
        output_file,
        template_path=template_path,
    )


async def plan_blank_mmc_model(request: dict[str, Any]) -> dict[str, Any]:
    """Plan a blank-project MMC model build without changing the workspace."""
    _project, folder, duration, blueprint, parsed = _mmc_args(request)
    result = _mmc_service().plan_model(
        parsed,
        folder=folder,
        simulation_duration_s=duration,
        blueprint=blueprint,
    )
    result["blank_request"] = parsed.to_dict()
    result["capabilities"] = {
        **(
            dict(result.get("capabilities", {}))
            if isinstance(result.get("capabilities"), dict)
            else {}
        ),
        **parsed.submodule_topology.capabilities(parsed.submodule_topology),
    }
    fault = result.get("fault")
    result["fault_events"] = [
        {
            "kind": fault.get("kind", "dc_pole_to_pole"),
            "time_s": fault.get("time_s", 0.3),
            "removal_time_s": fault.get("removal_time_s", 0.5),
        }
        if isinstance(fault, dict)
        else {"kind": "dc_pole_to_pole", "time_s": 0.3, "removal_time_s": 0.5}
    ]
    return result


async def build_blank_mmc_model(
    request: dict[str, Any], expected_plan_hash: str, confirm: bool = False
) -> dict[str, Any]:
    """Start a confirmed blank-project MMC model build."""
    _project, folder, duration, blueprint, parsed = _mmc_args(request)
    return await _mmc_service().build_model(
        parsed,
        expected_plan_hash,
        folder=folder,
        simulation_duration_s=duration,
        blueprint=blueprint,
        template_path=parsed.template_path,
        library_path=parsed.library_path,
        confirm=confirm,
    )


async def get_blank_mmc_build_status(build_id: str) -> dict[str, Any]:
    """Get blank-project MMC build status."""
    return _mmc_service().get_build_status(build_id)


async def validate_blank_mmc_model(
    project_name: str,
    blueprint: str = "cigre_b4_p2p_avm_v1",
    output_file: str | None = None,
    template_path: str | None = None,
    library_path: str | None = None,
) -> dict[str, Any]:
    """Validate a blank-project MMC model."""
    return _mmc_service().validate_model(
        project_name,
        blueprint,
        output_file,
        template_path=template_path,
        library_path=library_path,
    )


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


async def shutdown_blank_builder_services(timeout_s: float = 5.0) -> None:
    """Close initialized blank-builder singletons without creating new ones."""

    global _lcc_instance, _mmc_instance, _backend
    failures: list[BaseException] = []
    lcc_service = _lcc_instance
    mmc_service = _mmc_instance
    for service in (lcc_service, mmc_service):
        if service is None:
            continue
        shutdown = getattr(service, "shutdown", None)
        try:
            if callable(shutdown):
                await shutdown(timeout_s=timeout_s)
        except BaseException as error:  # noqa: BLE001 - report cleanup after attempting both services
            failures.append(error)
        else:
            if service is lcc_service:
                _lcc_instance = None
            elif service is mmc_service:
                _mmc_instance = None
    if _lcc_instance is None and _mmc_instance is None:
        _backend = None
    if failures:
        raise failures[0]


__all__ = ["register_blank_builder_tools", "shutdown_blank_builder_services"]
