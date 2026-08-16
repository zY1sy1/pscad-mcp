"""Declarative HVDC scenario validation and safe execution."""

from __future__ import annotations

import math
import asyncio
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any

from ..core.backend.base import BackendError
from ..core.service import ConfirmationRequired
from .profiles import load_profile


_UNSUPPORTED_TARGETS = {"insert_fault", "add_component", "rewire", "insert_breaker"}
_MAX_TIMEOUT_S = 86_400.0
_TERMINAL_PROJECT_STATUSES = {"completed", "complete", "finished", "done", "idle", "stopped"}
_FAILED_PROJECT_STATUSES = {"failed", "error", "aborted"}
_TRANSITIONS = {
    "validated": {"running", "failed", "timed_out", "completed"},
    "running": {"completed", "failed", "timed_out"},
    "completed": set(),
    "failed": set(),
    "timed_out": set(),
}


def _error(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def transition_scenario(record: dict[str, Any], status: str) -> None:
    current = str(record.get("status"))
    if status == current:
        return
    if status not in _TRANSITIONS.get(current, set()):
        raise RuntimeError(f"Invalid HVDC scenario transition: {current} -> {status}")
    record["status"] = status
    record.setdefault("status_history", []).append({"status": status, "at": _utc_now()})
    if status in {"completed", "failed", "timed_out"}:
        record["finished_at"] = _utc_now()


def _is_path_like(value: str) -> bool:
    path = Path(value).expanduser()
    return path.is_absolute() or path.suffix.lower() == ".pscx" or "/" in value or "\\" in value


def _logical_project_key(value: str) -> str:
    name = Path(value.strip()).name
    if name.casefold().endswith(".pscx"):
        name = name[:-5]
    return name.casefold()


def _path_key(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).expanduser().resolve())).casefold()


async def _resolve_target_project(service: Any, source_project: str, derived_project: str) -> str:
    if _is_path_like(derived_project):
        resolved = service._resolve_mutation_project(derived_project)
        if (
            _path_key(resolved) == _path_key(source_project)
            or _logical_project_key(str(resolved)) == _logical_project_key(source_project)
        ):
            raise BackendError(
                "HVDC_SCENARIO_INVALID",
                "derived_project must be distinct from the source project.",
                "hvdc",
                "run_hvdc_scenario",
                {"project": source_project, "derived_project": derived_project, "reason": "source_and_target_match"},
            )
        return str(resolved)
    if _logical_project_key(derived_project) == _logical_project_key(source_project):
        raise BackendError(
            "HVDC_SCENARIO_INVALID",
            "derived_project must be distinct from the source project.",
            "hvdc",
            "run_hvdc_scenario",
            {"project": source_project, "derived_project": derived_project, "reason": "source_and_target_match"},
        )
    backend = getattr(service, "backend_service", None)
    if backend is None or not callable(getattr(backend, "list_projects", None)):
        raise BackendError(
            "HVDC_CAPABILITY_UNAVAILABLE",
            "A logical derived_project can only be verified against a connected PSCAD project list.",
            "hvdc",
            "run_hvdc_scenario",
            {"derived_project": derived_project, "suggested_action": "Load the derived project before running the scenario."},
        )
    projects = await backend.list_projects()
    loaded = {
        _logical_project_key(str(item.get("name", "") if isinstance(item, Mapping) else getattr(item, "name", "")))
        for item in projects
    }
    if _logical_project_key(derived_project) not in loaded:
        raise BackendError(
            "NOT_FOUND",
            f"HVDC target project '{derived_project}' is not loaded.",
            "hvdc",
            "run_hvdc_scenario",
            {"candidate": derived_project, "suggested_action": "Load the pre-existing derived project before running the scenario."},
        )
    return derived_project


