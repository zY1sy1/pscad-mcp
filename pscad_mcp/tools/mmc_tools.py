"""MCP wrappers for the parameterized dual-engine MMC lifecycle."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.connection_manager import pscad_manager
from ..hvdc.builders.mmc.parametric_models import (
    MmcParametricRequest,
    parse_parametric_request,
)
from ..hvdc.builders.mmc.parametric_service import ParametricMmcBuilderService
from ..hvdc.service import HvdcDomainService
from .registration import register_tool


_service_instance: ParametricMmcBuilderService | None = None
_service_backend: Any = None


def _service() -> ParametricMmcBuilderService:
    global _service_instance, _service_backend
    backend = pscad_manager.service
    if _service_instance is None or backend is not _service_backend:
        _service_backend = backend
        path_policy = getattr(backend, "path_policy", None)
        workspace_root = getattr(path_policy, "workspace_root", None)
        scenario_service = HvdcDomainService(backend, path_policy=path_policy)
        _service_instance = ParametricMmcBuilderService(
            backend,
            workspace_root=workspace_root,
            scenario_service=scenario_service,
        )
    return _service_instance


def _request(
    value: MmcParametricRequest | dict[str, Any],
) -> MmcParametricRequest:
    return value if isinstance(value, MmcParametricRequest) else parse_parametric_request(value)


async def audit_mmc_template(
    template_path: str | None = None,
    library_path: str | None = None,
) -> dict[str, Any]:
    return _service().audit_template(template_path, library_path)


async def derive_mmc_parameters(request: dict[str, Any]) -> dict[str, Any]:
    return _service().derive_parameters(_request(request))


async def plan_parametric_mmc_model(
    request: dict[str, Any],
    project_name: str,
    folder: str,
    template_path: str | None = None,
    library_path: str | None = None,
) -> dict[str, Any]:
    return _service().plan_model(
        _request(request),
        project_name,
        folder,
        template_path=template_path,
        library_path=library_path,
    )


async def build_parametric_mmc_model(
    request: dict[str, Any],
    expected_plan_hash: str,
    project_name: str,
    folder: str,
    template_path: str | None = None,
    library_path: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    return await _service().build_model(
        _request(request),
        expected_plan_hash,
        project_name,
        folder,
        template_path=template_path,
        library_path=library_path,
        confirm=confirm,
    )


async def get_parametric_mmc_build_status(build_id: str) -> dict[str, Any]:
    return _service().get_status(build_id)


async def recommend_mmc_simulation(
    request_or_project: dict[str, Any] | str,
    objectives: list[str] | None = None,
) -> dict[str, Any]:
    value: MmcParametricRequest | str = (
        _request(request_or_project)
        if isinstance(request_or_project, dict)
        else request_or_project
    )
    return _service().recommend_simulation(value, objectives)


async def validate_mmc_model(
    project_name: str,
    model_fidelity: str,
    output_files: list[str] | None = None,
    acceptance_scope: str = "full",
) -> dict[str, Any]:
    return _service().validate_model(
        project_name,
        model_fidelity,
        output_files=output_files,
        acceptance_scope=acceptance_scope,
    )


def register_mmc_tools(mcp: FastMCP) -> None:
    for function in (
        audit_mmc_template,
        derive_mmc_parameters,
        plan_parametric_mmc_model,
        build_parametric_mmc_model,
        get_parametric_mmc_build_status,
        recommend_mmc_simulation,
        validate_mmc_model,
    ):
        register_tool(mcp, function)


__all__ = ["register_mmc_tools"]
