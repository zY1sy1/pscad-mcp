"""MCP wrappers for parameterized LCC modeling."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.connection_manager import pscad_manager
from ..hvdc.builders.lcc.parametric_models import ParametricLccRequest
from ..hvdc.builders.lcc.parametric_service import ParametricLccBuilderService
from ..hvdc.builders.lcc.schema import parse_parametric_request
from .registration import register_tool

_service_instance: ParametricLccBuilderService | None = None
_service_backend: Any = None


def _service() -> ParametricLccBuilderService:
    global _service_instance, _service_backend
    backend = pscad_manager.service
    if _service_instance is None or backend is not _service_backend:
        _service_backend = backend
        path_policy = getattr(backend, "path_policy", None)
        workspace_root = getattr(path_policy, "workspace_root", None)
        _service_instance = ParametricLccBuilderService(
            backend,
            workspace_root=workspace_root,
        )
    return _service_instance


def _request(value: ParametricLccRequest | dict[str, Any]) -> ParametricLccRequest:
    return value if isinstance(value, ParametricLccRequest) else parse_parametric_request(value)


async def derive_lcc_parameters(request: dict[str, Any]) -> dict[str, Any]:
    return _service().derive_parameters(_request(request))


async def audit_lcc_template(template_path: str) -> dict[str, Any]:
    return _service().audit_template(template_path)


async def plan_parametric_lcc_model(
    request: dict[str, Any],
    template_path: str,
    project_name: str,
    folder: str,
) -> dict[str, Any]:
    return _service().plan_parametric_model(
        _request(request),
        template_path=template_path,
        project_name=project_name,
        folder=folder,
    )


async def build_parametric_lcc_model(
    request: dict[str, Any],
    expected_plan_hash: str,
    template_path: str,
    project_name: str,
    folder: str,
    confirm: bool = False,
) -> dict[str, Any]:
    return await _service().build_parametric_model(
        _request(request),
        template_path=template_path,
        project_name=project_name,
        folder=folder,
        expected_plan_hash=expected_plan_hash,
        confirm=confirm,
    )


async def get_parametric_lcc_build_status(build_id: str) -> dict[str, Any]:
    return _service().get_status(build_id)


async def validate_lcc_operating_modes(events: list[dict[str, Any]]) -> dict[str, Any]:
    return _service().validate_operating_modes(events)


def register_lcc_parametric_tools(mcp: FastMCP) -> None:
    for function in (derive_lcc_parameters, audit_lcc_template, plan_parametric_lcc_model, build_parametric_lcc_model, get_parametric_lcc_build_status, validate_lcc_operating_modes):
        register_tool(mcp, function)


__all__ = ["register_lcc_parametric_tools"]
