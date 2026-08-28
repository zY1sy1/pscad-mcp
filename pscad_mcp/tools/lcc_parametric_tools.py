"""MCP wrappers for parameterized LCC modeling."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..core.connection_manager import pscad_manager
from ..hvdc.builders.lcc.parametric_models import ParametricLccRequest
from ..hvdc.builders.lcc.parametric_service import ParametricLccBuilderService
from ..hvdc.builders.lcc.schema import parse_parametric_request
from .registration import register_tool

ParametricLccInput = Annotated[
    Dict[str, Any],
    Field(
        description=(
            'Keys topology, ratings, engineering_overrides, operation_modes, '
            'return_path_assets, mode_requests, and template_mappings; example '
            '{"topology":"bipolar","ratings":{"rated_power_mw":1000,'
            '"dc_voltage_kv":500,"dc_current_ka":2,"ac_voltage_kv":230,'
            '"frequency_hz":50,"scr":3},"engineering_overrides":'
            '{"base_mva":1000}}.'
        )
    ),
]
OperatingModeEvents = Annotated[
    List[Dict[str, Any]],
    Field(
        description=(
            'Ordered events with event_id, time_s, target, and value; example '
            '[{"event_id":"e1","time_s":0.5,"target":"operating_mode",'
            '"value":"monopolar_earth_return"}].'
        )
    ),
]

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


async def shutdown_parametric_lcc_builder_service(
    timeout_s: float = 5.0,
) -> None:
    """Close the existing parametric singleton without initializing it."""
    global _service_instance, _service_backend
    service = _service_instance
    if service is None:
        return
    await service.shutdown(timeout_s=timeout_s)
    if _service_instance is service:
        _service_instance = None
        _service_backend = None


def _request(value: ParametricLccRequest | dict[str, Any]) -> ParametricLccRequest:
    return value if isinstance(value, ParametricLccRequest) else parse_parametric_request(value)


async def derive_lcc_parameters(request: ParametricLccInput) -> dict[str, Any]:
    """Derive deterministic LCC design parameters from a parametric request."""
    return _service().derive_parameters(_request(request))


async def audit_lcc_template(template_path: str) -> dict[str, Any]:
    """Audit an LCC template and report binding evidence without modifying it."""
    return _service().audit_template(template_path)


async def plan_parametric_lcc_model(
    request: ParametricLccInput,
    template_path: str,
    project_name: str,
    folder: str,
) -> dict[str, Any]:
    """Plan a parameterized LCC model build without changing the workspace."""
    return _service().plan_parametric_model(
        _request(request),
        template_path=template_path,
        project_name=project_name,
        folder=folder,
    )


async def build_parametric_lcc_model(
    request: ParametricLccInput,
    expected_plan_hash: str,
    template_path: str,
    project_name: str,
    folder: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """Start a confirmed parameterized LCC build from a matching plan."""
    return await _service().build_parametric_model(
        _request(request),
        template_path=template_path,
        project_name=project_name,
        folder=folder,
        expected_plan_hash=expected_plan_hash,
        confirm=confirm,
    )


async def get_parametric_lcc_build_status(build_id: str) -> dict[str, Any]:
    """Get the current status and evidence for a parameterized LCC build."""
    return _service().get_status(build_id)


async def validate_lcc_operating_modes(events: OperatingModeEvents) -> dict[str, Any]:
    """Validate an ordered schedule of LCC operating-mode events."""
    return _service().validate_operating_modes(events)


def register_lcc_parametric_tools(mcp: FastMCP) -> None:
    for function in (derive_lcc_parameters, audit_lcc_template, plan_parametric_lcc_model, build_parametric_lcc_model, get_parametric_lcc_build_status, validate_lcc_operating_modes):
        register_tool(mcp, function)


__all__ = [
    "register_lcc_parametric_tools",
    "shutdown_parametric_lcc_builder_service",
]