def _bind_approved_commands(service: Any, project_name: str, normalized: dict[str, Any], workspace_root: str | Path | None) -> None:
    profile = load_profile(str(normalized["profile"]), workspace_root=workspace_root)
    configured = {str(item["canonical"]): item for item in profile.get("mappings", [])}
    resolution = service.resolve_scenario_mappings(project_name, str(normalized["profile"]))
    observed = {str(item["canonical"]): item for item in resolution.get("mappings", [])}
    for field in ("parameter_changes", "events"):
        for index, item in enumerate(normalized[field]):
            target = str(item.get("target", ""))
            approved = configured.get(target)
            if approved is None:
                raise BackendError(
                    "HVDC_CAPABILITY_UNAVAILABLE",
                    f"Scenario target '{target}' is not canonical in profile '{normalized['profile']}'.",
                    "hvdc",
                    "run_hvdc_scenario",
                    {"target": target, "profile": normalized["profile"], "field": field, "index": index},
                )
            direction = approved.get("direction", "measurement")
            if direction != "command":
                raise BackendError(
                    "HVDC_CAPABILITY_UNAVAILABLE",
                    f"Scenario target '{target}' is not an approved command mapping.",
                    "hvdc",
                    "run_hvdc_scenario",
                    {"target": target, "profile": normalized["profile"], "direction": direction, "field": field, "index": index},
                )
            mapping = observed.get(target)
            source = mapping.get("source") if mapping and mapping.get("status") == "observed" else None
            if not source or source.get("component_id") in (None, "") or not source.get("parameter_name"):
                raise BackendError(
                    "HVDC_MAPPING_MISSING",
                    f"Command target '{target}' has no observed, non-conflicting component parameter mapping.",
                    "hvdc",
                    "run_hvdc_scenario",
                    {"target": target, "profile": normalized["profile"], "mapping_status": mapping.get("status") if mapping else "unresolved", "field": field, "index": index},
                )
            approved_source = {
                "component_id": str(source["component_id"]),
                "parameter_name": str(source["parameter_name"]),
            }
            supplied_id = item.get("component_id")
            supplied_parameter = item.get("parameter_name")
            if supplied_id is not None or supplied_parameter is not None:
                matches = (
                    supplied_id is not None
                    and supplied_parameter is not None
                    and str(supplied_id) == approved_source["component_id"]
                    and str(supplied_parameter) == approved_source["parameter_name"]
                )
                if not matches:
                    raise BackendError(
                        "HVDC_MAPPING_MISSING",
                        f"Explicit binding for '{target}' does not match the approved observed mapping source.",
                        "hvdc",
                        "run_hvdc_scenario",
                        {"target": target, "approved_source": approved_source, "field": field, "index": index},
                    )
            item["component_id"] = approved_source["component_id"]
            item["parameter_name"] = approved_source["parameter_name"]


def validate_scenario(scenario: Mapping[str, Any], *, workspace_root: str | Path | None = None) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if not isinstance(scenario, Mapping):
        return {"valid": False, "errors": [_error("HVDC_SCENARIO_INVALID", "scenario must be an object.")], "warnings": []}
    name = scenario.get("name")
    profile = scenario.get("profile")
    project = scenario.get("project")
    if not isinstance(name, str) or not name.strip():
        errors.append(_error("HVDC_SCENARIO_INVALID", "name must be a non-empty string.", field="name"))
    if not isinstance(profile, str) or not profile.strip():
        errors.append(_error("HVDC_SCENARIO_INVALID", "profile must be a non-empty string.", field="profile"))
    else:
        try:
            load_profile(profile, workspace_root=workspace_root)
        except BackendError as error:
            errors.append(_error(error.code, str(error), profile=profile))
    if not isinstance(project, str) or not project.strip():
        errors.append(_error("HVDC_SCENARIO_INVALID", "project must be a non-empty string.", field="project"))
    for field in ("parameter_changes", "events"):
        values = scenario.get(field, [])
        if not isinstance(values, list):
            errors.append(_error("HVDC_SCENARIO_INVALID", f"{field} must be a list.", field=field))
            continue
        for index, event in enumerate(values):
            if not isinstance(event, Mapping):
                errors.append(_error("HVDC_SCENARIO_INVALID", f"{field}[{index}] must be an object.", field=field, index=index))
                continue
            if field == "events":
                time_s = event.get("time_s")
                if isinstance(time_s, bool) or not isinstance(time_s, (int, float)) or not math.isfinite(float(time_s)) or float(time_s) < 0:
                    errors.append(_error("HVDC_SCENARIO_INVALID", "event time_s must be a finite non-negative number.", field=field, index=index))
            target = event.get("target")
            if not isinstance(target, str) or not target.strip():
                errors.append(_error("HVDC_SCENARIO_INVALID", "scenario target must be a non-empty string.", field=field, index=index))
            elif target in _UNSUPPORTED_TARGETS:
                errors.append(_error("HVDC_CAPABILITY_UNAVAILABLE", f"Scenario target '{target}' is not supported.", target=target, field=field, index=index))
    run = scenario.get("run", {})
    if run is not None and not isinstance(run, Mapping):
        errors.append(_error("HVDC_SCENARIO_INVALID", "run must be an object.", field="run"))
    elif isinstance(run, Mapping):
        timeout_s = run.get("timeout_s", 300)
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(float(timeout_s))
            or not 0 < float(timeout_s) <= _MAX_TIMEOUT_S
        ):
            errors.append(
                _error(
                    "HVDC_SCENARIO_INVALID",
                    f"run.timeout_s must be a finite number greater than 0 and no greater than {_MAX_TIMEOUT_S:g}.",
                    field="run.timeout_s",
                )
            )
    output_files = scenario.get("output_files", [])
    if not isinstance(output_files, list) or any(not isinstance(item, str) or not item.strip() for item in output_files):
        errors.append(_error("HVDC_SCENARIO_INVALID", "output_files must be a list of non-empty strings.", field="output_files"))
    return {"valid": not errors, "errors": errors, "warnings": []}


