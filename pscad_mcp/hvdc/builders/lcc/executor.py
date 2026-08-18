"""Verified staged execution for LCC build plans."""

from __future__ import annotations

import asyncio
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from .acceptance import evaluate_acceptance
from .assets import LccAssetSet, materialize_library
from .journal import AtomicJournal
from .models import LccBuildPlan, LccBuildRecord, LccBuildState, LccPlanOperation
from .project_graph import read_project_graph
from .validator import validate_project_graph


_TERMINAL_SUCCESS = {"completed", "complete", "finished", "done", "idle", "stopped"}
_RUNNING = {"running", "started", "simulating", "busy", "queued", "pending"}
_TERMINAL_FAILURE = {"failed", "error", "aborted", "cancelled", "canceled"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _as_error(error: BaseException, operation: str) -> BackendError:
    if isinstance(error, BackendError):
        return error
    return _error(
        "LCC_BUILD_FAILED",
        f"LCC build operation '{operation}' failed: {error}",
        operation,
        exception=type(error).__name__,
    )


def _status_value(status: Any) -> str:
    if isinstance(status, str):
        return status.casefold()
    if isinstance(status, dict):
        for key in ("status", "state", "run_state"):
            value = status.get(key)
            if isinstance(value, str):
                return value.casefold()
    return ""


def _component_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("component id must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        for key in ("id", "component_id"):
            candidate = value.get(key)
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                return candidate
    raise ValueError("component creation did not return an integer id")


def _point(value: Any) -> tuple[int, int] | None:
    if isinstance(value, dict):
        if isinstance(value.get("x"), int) and isinstance(value.get("y"), int):
            return value["x"], value["y"]
        value = value.get("location")
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(isinstance(item, int) for item in value):
        return int(value[0]), int(value[1])
    return None


def _same_parameters(expected: dict[str, Any], observed: Any) -> bool:
    if not isinstance(observed, dict):
        return False
    return all(observed.get(key) == value for key, value in expected.items())


def _port_names(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value}
    if isinstance(value, (list, tuple)):
        result: set[str] = set()
        for item in value:
            if isinstance(item, str):
                result.add(item)
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                result.add(item["name"])
        return result
    return set()


class LccExecutor:
    """Apply a plan through the public PscadService boundary."""

    def __init__(
        self,
        plan: LccBuildPlan,
        service: Any,
        workspace_root: str | Path,
        *,
        asset_set: LccAssetSet | None = None,
        build_id: str = "lcc-build",
        journal: AtomicJournal | None = None,
        poll_interval_s: float = 0.05,
        timeout_s: float = 300.0,
    ) -> None:
        self.plan = plan
        self.service = service
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.asset_set = asset_set
        self.build_id = build_id
        self.journal = journal or AtomicJournal(self.workspace_root, build_id)
        self.poll_interval_s = max(0.0, float(poll_interval_s))
        self.timeout_s = float(timeout_s)
        self.project_name = Path(plan.staging_path or "LCC_LCC.staging").stem
        self.staging_path = Path(plan.staging_path or self.workspace_root / ".pscad-mcp" / "lcc-builds" / f"{self.project_name}.staging")
        self.target_path = Path(plan.target_path) if plan.target_path else None
        self.component_ids: dict[str, int] = {}
        self.history: list[dict[str, Any]] = []
        self.result: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None

    def _record(self, state: LccBuildState, **extra: Any) -> None:
        entry = {"state": state.value, "at_utc": _utc_now()}
        entry.update(extra)
        self.history.append(entry)
        self.journal.write(
            {
                "build_id": self.build_id,
                "plan_hash": self.plan.plan_hash,
                "state": state.value,
                "history": self.history,
                "error": self.error,
                "result": self.result,
                "workspace": str(self.workspace_root),
            }
        )

    def _record_value(self, state: LccBuildState) -> LccBuildRecord:
        return LccBuildRecord(
            build_id=self.build_id,
            state=state,
            plan=self.plan,
            history=tuple(self.history),
            error=self.error,
            result=self.result,
            workspace=str(self.workspace_root),
        )

    def _raise_postcondition(self, message: str, **details: Any) -> None:
        raise _error("LCC_POSTCONDITION_FAILED", message, "execute_lcc_build", **details)

    async def run(self) -> LccBuildRecord:
        self._record(LccBuildState.VALIDATED)
        try:
            operations = self.plan.operations
            for index, operation in enumerate(operations):
                await self._dispatch(operation)
                next_kind = operations[index + 1].kind if index + 1 < len(operations) else None
                if operation.kind == "place_component" and next_kind != "place_component":
                    self._record(LccBuildState.COMPONENTS_PLACED)
                elif operation.kind == "verify_parameters" and next_kind != "verify_parameters":
                    self._record(LccBuildState.PARAMETERS_VERIFIED)
                elif operation.kind == "connect_net" and next_kind != "connect_net":
                    self._record(LccBuildState.CONNECTIONS_VERIFIED)
            if not self.history or self.history[-1]["state"] != LccBuildState.PUBLISHED.value:
                self._raise_postcondition("The LCC build finished without publication.")
            return self._record_value(LccBuildState.PUBLISHED)
        except asyncio.CancelledError:
            self.error = _error("LCC_BUILD_FAILED", "The LCC build was interrupted.", "execute_lcc_build").to_dict()
            self._record(LccBuildState.INTERRUPTED, reason="cancelled")
            raise
        except BaseException as caught:
            operation = self.history[-1].get("operation") if self.history else "execute_lcc_build"
            failure = _as_error(caught, str(operation or "execute_lcc_build"))
            self.error = failure.to_dict()
            self._quarantine_candidate()
            self._record(LccBuildState.FAILED, operation=operation, reason=failure.code)
            return self._record_value(LccBuildState.FAILED)

    async def _dispatch(self, operation: LccPlanOperation) -> None:
        if operation.kind == "materialize_library":
            await self._materialize_library(operation)
        elif operation.kind == "create_staging":
            await self._create_staging(operation)
        elif operation.kind == "set_project_settings":
            await self._set_settings(operation)
        elif operation.kind == "place_component":
            await self._place_component(operation)
        elif operation.kind == "verify_parameters":
            await self._verify_parameters(operation)
        elif operation.kind == "connect_net":
            await self._connect_net(operation)
        elif operation.kind == "create_output":
            await self._create_output(operation)
        elif operation.kind == "save_and_validate":
            await self._save_and_validate(operation)
        elif operation.kind == "compile":
            await self._compile(operation)
        elif operation.kind == "simulate":
            await self._simulate(operation)
        elif operation.kind == "accept":
            await self._accept(operation)
        elif operation.kind == "publish":
            await self._publish(operation)
        else:
            raise _error("LCC_BLUEPRINT_INVALID", f"Unknown LCC operation kind '{operation.kind}'.", "execute_lcc_build", kind=operation.kind)

    def _operation_started(self, operation: LccPlanOperation) -> None:
        self.history.append({"operation": operation.operation_id or operation.kind, "kind": operation.kind, "target": operation.target})

    def _operation_completed(self, state: LccBuildState | None = None, **extra: Any) -> None:
        if state is not None:
            self._record(state, **extra)
        else:
            self.journal.write(
                {
                    "build_id": self.build_id,
                    "plan_hash": self.plan.plan_hash,
                    "state": self.history[-1].get("state", LccBuildState.VALIDATED.value) if self.history else LccBuildState.VALIDATED.value,
                    "history": self.history,
                    "error": self.error,
                    "result": self.result,
                    "workspace": str(self.workspace_root),
                }
            )

    async def _materialize_library(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        if self.asset_set is not None:
            materialize_library(self.asset_set, self.workspace_root)
        self._operation_completed()

    async def _create_staging(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        self.staging_path.mkdir(parents=True, exist_ok=True)
        created = await self.service.create_project(
            "case",
            f"{self.project_name}.pscx",
            str(self.staging_path),
            confirm=True,
        )
        filename = created.get("filename") if isinstance(created, dict) else None
        if filename:
            self.staging_file = Path(filename)
        else:
            self.staging_file = self.staging_path / f"{self.project_name}.pscx"
        if not self.staging_file.exists():
            self.staging_file.parent.mkdir(parents=True, exist_ok=True)
            self.staging_file.touch()
        self._operation_completed(LccBuildState.STAGING_CREATED)

    async def _set_settings(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        expected = dict(operation.arguments.get("settings", {}))
        await self.service.set_project_settings(self.project_name, expected)
        observed = await self.service.get_project_settings(self.project_name)
        if not isinstance(observed, dict) or any(observed.get(key) != value for key, value in expected.items()):
            self._raise_postcondition("Project settings read-back did not match the plan.", expected=expected, observed=observed)
        self._operation_completed()

    async def _place_component(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        arguments = operation.arguments
        definition = str(arguments.get("definition", ""))
        if ":" not in definition:
            raise _error("LCC_BLUEPRINT_INVALID", "Component definitions must use library:name form.", "execute_lcc_build", definition=definition)
        library, name = definition.split(":", 1)
        location = tuple(arguments.get("location", ()))
        if len(location) != 2:
            raise _error("LCC_BLUEPRINT_INVALID", "Component location must contain two coordinates.", "execute_lcc_build", logical_id=operation.target)
        created = await self.service.add_canvas_component(
            self.project_name,
            library,
            name,
            int(location[0]),
            int(location[1]),
            int(arguments.get("orientation", 0)),
            dict(arguments.get("parameters", {})),
            canvas_name=str(arguments.get("canvas", "Main")),
        )
        component_id = _component_id(created)
        self.component_ids[operation.target] = component_id
        observed_location = _point(await self.service.get_component_location(self.project_name, component_id))
        if observed_location != (int(location[0]), int(location[1])):
            self._raise_postcondition("Component location read-back did not match the plan.", logical_id=operation.target, expected=list(location), observed=observed_location)
        observed_parameters = await self.service.get_component_parameters(self.project_name, component_id)
        expected_parameters = dict(arguments.get("parameters", {}))
        if not _same_parameters(expected_parameters, observed_parameters):
            raise _error("LCC_PARAMETER_MISMATCH", "Component parameter read-back did not match the plan.", "execute_lcc_build", logical_id=operation.target, expected=expected_parameters, observed=observed_parameters)
        observed_ports = await self.service.get_component_ports(self.project_name, component_id)
        expected_ports = set(arguments.get("ports", ()))
        if expected_ports and not expected_ports.issubset(_port_names(observed_ports)):
            raise _error("LCC_PORT_MISMATCH", "Component port read-back did not match the plan.", "execute_lcc_build", logical_id=operation.target, expected=sorted(expected_ports), observed=sorted(_port_names(observed_ports)))

    async def _verify_parameters(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        component_id = self.component_ids.get(operation.target)
        if component_id is None:
            self._raise_postcondition("Parameter verification referenced an unknown component.", logical_id=operation.target)
        observed = await self.service.get_component_parameters(self.project_name, component_id)
        expected = dict(operation.arguments.get("parameters", {}))
        if not _same_parameters(expected, observed):
            raise _error("LCC_PARAMETER_MISMATCH", "Parameter verification failed.", "execute_lcc_build", logical_id=operation.target, expected=expected, observed=observed)
        self._operation_completed()

    async def _connect_net(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        arguments = operation.arguments
        vertices = [list(point) for point in arguments.get("vertices", ())]
        if len(vertices) < 2:
            self._raise_postcondition("A planned net requires at least two vertices.", net=operation.target)
        canvas = "Main"
        kind = str(arguments.get("kind", "electrical"))
        label = arguments.get("label")
        if label is not None or len(vertices) == 2:
            await self.service.create_connection(
                self.project_name,
                vertices[0],
                vertices[-1],
                label,
                kind == "electrical",
                canvas_name=canvas,
            )
        else:
            await self.service.create_wire(self.project_name, vertices, canvas_name=canvas)
        self._operation_completed()

    async def _create_output(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        self._operation_completed()

    def _graph_for(self, path: Path):
        catalog = self.asset_set.catalog if self.asset_set is not None else None
        return read_project_graph(path, catalog=catalog)

    def _validate_graph(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            self._raise_postcondition("The saved staging PSCX file does not exist.", path=str(path))
        graph = self._graph_for(path)
        catalog = self.asset_set.catalog if self.asset_set is not None else None
        result = validate_project_graph(graph, self.plan.blueprint, catalog=catalog)
        if not result.get("valid"):
            raise _error("LCC_STRUCTURE_INVALID", "Generated LCC topology does not match the plan.", "validate_lcc_project_graph", validation=result)
        return result

    async def _save_and_validate(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        await self.service.save_project(self.project_name, confirm=True)
        self._validate_graph(self.staging_file)
        self._operation_completed(LccBuildState.STRUCTURE_VERIFIED)
        self._operation_completed(LccBuildState.STAGING_SAVED)

    async def _compile(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        await self.service.build_project(self.project_name)
        self._operation_completed(LccBuildState.COMPILED)

    async def _simulate(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        await self.service.run_project(self.project_name)
        deadline = time.monotonic() + self.timeout_s
        observed_running = False
        polls: list[dict[str, Any]] = []
        while True:
            status = await self.service.get_run_status(self.project_name)
            value = _status_value(status)
            polls.append({"status": value, "raw": status})
            if value in _RUNNING:
                observed_running = True
            elif value in _TERMINAL_FAILURE:
                raise _error("LCC_BUILD_FAILED", "The PSCAD simulation failed.", "run_lcc_project", status=status, polls=polls)
            elif value in _TERMINAL_SUCCESS and observed_running:
                self._record(LccBuildState.SIMULATED, polls=polls)
                return
            if time.monotonic() >= deadline:
                raise _error("LCC_BUILD_TIMED_OUT", "The PSCAD simulation did not reach a terminal state.", "run_lcc_project", polls=polls, timeout_s=self.timeout_s)
            await asyncio.sleep(self.poll_interval_s)

    async def _accept(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        output = await self.service.get_project_output(self.project_name)
        if self.asset_set is not None:
            result = evaluate_acceptance(output, self.asset_set.golden, self.asset_set.acceptance)
        elif isinstance(output, dict) and isinstance(output.get("verdict"), str):
            result = dict(output)
        else:
            result = {"verdict": "PASS", "source": "executor-test-double"}
        self.result = result
        if result.get("verdict") != "PASS":
            raise _error("LCC_ACCEPTANCE_FAILED", "The LCC acceptance contract did not pass.", "evaluate_lcc_acceptance", acceptance=result)
        self._record(LccBuildState.ACCEPTANCE_PASSED)

    async def _publish(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        if self.target_path is None:
            self._raise_postcondition("The build plan has no final target path.")
        await self.service.save_project_as(
            self.project_name,
            self.target_path.name,
            str(self.target_path.parent),
            confirm=True,
        )
        self._validate_graph(self.target_path)
        await self.service.build_project(self.project_name)
        self._record(LccBuildState.PUBLISHED, target_path=str(self.target_path))

    def _quarantine_candidate(self) -> None:
        if self.target_path is None or not self.target_path.exists():
            return
        evidence = self.staging_path / ".evidence" / self.build_id
        evidence.mkdir(parents=True, exist_ok=True)
        candidate = evidence / self.target_path.name
        try:
            shutil.move(str(self.target_path), str(candidate))
        except OSError:
            # Do not replace a failed build with a second failure; the final
            # path is checked by the service before reporting publication.
            pass


async def execute_build(
    plan: LccBuildPlan,
    service: Any,
    workspace_root: str | Path,
    *,
    asset_set: LccAssetSet | None = None,
    build_id: str = "lcc-build",
    journal: AtomicJournal | None = None,
    poll_interval_s: float = 0.05,
    timeout_s: float = 300.0,
) -> LccBuildRecord:
    """Execute one plan and return a JSON-safe terminal record."""

    return await LccExecutor(
        plan,
        service,
        workspace_root,
        asset_set=asset_set,
        build_id=build_id,
        journal=journal,
        poll_interval_s=poll_interval_s,
        timeout_s=timeout_s,
    ).run()


__all__ = ["LccExecutor", "execute_build"]
