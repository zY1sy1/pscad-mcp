"""Side-effect ordering and output readiness checks for HVDC scenarios."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..core.backend.base import BackendError
from .bindings import resolve_requested_commands
from .timing import select_timing_mode


_ENABLED_OUTPUT = {"out", "legacy", "1", "true", "yes"}
_DISABLED_OUTPUT = {"none", "no", "0", "false", "off", ""}


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", "preflight_scenario", details)


def _is_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1
    return str(value).strip().casefold() in _ENABLED_OUTPUT


async def ensure_output_ready(
    backend: Any,
    target_project: str,
    *,
    source_project: str,
    confirm: bool,
) -> dict[str, Any]:
    settings = await backend.get_project_settings(target_project)
    if not isinstance(settings, Mapping) or "PlotType" not in settings:
        raise _error("HVDC_CAPABILITY_UNAVAILABLE", "Project settings do not expose PlotType.", project_name=target_project)
    previous = settings["PlotType"]
    if _is_enabled(previous):
        return {"changed": False, "previous": previous, "current": previous}
    if target_project == source_project:
        raise _error("HVDC_CAPABILITY_UNAVAILABLE", "Output correction is forbidden on the source project.", project_name=target_project)
    if not confirm:
        raise _error("HVDC_CONFIRMATION_REQUIRED", "Output correction requires explicit confirmation.", project_name=target_project)
    await backend.set_project_settings(target_project, {"PlotType": "OUT"})
    read_back = await backend.get_project_settings(target_project)
    if not isinstance(read_back, Mapping) or str(read_back.get("PlotType", "")).strip().casefold() != "out":
        raise _error(
            "HVDC_CAPABILITY_UNAVAILABLE",
            "Output setting did not read back as OUT.",
            project_name=target_project,
            requested="OUT",
            observed=read_back.get("PlotType") if isinstance(read_back, Mapping) else None,
        )
    return {"changed": True, "previous": previous, "current": "OUT"}


def required_result_selectors(profile: Mapping[str, Any], requested_metrics: Sequence[str]) -> list[dict[str, Any]]:
    selectors = profile.get("result_channels", [])
    roles = profile.get("metric_roles", {})
    needed = {roles[metric] for metric in requested_metrics if isinstance(roles, Mapping) and metric in roles}
    if not needed:
        return [dict(selector) for selector in selectors if isinstance(selector, Mapping)]
    return [dict(selector) for selector in selectors if isinstance(selector, Mapping) and selector.get("canonical") in needed]


async def preflight_scenario(
    service: Any,
    source_project: str,
    target_project: str,
    normalized: Mapping[str, Any],
    *,
    confirm: bool,
) -> dict[str, Any]:
    profile = normalized.get("profile_data") or normalized.get("profile")
    if not isinstance(profile, Mapping):
        raise _error("HVDC_PROFILE_NOT_FOUND", "Preflight requires a loaded profile mapping.")
    evidence = service.scan_hvdc_project(target_project)
    requests = [item for field in ("parameter_changes", "events") for item in normalized.get(field, [])]
    commands = resolve_requested_commands(evidence, profile, requests) if requests else []
    timing_mode = await select_timing_mode(service.backend_service, target_project) if normalized.get("events") else None
    output = await ensure_output_ready(
        service.backend_service,
        target_project,
        source_project=source_project,
        confirm=confirm,
    )
    return {
        "resolved_commands": commands,
        "timing_mode": timing_mode,
        "output_change": output,
        "required_result_selectors": required_result_selectors(profile, normalized.get("analysis", {}).get("metrics", [])),
    }
