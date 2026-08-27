"""Independent persisted-graph, source, message, and output validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping
import xml.etree.ElementTree as ET

from ...core.backend.base import BackendError
from .acceptance import evaluate_acceptance
from .assets import hash_tree, manifest_hash
from .journal import write_json_atomic
from .models import BlueprintPlan
from .output import discover_output_dataset


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "blueprint", "validate_pscad_project_build", details)


def _integer(value: str | None, field: str) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise _error("BLUEPRINT_PROJECT_INVALID", f"Persisted component {field} is not an integer.") from error


def inspect_project_file(path: str | Path) -> dict[str, Any]:
    project_path = Path(path).expanduser().resolve()
    if not project_path.is_file() or project_path.is_symlink() or project_path.suffix.casefold() != ".pscx":
        raise _error("BLUEPRINT_PROJECT_INVALID", "Persisted project must be a regular PSCX file.", path=str(project_path))
    try:
        root = ET.parse(project_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise _error("BLUEPRINT_PROJECT_INVALID", "Persisted PSCX could not be parsed.", path=str(project_path)) from error
    components: list[dict[str, Any]] = []
    for definition in root.findall(".//definition"):
        canvas = definition.get("name") or "Main"
        for component in definition.findall("./component"):
            parameters = {
                str(parameter.get("name")): parameter.get("value")
                for parameter in component.findall("./parameters/param")
                if parameter.get("name") is not None
            }
            ports = []
            for port in component.findall("./port"):
                ports.append(
                    {
                        "name": port.get("name"),
                        "x": _integer(port.get("x"), "port x"),
                        "y": _integer(port.get("y"), "port y"),
                        "kind": port.get("kind"),
                        "dimension": _integer(port.get("dimension"), "port dimension") if port.get("dimension") is not None else None,
                    }
                )
            components.append(
                {
                    "id": _integer(component.get("id"), "id"),
                    "logical_id": component.get("logical_id") or component.get("name") or component.get("id"),
                    "definition": component.get("definition"),
                    "canvas": canvas,
                    "location": [_integer(component.get("x"), "x"), _integer(component.get("y"), "y")],
                    "orientation": _integer(component.get("orientation") or "0", "orientation"),
                    "parameters": parameters,
                    "ports": ports,
                }
            )
    identifiers = [component["logical_id"] for component in components]
    if len(set(identifiers)) != len(identifiers):
        raise _error("BLUEPRINT_PROJECT_INVALID", "Persisted logical component IDs are not unique.")
    return {
        "project_name": root.get("name") or project_path.stem,
        "pscad_version": root.get("version"),
        "components": components,
    }


def _project_path(staging: Path) -> Path:
    candidates = sorted(staging.rglob("*.pscx"), key=lambda path: path.as_posix())
    safe = [path for path in candidates if not path.is_symlink() and (path.resolve() == staging or staging in path.resolve().parents)]
    if len(safe) != 1:
        raise _error(
            "BLUEPRINT_PROJECT_INVALID",
            "Staging must contain exactly one workspace-contained PSCX entry point.",
            observed=len(safe),
        )
    return safe[0]


def _component_index(graph: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    components = graph.get("components")
    if not isinstance(components, list):
        raise _error("BLUEPRINT_PROJECT_INVALID", "Project inspection did not return a component array.")
    result: dict[str, Mapping[str, Any]] = {}
    for component in components:
        if not isinstance(component, Mapping) or not isinstance(component.get("logical_id"), str):
            raise _error("BLUEPRINT_PROJECT_INVALID", "Project inspection returned an invalid component.")
        logical_id = component["logical_id"]
        if logical_id in result:
            raise _error("BLUEPRINT_PROJECT_INVALID", "Project inspection returned duplicate logical IDs.", logical_id=logical_id)
        result[logical_id] = component
    return result


def _structure_checks(plan: BlueprintPlan, components: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for requirement in plan.blueprint.acceptance["required_structure"]:
        logical_id = requirement.get("logical_id")
        observed = components.get(logical_id)
        expected_definition = requirement.get("definition")
        expected_canvas = requirement.get("canvas")
        passed = bool(
            observed is not None
            and (expected_definition is None or observed.get("definition") == expected_definition)
            and (expected_canvas is None or observed.get("canvas") == expected_canvas)
        )
        checks.append(
            {
                "logical_id": logical_id,
                "expected_definition": expected_definition,
                "observed_definition": observed.get("definition") if observed else None,
                "expected_canvas": expected_canvas,
                "observed_canvas": observed.get("canvas") if observed else None,
                "passed": passed,
            }
        )
    return checks


def _parameter_checks(plan: BlueprintPlan, components: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for requirement in plan.blueprint.acceptance["required_parameters"]:
        logical_id = requirement.get("logical_id")
        name = requirement.get("name")
        expected = requirement.get("value")
        component = components.get(logical_id)
        parameters = component.get("parameters") if component is not None else None
        observed = parameters.get(name) if isinstance(parameters, Mapping) else None
        passed = observed == expected or (observed is not None and str(observed) == str(expected))
        checks.append({"logical_id": logical_id, "name": name, "expected": expected, "observed": observed, "passed": passed})
    return checks


def _message_checks(plan: BlueprintPlan, messages: list[Mapping[str, Any]]) -> tuple[bool, list[dict[str, Any]]]:
    tokens = [str(item).casefold() for item in plan.blueprint.acceptance["blocking_messages"]]
    blocking = []
    for message in messages:
        severity = str(message.get("severity", "")).casefold()
        text = str(message.get("text", ""))
        if any(token == severity or token in text.casefold() for token in tokens):
            blocking.append({"severity": message.get("severity"), "text": text})
    return not blocking, blocking


def validate_staging(
    plan: BlueprintPlan,
    staging_path: str | Path,
    *,
    inspector: Callable[[Path], Mapping[str, Any]] = inspect_project_file,
    dataset: Mapping[str, Any] | None = None,
    messages: list[Mapping[str, Any]] | None = None,
    trusted_source_classes: set[str] | frozenset[str] | None = None,
    executor_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    del executor_result
    staging = Path(staging_path).expanduser().resolve()
    if not staging.is_dir() or staging.is_symlink():
        raise _error("BLUEPRINT_STAGING_INVALID", "Validation target must be a regular staging directory.", path=str(staging))
    project = _project_path(staging)
    graph = inspector(project)
    components = _component_index(graph)
    structure_checks = _structure_checks(plan, components)
    parameter_checks = _parameter_checks(plan, components)
    structure_acceptance = all(check["passed"] for check in structure_checks)
    parameters_acceptance = all(check["passed"] for check in parameter_checks)
    observed_messages = list(messages or [])
    messages_acceptance, blocking_messages = _message_checks(plan, observed_messages)
    try:
        current_source = hash_tree(plan.source_path)
        source_integrity = current_source == dict(plan.source_manifest) and manifest_hash(current_source) == plan.source_package_hash
    except BackendError:
        source_integrity = False
    output_error: dict[str, Any] | None = None
    if dataset is None:
        try:
            dataset = discover_output_dataset(staging)
        except BackendError as error:
            output_error = error.to_dict()
            dataset = {"channels": {}}
    acceptance = evaluate_acceptance(
        plan.blueprint.acceptance,
        dataset,
        structure_acceptance=structure_acceptance,
        parameters_acceptance=parameters_acceptance,
        messages_acceptance=messages_acceptance,
        trusted_source_classes=trusted_source_classes,
    )
    report = {
        "plan_hash": plan.plan_hash,
        "source_integrity": source_integrity,
        "structure_acceptance": acceptance["structure_acceptance"],
        "parameters_acceptance": acceptance["parameters_acceptance"],
        "messages_acceptance": acceptance["messages_acceptance"],
        "output_acceptance": acceptance["output_acceptance"],
        "run_through_acceptance": bool(source_integrity and acceptance["run_through_acceptance"]),
        "physical_acceptance": bool(source_integrity and acceptance["physical_acceptance"]),
        "valid": bool(source_integrity and acceptance["run_through_acceptance"]),
        "structure_checks": structure_checks,
        "parameter_checks": parameter_checks,
        "blocking_messages": blocking_messages,
        "output_checks": acceptance["outputs"],
        "rules": acceptance["rules"],
        "output_error": output_error,
        "evidence": {"project": project.relative_to(staging).as_posix()},
    }
    return report


def write_validation_report(staging_path: str | Path, report: Mapping[str, Any]) -> Path:
    staging = Path(staging_path).expanduser().resolve()
    if not staging.is_dir() or staging.is_symlink():
        raise _error("BLUEPRINT_STAGING_INVALID", "Validation report target must be a staging directory.")
    destination = staging / "evidence" / "validation-report.json"
    return write_json_atomic(destination, report)
