"""Declarative HVDC scenario validation and safe execution."""

from __future__ import annotations

import math
import asyncio
import os
import time
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


async def _get_project_status(backend: Any, target_project: str) -> dict[str, Any] | None:
    get_status = getattr(backend, "get_run_status", None)
    if not callable(get_status):
        return None
    state = await get_status(target_project)
    return dict(state) if isinstance(state, Mapping) else None


async def _wait_for_project_terminal(backend: Any, target_project: str) -> dict[str, Any] | None:
    if not callable(getattr(backend, "get_run_status", None)):
        return None
    while True:
        state = await _get_project_status(backend, target_project)
        if state is None:
            return None
        status = str(state.get("status", "")).casefold()
        if status in _TERMINAL_PROJECT_STATUSES:
            return state
        if status in _FAILED_PROJECT_STATUSES:
            raise BackendError(
                "HVDC_SCENARIO_RUN_FAILED",
                f"PSCAD project '{target_project}' reported terminal status '{status}'.",
                "hvdc",
                "run_hvdc_scenario",
                {"project_name": target_project, "project_status": dict(state)},
            )
        await asyncio.sleep(0.1)


async def _attempt_containment(
    service: Any,
    record: dict[str, Any],
    *,
    timeout_s: float,
) -> bool:
    backend = service.backend_service
    target_project = record["target_project"]
    stop = None
    stop_name = None
    for name in ("stop_simulation", "stop_project"):
        candidate = getattr(backend, name, None)
        if callable(candidate):
            stop = candidate
            stop_name = name
            break
    containment_timeout = min(5.0, max(0.25, timeout_s))
    stop_record: dict[str, Any] = {"attempted": stop is not None, "operation": stop_name}
    if stop is not None:
        try:
            result = await asyncio.wait_for(stop(target_project), timeout=containment_timeout)
            stop_record["result"] = result if isinstance(result, (str, int, float, bool, dict, list, type(None))) else str(result)
        except Exception as error:
            stop_record["error"] = _serialize_execution_error(error)
    record["containment"] = {"status": "unknown", "stop": stop_record}
    get_status = getattr(backend, "get_run_status", None)
    if not callable(get_status):
        return False
    deadline = asyncio.get_running_loop().time() + containment_timeout
    while True:
        try:
            state = await asyncio.wait_for(
                _get_project_status(backend, target_project),
                timeout=max(0.01, deadline - asyncio.get_running_loop().time()),
            )
        except Exception as error:
            record["containment"]["status_error"] = _serialize_execution_error(error)
            return False
        if state is not None:
            record["project_status"] = state
            status = str(state.get("status", "")).casefold()
            if status in _TERMINAL_PROJECT_STATUSES | _FAILED_PROJECT_STATUSES:
                record["containment"] = {
                    "status": "contained",
                    "stop": stop_record,
                    "project_status": state,
                }
                return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.05)


async def _capture_outputs(service: Any, record: dict[str, Any]) -> None:
    backend = service.backend_service
    discover = getattr(backend, "discover_output_files", None)
    legacy_discover = None
    if not callable(discover):
        for name in ("list_output_files", "get_output_files"):
            candidate = getattr(backend, name, None)
            if callable(candidate):
                legacy_discover = candidate
                break
    if not callable(discover) and legacy_discover is None:
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
        if callable(discover):
            discovered = await discover(
                record["target_project"],
                started_after=float(record["run_started_at_epoch"]),
            )
            record["output_discovery"] = "service"
        else:
            discovered = await legacy_discover(record["target_project"])
            record["output_discovery"] = "backend"
        if not isinstance(discovered, (list, tuple)):
            raise TypeError("output discovery must return a list of file paths")
        validated = list(record["output_files"])
        for value in discovered:
            resolved = str(service._resolve_output_file(str(value), must_exist=True))
            if resolved not in validated:
                validated.append(resolved)
        record["output_files"] = validated
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
    run_started = asyncio.get_running_loop().time()
    record["run_started_at_epoch"] = time.time()
    record["partial_completion"]["run_command_dispatched"] = True
    if run.get("simulation_set"):
        run_task = asyncio.create_task(
            backend.run_simulation_set(target_project, str(run["simulation_set"])),
            name=f"{record['scenario_id']}-run",
        )
    else:
        run_task = asyncio.create_task(
            backend.run_project(target_project),
            name=f"{record['scenario_id']}-run",
        )
    scenario_id = record["scenario_id"]
    service._scenario_run_tasks[scenario_id] = run_task

    def _forget_run(completed: asyncio.Task[Any]) -> None:
        if service._scenario_run_tasks.get(scenario_id) is completed:
            service._scenario_run_tasks.pop(scenario_id, None)
        if not completed.cancelled():
            completed.exception()

    run_task.add_done_callback(_forget_run)
    await asyncio.sleep(0)
    record["partial_completion"]["run_started"] = "unknown"
    try:
        for event in sorted(normalized.get("events", []), key=lambda item: float(item["time_s"])):
            event_time = float(event["time_s"])
            elapsed = asyncio.get_running_loop().time() - run_started
            await asyncio.sleep(max(0.0, event_time - elapsed))
            if run_task.done():
                await asyncio.shield(run_task)
                state = await _get_project_status(backend, target_project)
                if state is None:
                    raise BackendError(
                        "HVDC_RUN_STATE_UNKNOWN",
                        "The run command returned before a timed event, but project state is unavailable.",
                        "hvdc",
                        "run_hvdc_scenario",
                        {"target": event.get("target"), "time_s": event_time},
                    )
                record["project_status"] = state
                status = str(state.get("status", "")).casefold()
                if status in _FAILED_PROJECT_STATUSES:
                    raise BackendError(
                        "HVDC_SCENARIO_RUN_FAILED",
                        f"PSCAD project '{target_project}' reported terminal status '{status}'.",
                        "hvdc",
                        "run_hvdc_scenario",
                        {"project_name": target_project, "project_status": state},
                    )
                if status in _TERMINAL_PROJECT_STATUSES:
                    raise BackendError(
                        "HVDC_EVENT_WINDOW_MISSED",
                        "The PSCAD run reached a terminal state before a timed event could be applied.",
                        "hvdc",
                        "run_hvdc_scenario",
                        {"target": event.get("target"), "time_s": event_time, "project_status": state},
                    )
                record["partial_completion"]["run_started"] = True
            await backend.set_component_parameters(
                target_project,
                int(event["component_id"]),
                {str(event["parameter_name"]): event.get("value")},
            )
            record["partial_completion"]["applied_events"].append(dict(event))
        # Keep cancellation of the bounded scenario worker separate from the
        # vendor run command. Some vendor calls do not acknowledge task
        # cancellation until an explicit stop command is issued; the worker
        # must regain control promptly so it can perform that containment.
        await asyncio.shield(run_task)
        terminal = await _wait_for_project_terminal(backend, target_project)
        if terminal is None:
            raise BackendError(
                "HVDC_RUN_STATE_UNKNOWN",
                "The backend cannot confirm that the PSCAD run reached a terminal state.",
                "hvdc",
                "run_hvdc_scenario",
                {"project_name": target_project},
            )
        record["project_status"] = terminal
        record["partial_completion"]["run_started"] = True
    except asyncio.CancelledError:
        if not run_task.done():
            run_task.cancel()
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
        if not run_task.done():
            run_task.cancel()
        await _capture_outputs(service, record)
        raise
    else:
        await _capture_outputs(service, record)