def _serialize_execution_error(error: BaseException) -> dict[str, Any]:
    if isinstance(error, BackendError):
        return error.to_dict()
    return BackendError(
        "HVDC_SCENARIO_FAILED",
        str(error),
        "hvdc",
        "run_hvdc_scenario",
        {"exception_type": type(error).__name__},
    ).to_dict()


async def _wait_for_project_terminal(backend: Any, target_project: str) -> None:
    get_status = getattr(backend, "get_run_status", None)
    if not callable(get_status):
        return
    while True:
        state = await get_status(target_project)
        if not isinstance(state, Mapping):
            return
        status = str(state.get("status", "")).casefold()
        if status in _TERMINAL_PROJECT_STATUSES:
            return
        if status in _FAILED_PROJECT_STATUSES:
            raise BackendError(
                "HVDC_SCENARIO_RUN_FAILED",
                f"PSCAD project '{target_project}' reported terminal status '{status}'.",
                "hvdc",
                "run_hvdc_scenario",
                {"project_name": target_project, "project_status": dict(state)},
            )
        await asyncio.sleep(0.1)


async def _capture_outputs(service: Any, record: dict[str, Any]) -> None:
    backend = service.backend_service
    discover = None
    for name in ("list_output_files", "discover_output_files", "get_output_files"):
        candidate = getattr(backend, name, None)
        if callable(candidate):
            discover = candidate
            break
    if discover is None:
        record["output_discovery"] = "unavailable"
        record["warnings"].append(
            {
                "code": "OUTPUT_DISCOVERY_UNAVAILABLE",
                "message": "The backend cannot discover output files; only explicit policy-validated output_files are recorded.",
                "unresolved": True,
            }
        )
        return
    try:
        discovered = await discover(record["target_project"])
        if not isinstance(discovered, (list, tuple)):
            raise TypeError("output discovery must return a list of file paths")
        validated = list(record["output_files"])
        for value in discovered:
            resolved = str(service._resolve_output_file(str(value), must_exist=True))
            if resolved not in validated:
                validated.append(resolved)
        record["output_files"] = validated
        record["output_discovery"] = "backend"
    except Exception as error:
        warning: dict[str, Any] = {
            "code": "OUTPUT_DISCOVERY_FAILED",
            "message": str(error),
            "unresolved": True,
        }
        if isinstance(error, BackendError):
            warning["error"] = error.to_dict()
        record["warnings"].append(warning)
        record["output_discovery"] = "failed"


async def _orchestrate_scenario(service: Any, record: dict[str, Any], normalized: dict[str, Any]) -> None:
    backend = service.backend_service
    target_project = record["target_project"]
    transition_scenario(record, "running")
    record["started_at"] = _utc_now()
    for change in normalized.get("parameter_changes", []):
        await backend.set_component_parameters(
            target_project,
            int(change["component_id"]),
            {str(change["parameter_name"]): change.get("value")},
        )
        record["partial_completion"]["applied_parameter_changes"].append(dict(change))
    run = normalized.get("run", {}) or {}
    if run.get("simulation_set"):
        await backend.run_simulation_set(target_project, str(run["simulation_set"]))
    else:
        await backend.run_project(target_project)
    record["partial_completion"]["run_started"] = True
    try:
        previous_time = 0.0
        for event in sorted(normalized.get("events", []), key=lambda item: float(item["time_s"])):
            event_time = float(event["time_s"])
            await asyncio.sleep(max(0.0, event_time - previous_time))
            await backend.set_component_parameters(
                target_project,
                int(event["component_id"]),
                {str(event["parameter_name"]): event.get("value")},
            )
            record["partial_completion"]["applied_events"].append(dict(event))
            previous_time = event_time
        await _wait_for_project_terminal(backend, target_project)
    except asyncio.CancelledError:
        record["warnings"].append(
            {
                "code": "OUTPUT_DISCOVERY_SKIPPED",
                "message": "Output discovery was skipped because scenario execution was cancelled or timed out.",
                "unresolved": True,
            }
        )
        record["output_discovery"] = "skipped"
        raise
    except Exception:
        await _capture_outputs(service, record)
        raise
    else:
        await _capture_outputs(service, record)


