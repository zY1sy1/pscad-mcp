"""MCP registrations for the isolated HVDC domain layer."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.connection_manager import pscad_manager
from ..hvdc.service import HvdcDomainService
from .registration import register_tool


_domain_service: HvdcDomainService | None = None
_domain_backend: Any = None


def _service() -> HvdcDomainService:
    global _domain_service, _domain_backend
    backend = pscad_manager.service
    if _domain_service is None or backend is not _domain_backend:
        _domain_backend = backend
        _domain_service = HvdcDomainService(backend, path_policy=getattr(backend, "path_policy", None))
    return _domain_service


async def inspect_hvdc_project(project_name: str, canvas_name: str = "Main") -> dict[str, Any]:
    return await _service().inspect_live_project(project_name, canvas_name)


async def get_hvdc_assets(project_name: str, kind: str | None = None) -> list[dict[str, Any]]:
    return await _service().get_live_assets(project_name, kind)


async def get_hvdc_mappings(project_name: str, canonical: str | None = None) -> dict[str, Any]:
    return await _service().get_live_mappings(project_name, canonical)


async def validate_hvdc_project(project_name: str, profile: str = "auto") -> dict[str, Any]:
    return await _service().validate_live_project(project_name, profile)


async def run_hvdc_scenario(project_name: str, scenario: dict[str, Any], confirm: bool = False) -> dict[str, Any]:
    return await _service().run_scenario(project_name, scenario, confirm=confirm)


async def get_hvdc_scenario_status(scenario_id: str) -> dict[str, Any]:
    return await _service().scenario_status(scenario_id)


async def analyze_hvdc_results(scenario_id: str, metrics: list[str] | None = None) -> dict[str, Any]:
    return await _service().analyze_results(scenario_id, metrics)


async def compare_hvdc_scenarios(scenario_ids: list[str], metrics: list[str] | None = None) -> dict[str, Any]:
    return await _service().compare_scenarios(scenario_ids, metrics)


async def list_hvdc_profiles() -> list[dict[str, Any]]:
    return _service().list_profiles()


async def register_hvdc_profile(profile_name: str, mapping_file: str, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        from ..core.service import ConfirmationRequired
        raise ConfirmationRequired("register_hvdc_profile")
    return _service().register_profile(profile_name, mapping_file)


def register_hvdc_tools(mcp: FastMCP) -> None:
    for function in (
        inspect_hvdc_project, get_hvdc_assets, get_hvdc_mappings,
        validate_hvdc_project, run_hvdc_scenario, get_hvdc_scenario_status,
        analyze_hvdc_results, compare_hvdc_scenarios, list_hvdc_profiles,
        register_hvdc_profile,
    ):
        register_tool(mcp, function)