async def _scenario_worker(service: Any, record: dict[str, Any], normalized: dict[str, Any], timeout_s: float) -> None:
    release_reservation = False
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
        contained = await _attempt_containment(service, record, timeout_s=timeout_s)
        record["outcome"] = "timed_out_contained" if contained else "needs_review"
        transition_scenario(record, "timed_out")
        release_reservation = contained
    except asyncio.CancelledError:
        record["error"] = BackendError(
            "HVDC_SCENARIO_CANCELLED",
            "HVDC scenario background task was cancelled.",
            "hvdc",
            "run_hvdc_scenario",
            {"scenario_id": record["scenario_id"]},
        ).to_dict()
        contained = await _attempt_containment(service, record, timeout_s=timeout_s)
        record["outcome"] = "cancelled_contained" if contained else "needs_review"
        transition_scenario(record, "failed")
        release_reservation = contained
    except Exception as error:
        record["error"] = _serialize_execution_error(error)
        if record["partial_completion"].get("run_command_dispatched"):
            contained = await _attempt_containment(service, record, timeout_s=timeout_s)
            record["outcome"] = "failed_contained" if contained else "needs_review"
            release_reservation = contained
        else:
            record["containment"] = {"status": "not_required"}
            record["outcome"] = "failed"
            release_reservation = True
        transition_scenario(record, "failed")
    else:
        record["containment"] = {"status": "terminal", "project_status": record.get("project_status")}
        record["outcome"] = "completed"
        transition_scenario(record, "completed")
        release_reservation = True
    finally:
        if release_reservation:
            await service._release_scenario(record["scenario_id"])


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
    scenario_id = f"hvdc-{uuid4().hex}"
    await service._reserve_scenario(scenario_id)
    try:
        if mutating:
            target_project = await _resolve_target_project(service, project_name, str(normalized["derived_project"]))
        elif _is_path_like(target_project):
            target_project = str(service._resolve_mutation_project(target_project))
        explicit_outputs = [
            str(service._resolve_output_file(file_path, must_exist=False))
            for file_path in normalized.get("output_files", [])
        ]
        backend = getattr(service, "backend_service", None)
        if backend is None:
            raise BackendError(
                "HVDC_CAPABILITY_UNAVAILABLE",
                "Scenario execution requires a connected PSCAD backend service.",
                "hvdc",
                "run_hvdc_scenario",
                {"project_name": target_project},
            )
    except BaseException:
        await service._release_scenario(scenario_id)
        raise
    created_at = _utc_now()
    record: dict[str, Any] = {
        "scenario_id": scenario_id,
        "project_name": project_name,
        "target_project": target_project,
        "name": normalized["name"],
        "profile": normalized["profile"],
        "status": "validated",
        "outcome": "pending",
        "containment": {"status": "pending"},
        "reservation_held": True,
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
            "run_command_dispatched": False,
        },
        "created_at": created_at,
        "status_history": [{"status": "validated", "at": created_at}],
    }
    service._scenarios[scenario_id] = record
    timeout_s = float((normalized.get("run") or {}).get("timeout_s", 300))
    try:
        task = asyncio.create_task(
            _scenario_worker(service, record, normalized, timeout_s),
            name=f"hvdc-scenario-{scenario_id}",
        )
        service._scenario_tasks[scenario_id] = task
    except BaseException:
        service._scenarios.pop(scenario_id, None)
        await service._release_scenario(scenario_id)
        raise

    def _forget(completed: asyncio.Task[None]) -> None:
        if service._scenario_tasks.get(scenario_id) is completed:
            service._scenario_tasks.pop(scenario_id, None)
        if not completed.cancelled():
            completed.exception()

    task.add_done_callback(_forget)
    return dict(record)
