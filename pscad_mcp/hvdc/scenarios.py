"""Declarative HVDC scenario validation and safe execution."""

from __future__ import annotations

import math
import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any

from ..core.backend.base import BackendError
from ..core.service import ConfirmationRequired
from .profiles import load_profile


_UNSUPPORTED_TARGETS = {"insert_fault", "add_component", "rewire", "insert_breaker"}


def _error(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


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
    return {"valid": not errors, "errors": errors, "warnings": []}


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
    try:
        inspection = service.inspect_project(project_name)
        observed = {
            mapping["canonical"]: mapping["source"]
            for mapping in inspection.get("mappings", [])
            if mapping.get("status") == "observed" and mapping.get("source", {}).get("component_id") and mapping.get("source", {}).get("parameter_name")
        }
        for field in ("parameter_changes", "events"):
            for item in normalized[field]:
                source = observed.get(item.get("target"))
                if source:
                    item.setdefault("component_id", source["component_id"])
                    item.setdefault("parameter_name", source["parameter_name"])
    except Exception:
        # A loaded PSCAD project may not have a source file available for
        # inspection; explicit component bindings remain mandatory then.
        pass
    validation = validate_scenario(normalized, workspace_root=workspace_root)
    if not validation["valid"]:
        first = validation["errors"][0]
        raise BackendError(first["code"], first["message"], "hvdc", "run_hvdc_scenario", {key: value for key, value in first.items() if key not in {"code", "message"}})
    if not confirm:
        raise ConfirmationRequired("run_hvdc_scenario")
    for field in ("parameter_changes", "events"):
        for index, event in enumerate(scenario.get(field, [])):
            if not event.get("component_id") or not event.get("parameter_name"):
                raise BackendError("HVDC_CAPABILITY_UNAVAILABLE", f"Scenario target '{event.get('target')}' is not bound to an existing component parameter.", "hvdc", "run_hvdc_scenario", {"target": event.get("target"), "field": field, "index": index, "suggested_action": "Provide component_id and parameter_name for an existing mapped control."})
    mutating = bool(normalized.get("parameter_changes") or normalized.get("events"))
    target_project = str(normalized.get("derived_project") or project_name)
    if mutating and not normalized.get("derived_project"):
        raise BackendError("HVDC_CAPABILITY_UNAVAILABLE", "Mutating scenarios require a pre-existing derived_project; source projects are read-only inputs.", "hvdc", "run_hvdc_scenario", {"project": project_name, "suggested_action": "Create a confirmed derived project with existing generic PSCAD tools, then pass derived_project."})
    if normalized.get("derived_project") and Path(target_project).suffix.lower() == ".pscx":
        try:
            service._resolve_mutation_project(target_project)
        except BackendError:
            raise
    scenario_id = f"hvdc-{uuid4().hex}"
    record: dict[str, Any] = {
        "scenario_id": scenario_id,
        "project_name": project_name,
        "target_project": target_project,
        "name": normalized["name"],
        "profile": normalized["profile"],
        "status": "validated",
        "changed_parameters": list(normalized.get("parameter_changes", [])),
        "events": list(normalized.get("events", [])),
        "output_files": list(normalized.get("output_files", [])),
        "resolved_channels": [],
        "metrics": [],
        "warnings": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    service._scenarios[scenario_id] = record
    backend = getattr(service, "backend_service", None)
    if backend is None:
        record["status"] = "planned"
        return {"scenario_id": scenario_id, **record}
    try:
        for change in normalized.get("parameter_changes", []):
            component_id = change.get("component_id")
            parameter_name = change.get("parameter_name")
            if component_id is None or not parameter_name:
                record["warnings"].append(f"Parameter change '{change.get('target')}' has no component_id/parameter_name and was not applied.")
                continue
            await backend.set_component_parameters(target_project, int(component_id), {str(parameter_name): change.get("value")})
        run = normalized.get("run", {}) or {}
        if run.get("simulation_set"):
            await backend.run_simulation_set(target_project, str(run["simulation_set"]))
        else:
            await backend.run_project(target_project)
        previous_time = 0.0
        for event in sorted(normalized.get("events", []), key=lambda item: float(item["time_s"])):
            event_time = float(event["time_s"])
            await asyncio.sleep(max(0.0, event_time - previous_time))
            await backend.set_component_parameters(target_project, int(event["component_id"]), {str(event["parameter_name"]): event.get("value")})
            previous_time = event_time
        record["status"] = "running"
    except Exception as error:
        record["status"] = "failed"
        record["warnings"].append(str(error))
    return {"scenario_id": scenario_id, **record}
