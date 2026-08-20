"""Staged MMC execution through the public PSCAD service boundary."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from .acceptance import evaluate_acceptance
from .journal import AtomicJournal
from .models import MmcBuildPlan, MmcBuildRecord, MmcBuildState, MmcPlanOperation
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
    return _error("MMC_BUILD_FAILED", f"MMC build operation '{operation}' failed: {error}", operation, exception=type(error).__name__)


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


def _port_names(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value}
    if isinstance(value, (list, tuple)):
        return {item if isinstance(item, str) else item["name"] for item in value if isinstance(item, str) or isinstance(item, dict) and isinstance(item.get("name"), str)}
    return set()


def _response_endpoints(value: Any) -> tuple[tuple[int, int], tuple[int, int]] | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("endpoints")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        first, second = _point(raw[0]), _point(raw[1])
        if first is not None and second is not None:
            return first, second
    first, second = _point(value.get("p1")), _point(value.get("p2"))
    if first is not None and second is not None:
        return first, second
    return None


def _same_parameters(expected: dict[str, Any], observed: Any) -> bool:
    return isinstance(observed, dict) and all(observed.get(key) == value for key, value in expected.items())


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise _error("MMC_OUTPUT_INCOMPLETE", "The expected project file is not a regular file.", "hash_mmc_project", path=str(path))
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class MmcExecutor:
    """Apply one deterministic plan and publish only after independent checks."""

    def __init__(
        self,
        plan: MmcBuildPlan,
        service: Any,
        workspace_root: str | Path,
        *,
        asset_set: Any = None,
        build_id: str = "mmc-build",
        journal: AtomicJournal | None = None,
        poll_interval_s: float = 0.05,
        timeout_s: float = 300.0,
        allow_test_double: bool = False,
    ) -> None:
        self.plan = plan
        self.service = service
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.asset_set = asset_set
        self.build_id = build_id
        self.journal = journal or AtomicJournal(self.workspace_root, build_id)
        self.poll_interval_s = max(0.0, float(poll_interval_s))
        self.timeout_s = float(timeout_s)
        self.allow_test_double = bool(allow_test_double)
        self.project_name = str(plan.metadata.get("project_name", Path(plan.staging_path or "MMC_TEST.staging").stem.replace(".staging", "")))
        self.staging_path = Path(plan.staging_path or self.workspace_root / ".pscad-mcp" / "mmc-builds" / f"{self.project_name}.staging")
        self.target_path = Path(plan.target_path) if plan.target_path else None
        self.staging_file: Path | None = None
        self.library_file: Path | None = None
        self.component_ids: dict[str, int] = {}
        self.history: list[dict[str, Any]] = []
        self.result: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None
        self._run_started_after: float | None = None
        self._simulation_active = False
        self._publication_created = False
        self._publication_hash: str | None = None
        self.output_file: str | None = None

    def _journal_payload(self, state: str | None = None) -> dict[str, Any]:
        return {
            "build_id": self.build_id,
            "plan_hash": self.plan.plan_hash,
            "plan": self.plan.to_dict(),
            "asset_hashes": dict(self.plan.asset_hashes),
            "target_path": self.plan.target_path,
            "staging_path": self.plan.staging_path,
            "pscad_version": self.plan.pscad_version,
            "catalog_identity": self.plan.catalog_identity,
            "state": state or (self.history[-1].get("state", MmcBuildState.VALIDATED.value) if self.history else MmcBuildState.VALIDATED.value),
            "history": self.history,
            "error": self.error,
            "result": self.result,
            "workspace": str(self.workspace_root),
        }

    def _record(self, state: MmcBuildState, **extra: Any) -> None:
        entry = {"state": state.value, "at_utc": _utc_now()}
        entry.update(extra)
        self.history.append(entry)
        self.journal.write(self._journal_payload(state.value))

    def _operation_started(self, operation: MmcPlanOperation) -> None:
        self.history.append({"operation": operation.operation_id or operation.kind, "kind": operation.kind, "target": operation.target, "started_at_utc": _utc_now()})
        self.journal.write(self._journal_payload())

    def _operation_completed(self, **extra: Any) -> None:
        if extra and self.history:
            self.history[-1].update(extra)
        self.journal.write(self._journal_payload())

    def _record_value(self, state: MmcBuildState) -> MmcBuildRecord:
        return MmcBuildRecord(build_id=self.build_id, state=state, plan=self.plan, history=tuple(self.history), error=self.error, result=self.result, workspace=str(self.workspace_root))

    def _raise_postcondition(self, message: str, **details: Any) -> None:
        raise _error("MMC_POSTCONDITION_FAILED", message, "execute_mmc_build", **details)

    async def run(self) -> MmcBuildRecord:
        self._record(MmcBuildState.VALIDATED)
        try:
            operations = self.plan.operations
            for index, operation in enumerate(operations):
                await self._dispatch(operation)
                next_kind = operations[index + 1].kind if index + 1 < len(operations) else None
                if operation.kind == "place_component" and next_kind != "place_component":
                    self._record(MmcBuildState.COMPONENTS_PLACED)
                elif operation.kind == "verify_parameters" and next_kind != "verify_parameters":
                    self._record(MmcBuildState.PARAMETERS_VERIFIED)
                elif operation.kind == "connect_net" and next_kind != "connect_net":
                    self._record(MmcBuildState.CONNECTIONS_VERIFIED)
            if not self.history or self.history[-1].get("state") != MmcBuildState.PUBLISHED.value:
                self._raise_postcondition("The MMC build finished without publication.")
            return self._record_value(MmcBuildState.PUBLISHED)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(self._stop_simulation("cancelled"))
            except BaseException:
                pass
            self.error = _error("MMC_BUILD_FAILED", "The MMC build was interrupted.", "execute_mmc_build").to_dict()
            self._quarantine_candidate()
            self._record(MmcBuildState.INTERRUPTED, reason="cancelled")
            return self._record_value(MmcBuildState.INTERRUPTED)
        except BaseException as caught:
            await self._stop_simulation("failure")
            operation = self.history[-1].get("operation") if self.history else "execute_mmc_build"
            failure = _as_error(caught, str(operation or "execute_mmc_build"))
            self.error = failure.to_dict()
            self._quarantine_candidate()
            state = MmcBuildState.TIMED_OUT if failure.code == "MMC_BUILD_TIMED_OUT" else MmcBuildState.FAILED
            self._record(state, operation=operation, reason=failure.code)
            return self._record_value(state)

    async def _dispatch(self, operation: MmcPlanOperation) -> None:
        if operation.kind == "materialize_library":
            await self._materialize_library(operation)
        elif operation.kind == "create_staging":
            await self._create_staging(operation)
        elif operation.kind == "set_project_settings":
            await self._set_settings(operation)
        elif operation.kind == "place_component":
            await self._place_component(operation)
        elif operation.kind in {"create_phase_midpoint", "create_dc_terminal"}:
            await self._create_logical_terminal(operation)
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
        elif operation.kind == "simulate_phase":
            await self._simulate_phase(operation)
        elif operation.kind == "accept":
            await self._accept(operation)
        elif operation.kind == "publish":
            await self._publish(operation)
        else:
            raise _error("MMC_BLUEPRINT_INVALID", f"Unknown MMC operation kind '{operation.kind}'.", "execute_mmc_build", kind=operation.kind)

    async def _materialize_library(self, operation: MmcPlanOperation) -> None:
        self._operation_started(operation)
        if self.asset_set is None:
            if not self.allow_test_double:
                raise _error("MMC_ASSET_MISMATCH", "A verified MMC asset set is required before construction.", "materialize_mmc_library")
            self._operation_completed(skipped=True, reason="test_double")
            return
        expected = self.plan.asset_hashes.get(operation.target)
        payload = getattr(self.asset_set, "files", {}).get(operation.target)
        if payload is None and operation.target == getattr(self.asset_set, "companion_library", None):
            payload = getattr(self.asset_set, "library_bytes", None)
        if not isinstance(expected, str) or not isinstance(payload, (bytes, bytearray)) or hashlib.sha256(bytes(payload)).hexdigest() != expected:
            raise _error("MMC_ASSET_MISMATCH", "The companion library does not match the planned asset hash.", "materialize_mmc_library", path=operation.target)
        target = self.workspace_root / ".pscad-mcp" / "mmc-libraries" / Path(operation.target).name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise _error("MMC_ASSET_MISMATCH", "The workspace MMC library target is not a regular file.", "materialize_mmc_library", path=str(target))

        def verify_target() -> None:
            try:
                observed_hash = _sha256_file(target)
            except (BackendError, OSError) as error:
                raise _error(
                    "MMC_ASSET_MISMATCH",
                    "The workspace MMC library could not be verified against the planned asset.",
                    "materialize_mmc_library",
                    path=str(target),
                    expected=expected,
                    upstream_code=error.code if isinstance(error, BackendError) else type(error).__name__,
                ) from error
            if observed_hash != expected:
                raise _error(
                    "MMC_ASSET_MISMATCH",
                    "The workspace MMC library differs from the planned asset.",
                    "materialize_mmc_library",
                    path=str(target),
                    expected=expected,
                    observed=observed_hash,
                )

        if target.is_file():
            verify_target()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(bytes(payload))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
                temporary = None
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
            verify_target()
        self.library_file = target
        loader = getattr(self.service, "load_projects", None)
        if not callable(loader):
            raise _error("MMC_BUILD_FAILED", "The PSCAD service does not expose companion-library loading.", "load_mmc_companion_library")
        await loader([str(target.resolve())])
        self._operation_completed(path=str(target), sha256=expected)

    async def _create_staging(self, operation: MmcPlanOperation) -> None:
        self._operation_started(operation)
        if self.staging_path.exists():
            raise _error("MMC_BUILD_CONFLICT", "The planned MMC staging path already exists and will not be reused.", "create_mmc_staging", staging_path=str(self.staging_path))
        self.staging_path.mkdir(parents=True, exist_ok=True)
        created = await self.service.create_project("case", f"{self.project_name}.pscx", str(self.staging_path), confirm=True)
        filename = created.get("filename") if isinstance(created, dict) else None
        expected_file = (self.staging_path / f"{self.project_name}.pscx").resolve()
        candidate = expected_file if not filename else Path(str(filename)).expanduser().resolve()
        try:
            candidate.relative_to(self.staging_path.resolve())
        except ValueError as error:
            self._raise_postcondition("The PSCAD backend returned a staging file outside the builder-owned directory.", expected=str(expected_file), observed=str(candidate))
            raise error
        if candidate != expected_file or not candidate.is_file():
            self._raise_postcondition("The PSCAD backend did not create the expected MMC staging project file.", expected=str(expected_file), observed=str(candidate))
        self.staging_file = candidate
        self._record(MmcBuildState.STAGING_CREATED)

    async def _set_settings(self, operation: MmcPlanOperation) -> None:
        self._operation_started(operation)
        expected = dict(operation.arguments.get("settings", {}))
        await self.service.set_project_settings(self.project_name, expected)
        observed = await self.service.get_project_settings(self.project_name)
        if not _same_parameters(expected, observed):
            self._raise_postcondition("Project settings read-back did not match the MMC plan.", expected=expected, observed=observed)
        self._operation_completed()

    async def _place_component(self, operation: MmcPlanOperation) -> None:
        self._operation_started(operation)
        arguments = operation.arguments
        definition = str(arguments.get("definition", ""))
        if ":" not in definition:
            raise _error("MMC_BLUEPRINT_INVALID", "Component definitions must use library:name form.", "execute_mmc_build", definition=definition)
        library, name = definition.split(":", 1)
        location = tuple(arguments.get("location", ()))
        if len(location) != 2:
            raise _error("MMC_BLUEPRINT_INVALID", "Component location must contain two coordinates.", "execute_mmc_build", logical_id=operation.target)
        created = await self.service.add_canvas_component(self.project_name, library, name, int(location[0]), int(location[1]), int(arguments.get("orientation", 0)), dict(arguments.get("parameters", {})), canvas_name=str(arguments.get("canvas", "Main")))
        component_id = _component_id(created)
        self.component_ids[operation.target] = component_id
        observed_location = _point(await self.service.get_component_location(self.project_name, component_id))
        expected_location = (int(location[0]), int(location[1]))
        if observed_location != expected_location:
            self._raise_postcondition("Component location read-back did not match the MMC plan.", logical_id=operation.target, expected=list(expected_location), observed=observed_location)
        expected_parameters = dict(arguments.get("parameters", {}))
        observed_parameters = await self.service.get_component_parameters(self.project_name, component_id)
        if not _same_parameters(expected_parameters, observed_parameters):
            raise _error("MMC_PARAMETER_MISMATCH", "Component parameter read-back did not match the MMC plan.", "execute_mmc_build", logical_id=operation.target, expected=expected_parameters, observed=observed_parameters)
        expected_ports = set(arguments.get("ports", ()))
        if expected_ports:
            observed_ports = await self.service.get_component_ports(self.project_name, component_id)
            if not expected_ports.issubset(_port_names(observed_ports)):
                raise _error("MMC_PORT_MISMATCH", "Component port read-back did not match the MMC plan.", "execute_mmc_build", logical_id=operation.target, expected=sorted(expected_ports), observed=sorted(_port_names(observed_ports)))
        self._operation_completed(component_id=component_id)

    async def _create_logical_terminal(self, operation: MmcPlanOperation) -> None:
        self._operation_started(operation)
        method_name = "create_phase_midpoint" if operation.kind == "create_phase_midpoint" else "create_dc_terminal"
        creator = getattr(self.service, method_name, None)
        if callable(creator):
            await creator(self.project_name, dict(operation.arguments))
            self._operation_completed(observed="backend")
        else:
            self._operation_completed(observed="declarative_plan_marker", reason="public PSCAD service has no named-terminal primitive")

    async def _verify_parameters(self, operation: MmcPlanOperation) -> None:
        self._operation_started(operation)
        component_id = self.component_ids.get(operation.target)
        if component_id is None:
            self._raise_postcondition("MMC parameter verification referenced an unknown component.", logical_id=operation.target)
        observed = await self.service.get_component_parameters(self.project_name, component_id)
        expected = dict(operation.arguments.get("parameters", {}))
        if not _same_parameters(expected, observed):
            raise _error("MMC_PARAMETER_MISMATCH", "MMC parameter verification failed.", "execute_mmc_build", logical_id=operation.target, expected=expected, observed=observed)
        self._operation_completed()

    async def _connect_net(self, operation: MmcPlanOperation) -> None:
        self._operation_started(operation)
        arguments = operation.arguments
        vertices = [list(point) for point in arguments.get("vertices", ())]
        if len(vertices) < 2:
            self._raise_postcondition("A planned MMC net requires at least two vertices.", net=operation.target)
        kind = str(arguments.get("kind", "electrical"))
        label = arguments.get("label")
        if label is not None or len(vertices) == 2:
            created = await self.service.create_connection(self.project_name, vertices[0], vertices[-1], label, kind == "electrical", canvas_name="Main")
        else:
            created = await self.service.create_wire(self.project_name, vertices, canvas_name="Main")
        if not isinstance(created, dict):
            self._raise_postcondition("MMC connection creation returned invalid evidence.", net=operation.target)
        endpoints = _response_endpoints(created)
        if endpoints is not None and endpoints != (tuple(vertices[0]), tuple(vertices[-1])):
            self._raise_postcondition("MMC connection endpoint read-back did not match the plan.", net=operation.target, expected_endpoints=[vertices[0], vertices[-1]], observed_endpoints=[list(endpoints[0]), list(endpoints[1])])
        returned_vertices = created.get("vertices")
        if returned_vertices is not None and [list(point) for point in returned_vertices] != vertices:
            self._raise_postcondition("MMC wire vertex read-back did not match the plan.", net=operation.target, expected_vertices=vertices, observed_vertices=returned_vertices)
        self._operation_completed(kind=kind, vertices=vertices)

    async def _create_output(self, operation: MmcPlanOperation) -> None:
        self._operation_started(operation)
        arguments = operation.arguments
        creator = getattr(self.service, "create_output_channel", None)
        getter = getattr(self.service, "get_output_channels", None)
        if not callable(creator) or not callable(getter):
            if self.allow_test_double:
                self._operation_completed(skipped=True, reason="output_test_double")
                return
            raise _error("MMC_OUTPUT_INCOMPLETE", "The PSCAD service does not expose output-channel creation and read-back.", "create_mmc_output_channel", selector=arguments.get("path"))
        await creator(self.project_name, arguments.get("path"), arguments.get("units"), call_id=arguments.get("call_id"))
        channels = await getter(self.project_name)
        if not isinstance(channels, (list, tuple)):
            raise _error("MMC_OUTPUT_INCOMPLETE", "The PSCAD service returned invalid output-channel metadata.", "verify_mmc_output_channel")
        matches = [channel for channel in channels if isinstance(channel, dict) and channel.get("path") == arguments.get("path") and channel.get("units") == arguments.get("units")]
        if not matches:
            raise _error("MMC_OUTPUT_INCOMPLETE", "The saved output-channel metadata does not match the MMC plan.", "verify_mmc_output_channel", selector=arguments.get("path"), units=arguments.get("units"))
        self._operation_completed(selector=arguments.get("path"), units=arguments.get("units"))

    def _validate_graph(self, path: Path) -> dict[str, Any]:
        graph = read_project_graph(path)
        result = validate_project_graph(graph, self.plan.blueprint)
        if not result.get("valid"):
            raise _error("MMC_STRUCTURE_INVALID", "The saved MMC topology does not match the plan.", "validate_mmc_project_graph", validation=result)
        return result

    async def _save_and_validate(self, operation: MmcPlanOperation) -> None:
        self._operation_started(operation)
        if self.staging_file is None:
            self._raise_postcondition("The MMC staging project path is not available.")
        await self.service.save_project(self.project_name, confirm=True)
        validation = self._validate_graph(self.staging_file)
        self._record(MmcBuildState.STRUCTURE_VERIFIED, validation=validation)
        self._record(MmcBuildState.STAGING_SAVED)

    async def _compile(self, operation: MmcPlanOperation) -> None:
        self._operation_started(operation)
        await self.service.build_project(self.project_name)
        self._record(MmcBuildState.COMPILED)

    async def _simulate_phase(self, operation: MmcPlanOperation) -> None:
        self._operation_started(operation)
        stop_simulation = getattr(self.service, "stop_simulation", None)
        if not callable(stop_simulation):
            raise _error("MMC_BUILD_FAILED", "The PSCAD service does not expose simulation stop control required for safe cleanup.", "run_mmc_project")
        self._run_started_after = time.time()
        self._simulation_active = True
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
                self._simulation_active = False
                raise _error("MMC_BUILD_FAILED", "The PSCAD MMC simulation phase failed.", "run_mmc_project", phase=operation.target, status=status, polls=polls)
            elif value in _TERMINAL_SUCCESS and observed_running:
                self._simulation_active = False
                state_name = str(operation.arguments.get("state", "")).upper()
                state = getattr(MmcBuildState, state_name, None)
                if not isinstance(state, MmcBuildState):
                    state = {"startup": MmcBuildState.STARTUP_SIMULATED, "forward": MmcBuildState.FORWARD_SIMULATED, "reversal": MmcBuildState.REVERSAL_SIMULATED, "reverse": MmcBuildState.REVERSE_SIMULATED}.get(operation.target)
                if state is None:
                    raise _error("MMC_BLUEPRINT_INVALID", "MMC simulation phase has no terminal state mapping.", "run_mmc_project", phase=operation.target)
                self._record(state, phase=operation.target, polls=polls)
                return
            if time.monotonic() >= deadline:
                await self._stop_simulation("timeout")
                raise _error("MMC_BUILD_TIMED_OUT", "The PSCAD MMC simulation phase did not reach a terminal state.", "run_mmc_project", phase=operation.target, polls=polls, timeout_s=self.timeout_s)
            await asyncio.sleep(self.poll_interval_s)

    async def _stop_simulation(self, reason: str) -> None:
        if not self._simulation_active:
            return
        self._simulation_active = False
        stop_simulation = getattr(self.service, "stop_simulation", None)
        evidence: dict[str, Any] = {"simulation_stop": {"reason": reason, "requested": callable(stop_simulation)}}
        if not callable(stop_simulation):
            evidence["simulation_stop"]["error"] = "stop_control_unavailable"
            self.history.append(evidence)
            self.journal.write(self._journal_payload())
            return
        try:
            response = await stop_simulation(self.project_name)
            evidence["simulation_stop"]["response_type"] = type(response).__name__
        except BaseException as error:
            evidence["simulation_stop"]["error"] = {"type": type(error).__name__, "message": str(error)}
        self.history.append(evidence)
        self.journal.write(self._journal_payload())

    async def _acceptance_output(self) -> Any:
        discover = getattr(self.service, "discover_output_files", None)
        read_output = getattr(self.service, "read_output_file", None)
        if callable(discover) or callable(read_output):
            if not callable(discover) or not callable(read_output):
                raise _error(
                    "MMC_OUTPUT_INCOMPLETE",
                    "The PSCAD service does not expose both output discovery and reading capabilities.",
                    "read_mmc_output",
                )
            if self.staging_file is None:
                raise _error(
                    "MMC_OUTPUT_INCOMPLETE",
                    "The staging PSCX path is not available for output discovery.",
                    "discover_mmc_output",
                )
            paths = await discover(
                str(self.staging_file.resolve()),
                started_after=self._run_started_after if self._run_started_after is not None else time.time(),
                max_files=32,
            )
            if not isinstance(paths, (list, tuple)):
                raise _error(
                    "MMC_OUTPUT_INCOMPLETE",
                    "The PSCAD service returned an invalid output-file list.",
                    "discover_mmc_output",
                )
            candidates: list[str] = []
            staging_root = self.staging_path.resolve()
            for path in paths:
                if not isinstance(path, str) or not path:
                    continue
                candidate = Path(path).expanduser()
                if not candidate.is_absolute():
                    candidate = self.staging_path / candidate
                if candidate.is_symlink():
                    raise _error(
                        "MMC_OUTPUT_INCOMPLETE",
                        "The PSCAD output file is not a regular file owned by the staging directory.",
                        "discover_mmc_output",
                        reason="output_not_regular",
                        path=str(candidate),
                    )
                resolved = candidate.resolve()
                try:
                    resolved.relative_to(staging_root)
                except ValueError as error:
                    raise _error(
                        "MMC_OUTPUT_INCOMPLETE",
                        "The PSCAD output file is outside the builder-owned staging directory.",
                        "discover_mmc_output",
                        reason="output_outside_staging",
                        path=str(resolved),
                    ) from error
                if resolved.suffix.casefold() not in {".out", ".psout"}:
                    raise _error(
                        "MMC_OUTPUT_INCOMPLETE",
                        "The PSCAD output file has an unsupported suffix.",
                        "discover_mmc_output",
                        reason="output_suffix_invalid",
                        path=str(resolved),
                    )
                if resolved.is_symlink() or not resolved.is_file():
                    raise _error(
                        "MMC_OUTPUT_INCOMPLETE",
                        "The PSCAD output file is not a regular file owned by the staging directory.",
                        "discover_mmc_output",
                        reason="output_not_regular",
                        path=str(resolved),
                    )
                candidates.append(str(resolved))
            if not candidates:
                raise _error(
                    "MMC_OUTPUT_INCOMPLETE",
                    "No PSCAD output file was created after the MMC simulation.",
                    "discover_mmc_output",
                    project_name=self.project_name,
                )
            candidates = sorted(set(candidates), key=str.casefold)
            if len(candidates) != 1:
                raise _error(
                    "MMC_OUTPUT_INCOMPLETE",
                    "Multiple PSCAD output files were created for the MMC simulation.",
                    "discover_mmc_output",
                    reason="output_ambiguous",
                    candidates=candidates,
                )
            self.output_file = candidates[0]
            return await read_output(self.output_file, max_samples=1_000_000, summary_only=False)

        getter = getattr(self.service, "get_project_output", None)
        if not callable(getter):
            raise _error("MMC_OUTPUT_INCOMPLETE", "The PSCAD service does not expose an output reader.", "read_mmc_output")
        return await getter(self.project_name)

    async def _accept(self, operation: MmcPlanOperation) -> None:
        self._operation_started(operation)
        output = await self._acceptance_output()
        if self.asset_set is not None and not (self.allow_test_double and isinstance(output, dict) and isinstance(output.get("verdict"), str)):
            result = evaluate_acceptance(output, self.plan.acceptance_checks, golden=getattr(self.asset_set, "golden", None))
            result = result.to_dict()
        elif self.allow_test_double and isinstance(output, dict) and isinstance(output.get("verdict"), str):
            result = dict(output)
        elif self.allow_test_double:
            result = {"verdict": "PASS", "source": "executor-test-double"}
        else:
            result = {"verdict": "INCOMPLETE_ANALYSIS", "source": "executor", "reason": "verified_asset_set_required"}
        if self.output_file is not None:
            result = dict(result)
            result["output_file"] = self.output_file
            try:
                result["output_sha256"] = _sha256_file(Path(self.output_file))
            except BackendError as error:
                raise _error(
                    "MMC_OUTPUT_INCOMPLETE",
                    "The selected PSCAD output file could not be hashed for acceptance evidence.",
                    "read_mmc_output",
                    output_file=self.output_file,
                    upstream_code=error.code,
                ) from error
        self.result = result
        if result.get("verdict") != "PASS":
            raise _error("MMC_ACCEPTANCE_FAILED", "The MMC acceptance contract did not pass.", "evaluate_mmc_acceptance", acceptance=result)
        self._record(MmcBuildState.ACCEPTANCE_PASSED, acceptance=result)

    async def _publish(self, operation: MmcPlanOperation) -> None:
        self._operation_started(operation)
        if self.target_path is None:
            self._raise_postcondition("The MMC build plan has no final target path.")
        if self.target_path.exists() or self.target_path.is_symlink():
            raise _error("MMC_BUILD_CONFLICT", "The final MMC publication target appeared after planning.", "publish_mmc_model", target_path=str(self.target_path))
        await self.service.save_project_as(self.project_name, self.target_path.name, str(self.target_path.parent), confirm=False)
        if not self.target_path.is_file():
            self._raise_postcondition("The final MMC project file was not created.", path=str(self.target_path))
        self._publication_created = True
        self._publication_hash = _sha256_file(self.target_path)
        loader = getattr(self.service, "load_projects", None)
        if not callable(loader):
            raise _error("MMC_OUTPUT_INCOMPLETE", "The PSCAD service does not expose final-project reload required for independent validation.", "validate_mmc_publication")
        await loader([str(self.target_path.resolve())])
        validation = self._validate_graph(self.target_path)
        await self.service.build_project(self.target_path.stem)
        self._record(
            MmcBuildState.PUBLISHED,
            target_path=str(self.target_path),
            final_project_name=self.target_path.stem,
            final_compile_smoke=True,
            final_project_sha256=self._publication_hash,
            validation=validation,
        )

    def _quarantine_candidate(self) -> None:
        if not self._publication_created or self.target_path is None or not self.target_path.exists():
            return
        evidence = self.staging_path / ".evidence" / self.build_id
        evidence.mkdir(parents=True, exist_ok=True)
        candidate = evidence / self.target_path.name
        cleanup: dict[str, Any] = {"path": str(self.target_path), "candidate": str(candidate)}
        if self._publication_hash is None or self.target_path.is_symlink() or not self.target_path.is_file():
            cleanup["action"] = "preserved_unverified_target"
        else:
            try:
                observed_hash = _sha256_file(self.target_path)
            except BackendError as error:
                cleanup["action"] = "preserved_unhashable_target"
                cleanup["error"] = error.to_dict()
            else:
                if observed_hash != self._publication_hash:
                    cleanup["action"] = "preserved_external_replacement"
                else:
                    try:
                        shutil.move(str(self.target_path), str(candidate))
                        cleanup["action"] = "quarantined_candidate"
                    except OSError as error:
                        cleanup["action"] = "preserved_move_failure"
                        cleanup["error"] = {"type": type(error).__name__, "message": str(error)}
        self.history.append({"publication_cleanup": cleanup})
        self.journal.write(self._journal_payload())


async def execute_build(
    plan: MmcBuildPlan,
    service: Any,
    workspace_root: str | Path,
    *,
    asset_set: Any = None,
    build_id: str = "mmc-build",
    journal: AtomicJournal | None = None,
    poll_interval_s: float = 0.05,
    timeout_s: float = 300.0,
    allow_test_double: bool = False,
) -> MmcBuildRecord:
    """Execute one plan and return a JSON-safe terminal record."""

    return await MmcExecutor(plan, service, workspace_root, asset_set=asset_set, build_id=build_id, journal=journal, poll_interval_s=poll_interval_s, timeout_s=timeout_s, allow_test_double=allow_test_double).run()


__all__ = ["MmcExecutor", "execute_build"]
