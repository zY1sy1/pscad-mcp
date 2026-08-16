"""Declarative HVDC scenario validation and safe execution."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from ..core.backend.base import BackendError
from ..core.service import ConfirmationRequired
from .profiles import load_profile


_UNSUPPORTED_TARGETS = {"insert_fault", "add_component", "rewire", "insert_breaker"}


def _error(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def validate_scenario(scenario: Mapping[str, Any]) -> dict[str, Any]:
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
            load_profile(profile)
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


async def run_scenario(service: Any, project_name: str, scenario: Mapping[str, Any], *, confirm: bool = False) -> dict[str, Any]:
    validation = validate_scenario(scenario)
    if not validation["valid"]:
        return validation
    if not confirm:
        raise ConfirmationRequired("run_hvdc_scenario")
    scenario_id = f"hvdc-{uuid4().hex}"
    record: dict[str, Any] = {
        "scenario_id": scenario_id,
        "project_name": project_name,
        "name": scenario["name"],
        "profile": scenario["profile"],
        "status": "validated",
        "changed_parameters": list(scenario.get("parameter_changes", [])),
        "events": list(scenario.get("events", [])),
        "output_files": list(scenario.get("output_files", [])),
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
        for change in scenario.get("parameter_changes", []):
            component_id = change.get("component_id")
            parameter_name = change.get("parameter_name")
            if component_id is None or not parameter_name:
                record["warnings"].append(f"Parameter change '{change.get('target')}' has no component_id/parameter_name and was not applied.")
                continue
            await backend.set_component_parameters(project_name, int(component_id), {str(parameter_name): change.get("value")})
        run = scenario.get("run", {}) or {}
        if run.get("simulation_set"):
            await backend.run_simulation_set(project_name, str(run["simulation_set"]))
        else:
            await backend.run_project(project_name)
        record["status"] = "running"
    except Exception as error:
        record["status"] = "failed"
        record["warnings"].append(str(error))
    return {"scenario_id": scenario_id, **record}
