"""Isolated PSCAD mutation execution with immediate read-back."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import shutil
import time
from typing import Any, Mapping

from ...core.backend.base import BackendError
from .assets import hash_tree, manifest_hash
from .journal import BuildJournal, next_state, write_json_atomic
from .models import (
    BlueprintBuildRecord,
    BlueprintBuildState,
    BlueprintOperation,
    BlueprintPlan,
    freeze,
    json_safe,
)
from .output import discover_output_dataset
from .validator import validate_staging, write_validation_report


_RUNNING = {"running", "started", "active", "busy"}
_SUCCESS = {"completed", "complete", "finished", "idle", "stopped"}
_FAILURE = {"failed", "error", "aborted", "cancelled", "canceled"}


def _error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "blueprint", operation, details)


def _status_value(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("status") or value.get("state")
    return str(value or "unknown").strip().casefold()


def _record(
    build_id: str,
    state: BlueprintBuildState,
    plan: BlueprintPlan,
    history: list[dict[str, Any]],
    bindings: Mapping[str, int],
    staging: Path | None,
    *,
    error: Mapping[str, Any] | None = None,
    result: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> BlueprintBuildRecord:
    return BlueprintBuildRecord(
        build_id,
        state,
        plan,
        freeze(history),
        freeze(bindings),
        str(staging) if staging is not None else None,
        freeze(error) if error is not None else None,
        freeze(result) if result is not None else None,
        freeze(evidence) if evidence is not None else None,
    )


@dataclass
class _Context:
    build_id: str
    plan: BlueprintPlan
    service: Any
    staging: Path
    project_file: Path
    journal: BuildJournal
    history: list[dict[str, Any]]
    bindings: dict[str, int]
    state: BlueprintBuildState = BlueprintBuildState.PLANNED
    simulation_active: bool = False

    def transition(self, proposed: BlueprintBuildState, **details: Any) -> None:
        self.state = next_state(self.state, proposed)
        event = {"state": proposed.value, **details}
        self.history.append(event)
        self.journal.append("state", event)

    def verify_source(self, checkpoint: str) -> None:
        observed = hash_tree(self.plan.source_path)
        if observed != dict(self.plan.source_manifest) or manifest_hash(observed) != self.plan.source_package_hash:
            raise _error(
                "BLUEPRINT_SOURCE_HASH_MISMATCH",
                "The read-only source package changed during execution.",
                "build_pscad_project",
                checkpoint=checkpoint,
            )

    def component_id(self, logical_id: str) -> int:
        component_id = self.bindings.get(logical_id)
        if not isinstance(component_id, int):
            raise _error("BLUEPRINT_TARGET_UNRESOLVED", "A runtime logical component binding is missing.", "execute_blueprint_operation", logical_id=logical_id)
        return component_id

    def operation_event(self, operation: BlueprintOperation, observed: Mapping[str, Any]) -> None:
        event = {
            "operation_id": operation.operation_id,
            "sequence": operation.sequence,
            "kind": operation.kind,
            "requested": operation.to_dict(),
            "observed": json_safe(observed),
        }
        self.history.append({"operation": operation.operation_id, "kind": operation.kind})
        self.journal.append("operation", event)


def _location(value: Any) -> tuple[int, int]:
    if isinstance(value, Mapping):
        value = (value.get("x"), value.get("y"))
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise _error("BLUEPRINT_READBACK_MISMATCH", "Component location read-back is invalid.", "verify_blueprint_operation")
    return int(value[0]), int(value[1])


def _assert_equal(label: str, expected: Any, observed: Any, operation: BlueprintOperation) -> None:
    if expected != observed:
        raise _error(
            "BLUEPRINT_READBACK_MISMATCH",
            f"{label} read-back does not match the confirmed plan.",
            "verify_blueprint_operation",
            operation_id=operation.operation_id,
            expected=json_safe(expected),
            observed=json_safe(observed),
        )


async def _snapshot(context: _Context, component_id: int) -> Mapping[str, Any]:
    bridge = getattr(context.service, "get_component_snapshot", None)
    if callable(bridge):
        value = await bridge(context.plan.target_name, component_id)
        if isinstance(value, Mapping):
            return value
    values = await context.service.list_canvas_components(context.plan.target_name, canvas_name="Main")
    matches = [value for value in values if isinstance(value, Mapping) and value.get("id") == component_id]
    if len(matches) != 1:
        raise _error("BLUEPRINT_READBACK_MISMATCH", "Component snapshot is missing or ambiguous.", "verify_blueprint_operation", component_id=component_id)
    return matches[0]


async def _apply_operation(context: _Context, operation: BlueprintOperation) -> None:
    context.verify_source(f"before:{operation.operation_id}")
    arguments = operation.arguments
    project = context.plan.target_name
    observed: dict[str, Any]
    if operation.kind == "clone_component":
        source_id = arguments["source_component_id"]
        expected_location = _location(arguments["location"])
        response = await context.service.clone_component(project, source_id, *expected_location)
        if not isinstance(response, Mapping) or not isinstance(response.get("id"), int):
            raise _error("BLUEPRINT_READBACK_MISMATCH", "Clone did not return a component ID.", "verify_blueprint_operation", operation_id=operation.operation_id)
        logical_id = arguments["logical_id"]
        component_id = response["id"]
        context.bindings[logical_id] = component_id
        read_location = _location(await context.service.get_component_location(project, component_id))
        _assert_equal("clone location", expected_location, read_location, operation)
        expected_definition = arguments.get("expected_definition")
        if expected_definition is not None:
            _assert_equal("clone definition", expected_definition, response.get("definition"), operation)
        observed = {"component_id": component_id, "logical_id": logical_id, "definition": response.get("definition"), "location": list(read_location)}
    elif operation.kind == "create_component":
        expected_location = _location(arguments["location"])
        logical_id = arguments.get("logical_id") or operation.target
        parameters = dict(arguments.get("parameters", {}))
        response = await context.service.create_canvas_component(
            project,
            arguments["definition"],
            *expected_location,
            int(arguments.get("orientation", 0)),
            parameters,
            canvas_name=arguments.get("canvas", "Main"),
        )
        if not isinstance(response, Mapping) or not isinstance(response.get("id"), int):
            raise _error("BLUEPRINT_READBACK_MISMATCH", "Component creation did not return an ID.", "verify_blueprint_operation", operation_id=operation.operation_id)
        component_id = response["id"]
        context.bindings[logical_id] = component_id
        read_location = _location(await context.service.get_component_location(project, component_id))
        _assert_equal("created component location", expected_location, read_location, operation)
        _assert_equal("created component definition", arguments["definition"], response.get("definition"), operation)
        read_parameters = await context.service.get_component_parameters(project, component_id)
        for name, value in parameters.items():
            _assert_equal(f"created parameter {name}", value, read_parameters.get(name), operation)
        observed = {"component_id": component_id, "logical_id": logical_id, "definition": response.get("definition"), "location": list(read_location), "parameters": read_parameters}
    elif operation.kind == "set_component_location":
        component_id = context.component_id(operation.target)
        expected = _location(arguments["location"])
        await context.service.set_component_location(project, component_id, *expected)
        read_location = _location(await context.service.get_component_location(project, component_id))
        _assert_equal("component location", expected, read_location, operation)
        observed = {"component_id": component_id, "location": list(read_location)}
    elif operation.kind == "rotate_component":
        component_id = context.component_id(operation.target)
        await context.service.rotate_component(project, component_id, arguments["direction"])
        snapshot = await _snapshot(context, component_id)
        expected = int(arguments["expected_orientation"])
        _assert_equal("component orientation", expected, snapshot.get("orientation"), operation)
        observed = {"component_id": component_id, "orientation": snapshot.get("orientation")}
    elif operation.kind == "set_component_parameters":
        component_id = context.component_id(operation.target)
        parameters = dict(arguments["parameters"])
        await context.service.set_component_parameters(project, component_id, parameters, confirm=True)
        read_parameters = await context.service.get_component_parameters(project, component_id)
        for name, value in parameters.items():
            _assert_equal(f"component parameter {name}", value, read_parameters.get(name), operation)
        observed = {"component_id": component_id, "parameters": {name: read_parameters[name] for name in parameters}}
    elif operation.kind == "create_wire":
        vertices = [list(vertex) for vertex in arguments["vertices"]]
        response = await context.service.create_wire(project, vertices, canvas_name=arguments.get("canvas", "Main"))
        if not isinstance(response, Mapping):
            raise _error("BLUEPRINT_READBACK_MISMATCH", "Wire creation returned invalid evidence.", "verify_blueprint_operation")
        _assert_equal("wire vertices", vertices, response.get("vertices"), operation)
        observed = dict(response)
    elif operation.kind == "connect_ports":
        first = arguments["from"]
        second = arguments["to"]
        first_id = context.component_id(first["logical_id"])
        second_id = context.component_id(second["logical_id"])
        for component_id, endpoint in ((first_id, first), (second_id, second)):
            ports = await context.service.get_component_ports(project, component_id)
            if endpoint["port"] not in ports:
                raise _error("BLUEPRINT_READBACK_MISMATCH", "A connection port is absent at execution time.", "verify_blueprint_operation", component_id=component_id, port=endpoint["port"])
        response = await context.service.connect_ports(
            project,
            first_id,
            first["port"],
            second_id,
            second["port"],
            canvas_name=arguments.get("canvas", "Main"),
        )
        expected_from = {"component_id": first_id, "port": first["port"]}
        expected_to = {"component_id": second_id, "port": second["port"]}
        if not isinstance(response, Mapping):
            raise _error("BLUEPRINT_READBACK_MISMATCH", "Port connection returned invalid evidence.", "verify_blueprint_operation")
        _assert_equal("connection source", expected_from, response.get("from"), operation)
        _assert_equal("connection target", expected_to, response.get("to"), operation)
        observed = dict(response)
    elif operation.kind == "set_project_settings":
        settings = dict(arguments["settings"])
        await context.service.set_project_settings(project, settings, confirm=True)
        read_settings = await context.service.get_project_settings(project)
        for name, value in settings.items():
            _assert_equal(f"project setting {name}", value, read_settings.get(name), operation)
        observed = {"settings": {name: read_settings[name] for name in settings}}
    elif operation.kind == "declare_output_channel":
        await context.service.create_output_channel(
            project,
            arguments["path"],
            arguments["units"],
            call_id=arguments.get("call_id"),
        )
        channels = await context.service.get_output_channels(project)
        matches = [channel for channel in channels if channel.get("path") == arguments["path"]]
        if len(matches) != 1:
            raise _error("BLUEPRINT_READBACK_MISMATCH", "Output channel read-back is missing or ambiguous.", "verify_blueprint_operation", path=arguments["path"])
        _assert_equal("output units", arguments["units"], matches[0].get("units"), operation)
        if arguments.get("call_id") is not None:
            _assert_equal("output call ID", arguments["call_id"], matches[0].get("call_id"), operation)
        observed = dict(matches[0])
    else:
        raise _error("BLUEPRINT_OPERATION_INVALID", "Plan contains an unsupported operation.", "execute_blueprint_operation", kind=operation.kind)
    context.operation_event(operation, observed)
    context.verify_source(f"after:{operation.operation_id}")


async def _reload(context: _Context) -> None:
    bridge = getattr(context.service, "reload_project", None)
    if callable(bridge):
        await bridge(context.plan.target_name, str(context.project_file))
    else:
        await context.service.load_projects([str(context.project_file)])


async def _verify_parameters_after_reload(context: _Context) -> None:
    for operation in context.plan.operations:
        if operation.kind != "set_component_parameters":
            continue
        component_id = context.component_id(operation.target)
        observed = await context.service.get_component_parameters(context.plan.target_name, component_id)
        for name, value in operation.arguments["parameters"].items():
            _assert_equal(f"reloaded parameter {name}", value, observed.get(name), operation)


def _normalize_messages(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        messages = value.get("messages")
        if isinstance(messages, list):
            return [dict(item) for item in messages if isinstance(item, Mapping)]
    if isinstance(value, str) and value:
        return [{"severity": "info", "text": line} for line in value.splitlines() if line]
    return []


async def _simulate(context: _Context, timeout_s: float, poll_interval_s: float) -> None:
    stop = getattr(context.service, "stop_simulation", None)
    if not callable(stop):
        raise _error("BLUEPRINT_BUILD_FAILED", "Simulation stop control is required for safe cleanup.", "run_blueprint_project")
    context.simulation_active = True
    await context.service.run_project(context.plan.target_name)
    deadline = time.monotonic() + timeout_s
    observed_running = False
    statuses: list[str] = []
    while True:
        status = _status_value(await context.service.get_run_status(context.plan.target_name))
        statuses.append(status)
        if status in _RUNNING:
            observed_running = True
        elif status in _FAILURE:
            context.simulation_active = False
            raise _error("BLUEPRINT_BUILD_FAILED", "PSCAD simulation reached a failure state.", "run_blueprint_project", statuses=statuses)
        elif status in _SUCCESS and observed_running:
            context.simulation_active = False
            return
        if time.monotonic() >= deadline:
            await stop(context.plan.target_name)
            context.simulation_active = False
            raise _error("BLUEPRINT_BUILD_TIMED_OUT", "PSCAD simulation did not reach a terminal state.", "run_blueprint_project", statuses=statuses, timeout_s=timeout_s)
        await asyncio.sleep(poll_interval_s)


async def execute_build(
    plan: BlueprintPlan,
    service: Any,
    workspace_root: str | Path,
    *,
    build_id: str,
    journal: BuildJournal | None = None,
    poll_interval_s: float = 0.1,
    simulation_timeout_s: float = 300.0,
    trusted_source_classes: set[str] | frozenset[str] | None = None,
) -> BlueprintBuildRecord:
    workspace = Path(workspace_root).expanduser().resolve()
    build_root = workspace / ".pscad-mcp" / "blueprint-builds" / build_id
    history: list[dict[str, Any]] = [{"state": BlueprintBuildState.PLANNED.value}]
    bindings = {key: int(value) for key, value in plan.resolved_selectors.items()}
    try:
        build_root.parent.mkdir(parents=True, exist_ok=True)
        build_root.mkdir()
    except FileExistsError:
        conflict = _error("BLUEPRINT_BUILD_CONFLICT", "The requested blueprint build directory already exists.", "build_pscad_project", build_id=build_id)
        return _record(build_id, BlueprintBuildState.REJECTED, plan, history + [{"state": "rejected"}], bindings, None, error=conflict.to_dict())
    active_journal = journal or BuildJournal(workspace, build_id)
    active_journal.append("state", history[0])
    staging = build_root / "staging"
    context: _Context | None = None
    try:
        shutil.copytree(plan.source_path, staging, symlinks=False)
        source_relative = Path(plan.source_entry_point).resolve().relative_to(Path(plan.source_path).resolve())
        copied_entry = staging / source_relative
        project_file = copied_entry.with_name(f"{plan.target_name}.pscx")
        if project_file != copied_entry:
            if project_file.exists() or project_file.is_symlink():
                raise _error("BLUEPRINT_BUILD_CONFLICT", "The target project file already exists in staging.", "build_pscad_project")
            copied_entry.replace(project_file)
        context = _Context(build_id, plan, service, staging, project_file, active_journal, history, bindings)
        context.verify_source("staging_created")
        evidence_dir = staging / "evidence"
        write_json_atomic(evidence_dir / "plan.json", plan.to_dict())
        write_json_atomic(
            evidence_dir / "source-manifest.json",
            {"package_hash": plan.source_package_hash, "files": dict(plan.source_manifest)},
        )
        context.transition(BlueprintBuildState.STAGING_CREATED, staging="staging")
        await service.load_projects([str(project_file)])
        for operation in plan.operations:
            await _apply_operation(context, operation)
        context.transition(BlueprintBuildState.MUTATIONS_APPLIED)
        context.transition(BlueprintBuildState.STRUCTURE_VERIFIED, operation_readbacks=len(plan.operations))
        await service.save_project(plan.target_name, confirm=True)
        if not project_file.is_file():
            raise _error("BLUEPRINT_PROJECT_INVALID", "Saved staging PSCX is missing.", "save_blueprint_project")
        context.transition(BlueprintBuildState.SAVED)
        await _reload(context)
        context.transition(BlueprintBuildState.RELOADED)
        await _verify_parameters_after_reload(context)
        context.transition(BlueprintBuildState.PARAMETERS_VERIFIED)
        await service.build_project(plan.target_name)
        context.transition(BlueprintBuildState.COMPILED)
        messages = _normalize_messages(await service.get_project_output(plan.target_name, structured=True))
        await _simulate(context, simulation_timeout_s, poll_interval_s)
        context.transition(BlueprintBuildState.SIMULATED)
        dataset = discover_output_dataset(staging)
        validation = validate_staging(
            plan,
            staging,
            dataset=dataset,
            messages=messages,
            trusted_source_classes=trusted_source_classes,
        )
        report_path = write_validation_report(staging, validation)
        if not validation["run_through_acceptance"]:
            raise _error("BLUEPRINT_ACCEPTANCE_FAILED", "Independent blueprint acceptance did not pass.", "evaluate_blueprint_acceptance", validation=validation)
        context.transition(BlueprintBuildState.ACCEPTANCE_PASSED)
        evidence = {
            "plan": "evidence/plan.json",
            "source_manifest": "evidence/source-manifest.json",
            "validation_report": report_path.relative_to(staging).as_posix(),
            "journal": "../journal.jsonl",
        }
        manifest = {
            "build_id": build_id,
            "plan_hash": plan.plan_hash,
            "state": context.state.value,
            "source_integrity": validation["source_integrity"],
            "structure_acceptance": validation["structure_acceptance"],
            "run_through_acceptance": validation["run_through_acceptance"],
            "physical_acceptance": validation["physical_acceptance"],
            "published": False,
            "publication_scope": None,
            "component_bindings": bindings,
            "evidence": evidence,
        }
        write_json_atomic(evidence_dir / "manifest.json", manifest)
        evidence["manifest"] = "evidence/manifest.json"
        context.verify_source("completed")
        return _record(build_id, context.state, plan, history, bindings, staging, result=validation, evidence=evidence)
    except asyncio.CancelledError:
        error = _error("BLUEPRINT_BUILD_INTERRUPTED", "Blueprint build was interrupted.", "build_pscad_project")
    except BackendError as caught:
        error = caught
    except BaseException as caught:
        error = _error("BLUEPRINT_BUILD_FAILED", "Blueprint build failed.", "build_pscad_project", exception=type(caught).__name__, message=str(caught))
    if context is not None and context.simulation_active:
        stop = getattr(service, "stop_simulation", None)
        if callable(stop):
            try:
                await stop(plan.target_name)
            except BaseException:
                pass
    failure_event = {"state": BlueprintBuildState.FAILED.value, "error": error.to_dict()}
    history.append(failure_event)
    active_journal.append("error", failure_event)
    quarantine = build_root / "quarantine"
    if staging.exists() and not quarantine.exists():
        staging.replace(quarantine)
    elif not quarantine.exists():
        quarantine.mkdir(parents=True, exist_ok=True)
    history.append({"state": BlueprintBuildState.QUARANTINED.value})
    active_journal.append("state", {"state": BlueprintBuildState.QUARANTINED.value})
    write_json_atomic(
        quarantine / "evidence" / "failure-report.json",
        {"build_id": build_id, "plan_hash": plan.plan_hash, "state": "quarantined", "error": error.to_dict()},
    )
    return _record(
        build_id,
        BlueprintBuildState.QUARANTINED,
        plan,
        history,
        bindings,
        quarantine,
        error=error.to_dict(),
        evidence={"failure_report": "evidence/failure-report.json", "journal": "../journal.jsonl"},
    )