async def _scenario_worker(service: Any, record: dict[str, Any], normalized: dict[str, Any], timeout_s: float) -> None:
    try:
        await asyncio.wait_for(_orchestrate_scenario(service, record, normalized), timeout=timeout_s)
    except asyncio.TimeoutError:
        record["error"] = BackendError(
            "HVDC_SCENARIO_TIMEOUT",
            f"HVDC scenario exceeded its {timeout_s:g} second timeout.",
            "hvdc",
            "run_hvdc_scenario",
            {"scenario_id": record["scenario_id"], "timeout_s": timeout_s},
        ).to_dict()
        transition_scenario(record, "timed_out")
    except asyncio.CancelledError:
        record["error"] = BackendError(
            "HVDC_SCENARIO_CANCELLED",
            "HVDC scenario background task was cancelled.",
            "hvdc",
            "run_hvdc_scenario",
            {"scenario_id": record["scenario_id"]},
        ).to_dict()
        transition_scenario(record, "failed")
    except Exception as error:
        record["error"] = _serialize_execution_error(error)
        transition_scenario(record, "failed")
    else:
        transition_scenario(record, "completed")


async def run_scenario(
    service: Any,
    project_name: str,
    scenario: Mapping[str, Any],
    *,
    confirm: bool = False,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    normalized: dict[str, Any] = dict(scenario)
    for field in ("parameter_changes", "events"):
        raw = scenario.get(field, [])
        normalized[field] = [dict(item) if isinstance(item, Mapping) else item for item in raw] if isinstance(raw, list) else raw
    validation = validate_scenario(normalized, workspace_root=workspace_root)
    if not validation["valid"]:
        first = validation["errors"][0]
        raise BackendError(first["code"], first["message"], "hvdc", "run_hvdc_scenario", {key: value for key, value in first.items() if key not in {"code", "message"}})
    if not confirm:
        raise ConfirmationRequired("run_hvdc_scenario")
    mutating = bool(normalized.get("parameter_changes") or normalized.get("events"))
    target_project = project_name
    if mutating and not normalized.get("derived_project"):
        raise BackendError("HVDC_CAPABILITY_UNAVAILABLE", "Mutating scenarios require a pre-existing derived_project; source projects are read-only inputs.", "hvdc", "run_hvdc_scenario", {"project": project_name, "suggested_action": "Create a confirmed derived project with existing generic PSCAD tools, then pass derived_project."})
    if mutating:
        _bind_approved_commands(service, project_name, normalized, workspace_root)
        target_project = await _resolve_target_project(service, project_name, str(normalized["derived_project"]))
    elif _is_path_like(target_project):
        target_project = str(service._resolve_mutation_project(target_project))
    explicit_outputs = [
        str(service._resolve_output_file(file_path, must_exist=False))
        for file_path in normalized.get("output_files", [])
    ]
    scenario_id = f"hvdc-{uuid4().hex}"
    created_at = _utc_now()
    record: dict[str, Any] = {
        "scenario_id": scenario_id,
        "project_name": project_name,
        "target_project": target_project,
        "name": normalized["name"],
        "profile": normalized["profile"],
        "status": "validated",
        "changed_parameters": list(normalized.get("parameter_changes", [])),
        "events": list(normalized.get("events", [])),
        "output_files": explicit_outputs,
        "output_discovery": "pending",
        "resolved_channels": [],
        "metrics": [],
        "warnings": [],
        "messages": [],
        "error": None,
        "partial_completion": {
            "applied_parameter_changes": [],
            "applied_events": [],
            "run_started": False,
        },
        "created_at": created_at,
        "status_history": [{"status": "validated", "at": created_at}],
    }
    service._scenarios[scenario_id] = record
    backend = getattr(service, "backend_service", None)
    if backend is None:
        service._scenarios.pop(scenario_id, None)
        raise BackendError(
            "HVDC_CAPABILITY_UNAVAILABLE",
            "Scenario execution requires a connected PSCAD backend service.",
            "hvdc",
            "run_hvdc_scenario",
            {"project_name": target_project},
        )
    timeout_s = float((normalized.get("run") or {}).get("timeout_s", 300))
    task = asyncio.create_task(
        _scenario_worker(service, record, normalized, timeout_s),
        name=f"hvdc-scenario-{scenario_id}",
    )
    service._scenario_tasks[scenario_id] = task

    def _forget(completed: asyncio.Task[None]) -> None:
        if service._scenario_tasks.get(scenario_id) is completed:
            service._scenario_tasks.pop(scenario_id, None)
        if not completed.cancelled():
            completed.exception()

    task.add_done_callback(_forget)
    return dict(record)
