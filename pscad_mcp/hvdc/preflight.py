"""Side-effect ordering and output readiness checks for HVDC scenarios."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..core.backend.base import BackendError
from .bindings import (
    _UNSAFE_COMMAND_PARAMETERS,
    _normalized_parameter_name,
    matching_fingerprints,
    resolve_requested_commands,
)
from .mappings import resolve_mappings
from .scanner import scan_project
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
    requested = [str(metric) for metric in requested_metrics]
    if profile.get("profile_version", 1) == 2:
        selector_names = {
            str(item.get("canonical"))
            for item in selectors
            if isinstance(item, Mapping) and item.get("canonical")
        }
        for metric in requested:
            if not isinstance(roles, Mapping) or metric not in roles:
                raise _error(
                    "HVDC_MAPPING_MISSING",
                    f"Profile metric '{metric}' has no explicit result selector role.",
                    metric=metric,
                )
            canonical = roles[metric]
            if canonical not in selector_names:
                raise _error(
                    "HVDC_MAPPING_MISSING",
                    f"Metric '{metric}' points to undefined result selector '{canonical}'.",
                    metric=metric,
                    canonical=canonical,
                )
    needed = {roles[metric] for metric in requested if isinstance(roles, Mapping) and metric in roles}
    if not needed:
        return [dict(selector) for selector in selectors if isinstance(selector, Mapping)]
    return [dict(selector) for selector in selectors if isinstance(selector, Mapping) and selector.get("canonical") in needed]


async def verify_required_result_selectors(
    backend: Any,
    project_name: str,
    profile: Mapping[str, Any],
    requested_metrics: Sequence[str],
) -> dict[str, Any]:
    """Verify requested v2 selectors against backend-provided output metadata."""

    required = required_result_selectors(profile, requested_metrics)
    if profile.get("profile_version", 1) != 2 or not required:
        return {"verified": True, "required": []}

    provider = next(
        (
            getattr(backend, name, None)
            for name in ("get_output_channels", "inspect_output_channels", "get_project_output_channels")
            if callable(getattr(backend, name, None))
        ),
        None,
    )
    if provider is None:
        raise _error(
            "HVDC_CAPABILITY_UNAVAILABLE",
            "The backend cannot inspect output channel metadata before a scenario run.",
            project_name=project_name,
            reason="output_channel_inspection_unavailable",
        )
    try:
        observed = await provider(project_name)
    except BackendError:
        raise
    except Exception as error:
        raise _error(
            "HVDC_CAPABILITY_UNAVAILABLE",
            f"Output channel inspection failed: {error}",
            project_name=project_name,
            reason="output_channel_inspection_failed",
        ) from error
    if isinstance(observed, Mapping):
        observed = observed.get("channels", observed.get("output_channels", []))
    if not isinstance(observed, (list, tuple)):
        raise _error(
            "HVDC_CAPABILITY_UNAVAILABLE",
            "Output channel inspection returned an invalid channel collection.",
            project_name=project_name,
            reason="output_channel_inspection_invalid",
        )

    normalized = [dict(item) for item in observed if isinstance(item, Mapping)]
    matches: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for selector in required:
        selector_path = str(selector.get("path", "")).casefold()
        candidates = [
            item
            for item in normalized
            if str(item.get("path", "")).casefold() == selector_path
            and (selector.get("call_id") is None or item.get("call_id") == selector.get("call_id"))
            and (selector.get("units") is None or str(item.get("units", "")).casefold() == str(selector.get("units")).casefold())
        ]
        evidence = {
            "canonical": selector.get("canonical"),
            "selector": dict(selector),
            "candidates": candidates,
        }
        if len(candidates) != 1:
            missing.append(evidence)
        else:
            matches.append({**evidence, "observed": candidates[0]})
    if missing:
        raise _error(
            "HVDC_MAPPING_MISSING",
            "One or more required result selectors are absent or ambiguous in the target output definitions.",
            project_name=project_name,
            reason="required_result_selector_unresolved",
            unresolved=missing,
        )
    return {"verified": True, "required": matches}


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
    try:
        evidence = scan_project(service._resolve_project(target_project))
    except BackendError:
        raise
    except Exception as error:
        raise _error(
            "HVDC_MAPPING_MISSING",
            f"Unable to scan the target project before mutation: {error}",
            project_name=target_project,
        ) from error
    fingerprints = matching_fingerprints(evidence, profile)
    if profile.get("project_fingerprints") and not fingerprints:
        raise _error(
            "HVDC_MAPPING_MISSING",
            "No configured project fingerprint matches the target project.",
            project_name=target_project,
            reason="project_fingerprint_mismatch",
        )
    requests = [item for field in ("parameter_changes", "events") for item in normalized.get(field, [])]
    if requests and profile.get("profile_version", 1) == 1:
        # Version 1 profiles remain readable for existing users. Their command
        # mappings are still resolved against this exact target evidence and
        # never participate in v2 binding inference.
        legacy = resolve_mappings(evidence, profile)
        by_canonical = {item.canonical: item for item in legacy.mappings}
        commands: list[dict[str, Any]] = []
        for index, request in enumerate(requests):
            canonical = request.get("target", request.get("canonical"))
            mapping = by_canonical.get(canonical)
            source = mapping.source if mapping and mapping.status == "observed" else None
            if mapping is None or mapping.direction != "command":
                raise _error(
                    "HVDC_CAPABILITY_UNAVAILABLE",
                    f"Scenario target '{canonical}' is not an approved v1 command mapping.",
                    target=canonical,
                    direction=mapping.direction if mapping else "measurement",
                    index=index,
                )
            if source is None or not source.component_id or not source.parameter_name:
                raise _error(
                    "HVDC_MAPPING_MISSING",
                    f"Command target '{canonical}' has no unique observed component parameter.",
                    target=canonical,
                    index=index,
                )
            if _normalized_parameter_name(source.parameter_name) in _UNSAFE_COMMAND_PARAMETERS:
                raise _error(
                    "HVDC_MAPPING_MISSING",
                    f"Command target '{canonical}' resolved to unsafe metadata.",
                    target=canonical,
                    component_id=str(source.component_id),
                    parameter_name=source.parameter_name,
                    reason="unsafe_command_parameter",
                    index=index,
                )
            semantic_names = {
                _normalized_parameter_name(str(canonical)),
                *(_normalized_parameter_name(str(alias)) for alias in next(
                    (item.get("aliases", []) for item in profile.get("mappings", []) if item.get("canonical") == canonical),
                    []
                )),
            }
            if _normalized_parameter_name(source.parameter_name) not in semantic_names:
                raise _error(
                    "HVDC_MAPPING_MISSING",
                    f"Command target '{canonical}' did not resolve to its semantic parameter name.",
                    target=canonical,
                    component_id=str(source.component_id),
                    parameter_name=source.parameter_name,
                    reason="nonsemantic_command_parameter",
                    index=index,
                )
            supplied_id = requests[index].get("component_id")
            supplied_parameter = requests[index].get("parameter_name")
            if supplied_id is not None or supplied_parameter is not None:
                if str(supplied_id) != str(source.component_id) or str(supplied_parameter) != str(source.parameter_name):
                    raise _error(
                        "HVDC_MAPPING_MISSING",
                        f"Explicit binding for '{canonical}' does not match the observed v1 mapping.",
                        target=canonical,
                        approved_source={"component_id": str(source.component_id), "parameter_name": source.parameter_name},
                        index=index,
                    )
            commands.append({
                "canonical": str(canonical),
                "component_id": str(source.component_id),
                "parameter_name": source.parameter_name,
                "old_value": None,
                "semantics": mapping.direction,
                "read_back": True,
                "matched_fingerprint": fingerprints[0] if fingerprints else {},
            })
    else:
        commands = resolve_requested_commands(evidence, profile, requests) if requests else []
    timing_mode = await select_timing_mode(service.backend_service, target_project) if normalized.get("events") else None
    requested_metrics = normalized.get("analysis", {}).get("metrics", [])
    selectors = required_result_selectors(profile, requested_metrics)
    selector_check = await verify_required_result_selectors(
        service.backend_service,
        target_project,
        profile,
        requested_metrics,
    )
    get_settings = getattr(service.backend_service, "get_project_settings", None)
    if callable(get_settings):
        output = await ensure_output_ready(
            service.backend_service,
            target_project,
            source_project=source_project,
            confirm=confirm,
        )
    elif profile.get("profile_version", 1) == 1:
        output = {"changed": False, "verified": False, "reason": "project_settings_unavailable"}
    else:
        raise _error(
            "HVDC_CAPABILITY_UNAVAILABLE",
            "Project settings read-back is required before a v2 scenario can run.",
            project_name=target_project,
        )
    return {
        "resolved_commands": commands,
        "timing_mode": timing_mode,
        "output_change": output,
        "required_result_selectors": selectors,
        "result_channel_check": selector_check,
        "matched_fingerprint": fingerprints[0] if fingerprints else {},
    }
