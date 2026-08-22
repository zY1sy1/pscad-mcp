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
from .assets import LccAssetSet, materialize_library, sha256_file
from .catalog import parse_catalog, require_definition, require_port
from .journal import AtomicJournal
from .models import LccBuildPlan, LccBuildRecord, LccBuildState, LccPlanOperation
from .project_graph import read_project_graph
from .routing import absolute_port
from .validator import validate_companion_library, validate_project_graph


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


def _port_records(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("name"), str):
            return {value["name"]: value}
        return {
            str(name): item
            for name, item in value.items()
            if isinstance(item, dict)
        }
    if isinstance(value, (list, tuple)):
        return {
            item["name"]: item
            for item in value
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
    return {}


def _port_point(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, dict):
        return None
    point = _point(value)
    if point is not None:
        return point
    location = value.get("location")
    return _point(location)


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
        allow_test_double: bool = False,
        trusted_threshold_sources: Any = None,
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
        self.trusted_threshold_sources = trusted_threshold_sources
        self.project_name = Path(plan.staging_path or "LCC_LCC.staging").stem
        self.staging_path = Path(plan.staging_path or self.workspace_root / ".pscad-mcp" / "lcc-builds" / f"{self.project_name}.staging")
        self.target_path = Path(plan.target_path) if plan.target_path else None
        self.staging_file: Path | None = None
        self.library_file: Path | None = None
        self.component_ids: dict[str, int] = {}
        self.history: list[dict[str, Any]] = []
        self.result: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None
        self._run_started_after: float | None = None
        self.output_file: str | None = None
        self._publication_created = False
        self._publication_hash: str | None = None
        self._simulation_active = False

    def _record(self, state: LccBuildState, **extra: Any) -> None:
        entry = {"state": state.value, "at_utc": _utc_now()}
        entry.update(extra)
        self.history.append(entry)
        self.journal.write(self._journal_payload(state.value))

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
            "state": state or (self.history[-1].get("state", LccBuildState.VALIDATED.value) if self.history else LccBuildState.VALIDATED.value),
            "history": self.history,
            "error": self.error,
            "result": self.result,
            "workspace": str(self.workspace_root),
        }

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
            try:
                await asyncio.shield(self._stop_simulation("cancelled"))
            except BaseException:
                # Preserve cancellation as the terminal outcome; stop evidence
                # is retained in the journal when the backend accepts it.
                pass
            self.error = _error("LCC_BUILD_FAILED", "The LCC build was interrupted.", "execute_lcc_build").to_dict()
            self._record(LccBuildState.INTERRUPTED, reason="cancelled")
            raise
        except BaseException as caught:
            await self._stop_simulation("failure")
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
            if extra and self.history:
                self.history[-1].update(extra)
            self.journal.write(self._journal_payload())

    async def _materialize_library(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        if self.asset_set is not None:
            self.library_file = materialize_library(self.asset_set, self.workspace_root)
            validate_companion_library(self.library_file, raise_on_error=True)
            loader = getattr(self.service, "load_projects", None)
            if not callable(loader):
                raise _error(
                    "LCC_BUILD_FAILED",
                    "The PSCAD service does not expose companion-library loading.",
                    "load_lcc_companion_library",
                )
            await loader([str(self.library_file.resolve())])
        self._operation_completed()

    async def _create_staging(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        if self.staging_path.exists():
            raise _error(
                "LCC_BUILD_CONFLICT",
                "The planned staging path already exists and will not be reused.",
                "create_lcc_staging",
                staging_path=str(self.staging_path),
            )
        self.staging_path.mkdir(parents=True, exist_ok=True)
        created = await self.service.create_project(
            "case",
            f"{self.project_name}.pscx",
            str(self.staging_path),
            confirm=True,
        )
        filename = created.get("filename") if isinstance(created, dict) else None
        expected_file = (self.staging_path / f"{self.project_name}.pscx").resolve()
        candidate = expected_file if not filename else Path(str(filename)).expanduser().resolve()
        try:
            candidate.relative_to(self.staging_path.resolve())
        except ValueError as error:
            self._raise_postcondition(
                "The PSCAD backend returned a staging file outside the builder-owned staging directory.",
                expected=str(expected_file),
                observed=str(candidate),
            )
            raise error
        if candidate != expected_file:
            self._raise_postcondition(
                "The PSCAD backend returned an unexpected staging project path.",
                expected=str(expected_file),
                observed=str(candidate),
            )
        self.staging_file = candidate
        if not self.staging_file.is_file():
            self._raise_postcondition(
                "The PSCAD backend did not create the expected staging project file.",
                path=str(self.staging_file),
            )
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
        expected_definition = f"{library}:{name}"
        if isinstance(created, dict) and created.get("definition") is not None:
            if created.get("definition") != expected_definition:
                self._raise_postcondition(
                    "Component definition read-back did not match the plan.",
                    logical_id=operation.target,
                    definition=expected_definition,
                    observed_definition=created.get("definition"),
                )
        expected_orientation = int(arguments.get("orientation", 0))
        if isinstance(created, dict) and created.get("orientation") is not None:
            if created.get("orientation") != expected_orientation:
                self._raise_postcondition(
                    "Component orientation read-back did not match the plan.",
                    logical_id=operation.target,
                    orientation=expected_orientation,
                    observed_orientation=created.get("orientation"),
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
        if self.asset_set is not None and expected_ports:
            catalog = parse_catalog(self.asset_set.catalog)
            definition_spec = require_definition(catalog, expected_definition)
            observed_records = _port_records(observed_ports)
            for port_name in sorted(expected_ports):
                contract = require_port(definition_spec, port_name)
                observed = observed_records.get(port_name)
                if observed is None:
                    continue
                observed_dimension = observed.get("dimension", observed.get("dim"))
                if observed_dimension is not None and observed_dimension != contract.dimension:
                    raise _error(
                        "LCC_PORT_MISMATCH",
                        "Component port dimension read-back did not match the catalog.",
                        "execute_lcc_build",
                        logical_id=operation.target,
                        port=port_name,
                        expected_dimension=contract.dimension,
                        observed_dimension=observed_dimension,
                    )
                observed_kind = observed.get("kind", observed.get("type"))
                if observed_kind is not None:
                    normalized_kind = str(observed_kind).casefold()
                    if normalized_kind in {"power", "analog", "node"}:
                        normalized_kind = "electrical"
                    if normalized_kind != contract.kind:
                        raise _error(
                            "LCC_PORT_MISMATCH",
                            "Component port kind read-back did not match the catalog.",
                            "execute_lcc_build",
                            logical_id=operation.target,
                            port=port_name,
                            expected_kind=contract.kind,
                            observed_kind=observed_kind,
                        )
                observed_point = _port_point(observed)
                if observed_point is not None:
                    expected_point = absolute_port(
                        (int(location[0]), int(location[1])),
                        contract.offset,
                        expected_orientation,
                    )
                    if observed_point != expected_point:
                        self._raise_postcondition(
                            "Component port endpoint read-back did not match the plan.",
                            logical_id=operation.target,
                            port=port_name,
                            expected_endpoint=list(expected_point),
                            observed_endpoint=list(observed_point),
                            orientation=expected_orientation,
                        )

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
            created = await self.service.create_connection(
                self.project_name,
                vertices[0],
                vertices[-1],
                label,
                kind == "electrical",
                canvas_name=canvas,
            )
        else:
            created = await self.service.create_wire(self.project_name, vertices, canvas_name=canvas)
        if not isinstance(created, dict):
            self._raise_postcondition("Connection creation returned invalid evidence.", net=operation.target)
        endpoints = _response_endpoints(created)
        if endpoints is not None and endpoints != (tuple(vertices[0]), tuple(vertices[-1])):
            self._raise_postcondition(
                "Connection endpoint read-back did not match the plan.",
                net=operation.target,
                expected_endpoints=[vertices[0], vertices[-1]],
                observed_endpoints=[list(endpoints[0]), list(endpoints[1])],
            )
        returned_vertices = created.get("vertices")
        if returned_vertices is not None:
            normalized_vertices = [list(point) for point in returned_vertices]
            if normalized_vertices != vertices:
                self._raise_postcondition(
                    "Wire vertex read-back did not match the plan.",
                    net=operation.target,
                    expected_vertices=vertices,
                    observed_vertices=normalized_vertices,
                )
        evidence: dict[str, Any] = {"backend_response_type": type(created).__name__}
        if endpoints is not None:
            evidence["endpoints"] = [list(endpoints[0]), list(endpoints[1])]
        if returned_vertices is not None:
            evidence["vertices"] = normalized_vertices
        self._operation_completed(**evidence)

    async def _create_output(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        selector = operation.arguments.get("path")
        units = operation.arguments.get("units")
        expected_call_id = operation.arguments.get("call_id")
        creator = getattr(self.service, "create_output_channel", None)
        if not callable(creator):
            raise _error(
                "LCC_OUTPUT_INCOMPLETE",
                "The PSCAD service does not expose output-channel creation required by the LCC plan.",
                "create_lcc_output_channel",
                selector=selector,
                reason="output_channel_mutation_unavailable",
            )
        try:
            created = await creator(
                self.project_name,
                selector,
                units,
                call_id=expected_call_id,
            )
        except BackendError as error:
            raise _error(
                "LCC_OUTPUT_INCOMPLETE",
                "The PSCAD output-channel definition could not be created.",
                "create_lcc_output_channel",
                selector=selector,
                upstream_code=error.code,
            ) from error
        except BaseException as error:
            raise _error(
                "LCC_OUTPUT_INCOMPLETE",
                "The PSCAD output-channel definition could not be created.",
                "create_lcc_output_channel",
                selector=selector,
                exception=type(error).__name__,
            ) from error
        getter = getattr(self.service, "get_output_channels", None)
        if not callable(getter):
            raise _error(
                "LCC_OUTPUT_INCOMPLETE",
                "The PSCAD service does not expose verified output-channel metadata.",
                "verify_lcc_output_channel",
                selector=operation.arguments.get("path"),
            )
        try:
            channels = await getter(self.project_name)
        except BackendError as error:
            raise _error(
                "LCC_OUTPUT_INCOMPLETE",
                "The PSCAD output-channel metadata could not be verified.",
                "verify_lcc_output_channel",
                selector=operation.arguments.get("path"),
                upstream_code=error.code,
            ) from error
        except BaseException as error:
            raise _error(
                "LCC_OUTPUT_INCOMPLETE",
                "The PSCAD output-channel metadata could not be verified.",
                "verify_lcc_output_channel",
                selector=operation.arguments.get("path"),
                exception=type(error).__name__,
            ) from error
        if not isinstance(channels, (list, tuple)):
            raise _error(
                "LCC_OUTPUT_INCOMPLETE",
                "The PSCAD service returned invalid output-channel metadata.",
                "verify_lcc_output_channel",
                selector=operation.arguments.get("path"),
            )

        matches = [
            channel
            for channel in channels
            if isinstance(channel, dict) and channel.get("path") == selector
        ]
        if not matches:
            raise _error(
                "LCC_OUTPUT_INCOMPLETE",
                "A required PSCAD output selector was not declared.",
                "verify_lcc_output_channel",
                selector=selector,
                expected_units=units,
                expected_call_id=expected_call_id,
            )
        if len(matches) != 1:
            raise _error(
                "LCC_OUTPUT_INCOMPLETE",
                "A required PSCAD output selector is ambiguous.",
                "verify_lcc_output_channel",
                selector=selector,
                matches=len(matches),
            )
        observed = matches[0]
        if observed.get("units") != units:
            raise _error(
                "LCC_OUTPUT_INCOMPLETE",
                "A PSCAD output selector has unexpected units.",
                "verify_lcc_output_channel",
                selector=selector,
                expected_units=units,
                observed_units=observed.get("units"),
            )
        if expected_call_id is not None and observed.get("call_id") != expected_call_id:
            raise _error(
                "LCC_OUTPUT_INCOMPLETE",
                "A PSCAD output selector has an unexpected call ID.",
                "verify_lcc_output_channel",
                selector=selector,
                expected_call_id=expected_call_id,
                observed_call_id=observed.get("call_id"),
            )
        self._operation_completed(creation_response_type=type(created).__name__)

    def _graph_for(self, path: Path):
        catalog = self.asset_set.catalog if self.asset_set is not None else None
        return read_project_graph(path, catalog=catalog)

    def _validate_graph(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            self._raise_postcondition("The saved staging PSCX file does not exist.", path=str(path))
        graph = self._graph_for(path)
        catalog = self.asset_set.catalog if self.asset_set is not None else None
        is_final = self.target_path is not None and path.resolve() == self.target_path.resolve()
        expected_project_name = self.target_path.stem if is_final and self.target_path is not None else self.project_name
        result = validate_project_graph(
            graph,
            self.plan.blueprint,
            catalog=catalog,
            expected_project_name=expected_project_name,
            expected_pscad_version=self.plan.pscad_version,
        )
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
        stop_simulation = getattr(self.service, "stop_simulation", None)
        if not callable(stop_simulation):
            raise _error(
                "LCC_BUILD_FAILED",
                "The PSCAD service does not expose simulation stop control required for safe cleanup.",
                "run_lcc_project",
            )
        self._run_started_after = time.time()
        self._simulation_active = True
        # The run command can be submitted successfully even when its
        # acknowledgement raises. Mark it active before crossing that
        # boundary so failure cleanup still requests a stop.
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
                raise _error("LCC_BUILD_FAILED", "The PSCAD simulation failed.", "run_lcc_project", status=status, polls=polls)
            elif value in _TERMINAL_SUCCESS and observed_running:
                self._simulation_active = False
                self._record(LccBuildState.SIMULATED, polls=polls)
                return
            if time.monotonic() >= deadline:
                await self._stop_simulation("timeout")
                raise _error("LCC_BUILD_TIMED_OUT", "The PSCAD simulation did not reach a terminal state.", "run_lcc_project", polls=polls, timeout_s=self.timeout_s)
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
            evidence["simulation_stop"]["error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
        status_reader = getattr(self.service, "get_run_status", None)
        if callable(status_reader):
            statuses: list[str] = []
            for _ in range(20):
                try:
                    status = await status_reader(self.project_name)
                except BaseException as error:
                    evidence["simulation_stop"]["status_error"] = {
                        "type": type(error).__name__,
                        "message": str(error),
                    }
                    break
                value = _status_value(status)
                statuses.append(value)
                if value in _TERMINAL_SUCCESS or value in _TERMINAL_FAILURE:
                    break
                await asyncio.sleep(max(self.poll_interval_s, 0.01))
            evidence["simulation_stop"]["statuses"] = statuses
        self.history.append(evidence)
        self.journal.write(self._journal_payload())

    async def _acceptance_output(self) -> Any:
        discover = getattr(self.service, "discover_output_files", None)
        read_output = getattr(self.service, "read_output_file", None)
        if callable(discover) or callable(read_output):
            if not callable(discover) or not callable(read_output):
                raise _error(
                    "LCC_OUTPUT_INCOMPLETE",
                    "The PSCAD service does not expose both output discovery and reading capabilities.",
                    "read_lcc_output",
                )
            if self.staging_file is None:
                raise _error(
                    "LCC_OUTPUT_INCOMPLETE",
                    "The staging PSCX path is not available for output discovery.",
                    "discover_lcc_output",
                )
            paths = await discover(
                str(self.staging_file.resolve()),
                started_after=self._run_started_after if self._run_started_after is not None else time.time(),
                max_files=32,
            )
            if not isinstance(paths, (list, tuple)):
                raise _error(
                    "LCC_OUTPUT_INCOMPLETE",
                    "The PSCAD service returned an invalid output-file list.",
                    "discover_lcc_output",
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
                        "LCC_OUTPUT_INCOMPLETE",
                        "The PSCAD output file is not a regular file owned by the staging directory.",
                        "discover_lcc_output",
                        reason="output_not_regular",
                        path=str(candidate),
                    )
                resolved = candidate.resolve()
                try:
                    resolved.relative_to(staging_root)
                except ValueError as error:
                    raise _error(
                        "LCC_OUTPUT_INCOMPLETE",
                        "The PSCAD output file is outside the builder-owned staging directory.",
                        "discover_lcc_output",
                        reason="output_outside_staging",
                        path=str(resolved),
                    ) from error
                if resolved.suffix.casefold() not in {".out", ".psout"}:
                    raise _error(
                        "LCC_OUTPUT_INCOMPLETE",
                        "The PSCAD output file has an unsupported suffix.",
                        "discover_lcc_output",
                        reason="output_suffix_invalid",
                        path=str(resolved),
                    )
                if resolved.is_symlink() or not resolved.is_file():
                    raise _error(
                        "LCC_OUTPUT_INCOMPLETE",
                        "The PSCAD output file is not a regular file owned by the staging directory.",
                        "discover_lcc_output",
                        reason="output_not_regular",
                        path=str(resolved),
                    )
                candidates.append(str(resolved))
            if not candidates:
                raise _error(
                    "LCC_OUTPUT_INCOMPLETE",
                    "No PSCAD output file was created after the LCC simulation.",
                    "discover_lcc_output",
                    project_name=self.project_name,
                )
            candidates = sorted(set(candidates), key=str.casefold)
            if len(candidates) != 1:
                raise _error(
                    "LCC_OUTPUT_INCOMPLETE",
                    "Multiple PSCAD output files were created for the LCC simulation.",
                    "discover_lcc_output",
                    reason="output_ambiguous",
                    candidates=candidates,
                )
            self.output_file = candidates[0]
            return await read_output(self.output_file, max_samples=1_000_000, summary_only=False)

        get_project_output = getattr(self.service, "get_project_output", None)
        if not callable(get_project_output):
            raise _error(
                "LCC_OUTPUT_INCOMPLETE",
                "The PSCAD service does not expose an output reader.",
                "read_lcc_output",
            )
        return await get_project_output(self.project_name)

    async def _accept(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        output = await self._acceptance_output()
        if self.asset_set is not None:
            result = evaluate_acceptance(
                output,
                self.asset_set.golden,
                self.asset_set.acceptance,
                self.trusted_threshold_sources,
            )
        elif self.allow_test_double and isinstance(output, dict) and isinstance(output.get("verdict"), str):
            result = dict(output)
        elif self.allow_test_double:
            result = {"verdict": "PASS", "source": "executor-test-double"}
        else:
            result = {
                "verdict": "INCOMPLETE_ANALYSIS",
                "source": "executor",
                "reason": "verified_asset_set_required",
            }
        if self.output_file is not None:
            result = dict(result)
            result["output_file"] = self.output_file
            try:
                result["output_sha256"] = sha256_file(Path(self.output_file))
            except BackendError as error:
                raise _error(
                    "LCC_OUTPUT_INCOMPLETE",
                    "The selected PSCAD output file could not be hashed for acceptance evidence.",
                    "read_lcc_output",
                    output_file=self.output_file,
                    upstream_code=error.code,
                ) from error
        self.result = result
        if result.get("verdict") != "PASS":
            raise _error("LCC_ACCEPTANCE_FAILED", "The LCC acceptance contract did not pass.", "evaluate_lcc_acceptance", acceptance=result)
        self._record(LccBuildState.ACCEPTANCE_PASSED)

    async def _publish(self, operation: LccPlanOperation) -> None:
        self._operation_started(operation)
        if self.target_path is None:
            self._raise_postcondition("The build plan has no final target path.")
        if self.target_path.exists() or self.target_path.is_symlink():
            raise _error(
                "LCC_BUILD_CONFLICT",
                "The final publication target appeared after planning.",
                "publish_lcc_model",
                target_path=str(self.target_path),
            )
        await self.service.save_project_as(
            self.project_name,
            self.target_path.name,
            str(self.target_path.parent),
            confirm=False,
        )
        if not self.target_path.is_file():
            self._raise_postcondition("The final publication file was not created.", path=str(self.target_path))
        self._publication_created = True
        try:
            self._publication_hash = sha256_file(self.target_path)
        except BackendError as error:
            raise _error(
                "LCC_POSTCONDITION_FAILED",
                "The published final project is not a hashable regular file.",
                "publish_lcc_model",
                target_path=str(self.target_path),
                upstream_code=error.code,
            ) from error
        loader = getattr(self.service, "load_projects", None)
        if not callable(loader):
            raise _error(
                "LCC_BUILD_FAILED",
                "The PSCAD service does not expose final-project reloading.",
                "reload_lcc_published_project",
                target_path=str(self.target_path.resolve()),
            )
        final_path = self.target_path.resolve()
        await loader([str(final_path)])
        self._validate_graph(self.target_path)
        final_project_name = final_path.stem
        await self.service.build_project(final_project_name)
        self._validate_graph(self.target_path)
        try:
            final_project_hash = sha256_file(self.target_path)
        except BackendError as error:
            raise _error(
                "LCC_POSTCONDITION_FAILED",
                "The final project could not be hashed after compile smoke.",
                "publish_lcc_model",
                target_path=str(final_path),
                upstream_code=error.code,
            ) from error
        self._publication_hash = final_project_hash
        self._record(
            LccBuildState.PUBLISHED,
            target_path=str(final_path),
            final_project_name=final_project_name,
            final_compile_smoke=True,
            final_project_sha256=final_project_hash,
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
            self.history.append({"publication_cleanup": cleanup})
            self.journal.write(self._journal_payload())
            return
        try:
            observed_hash = sha256_file(self.target_path)
        except BackendError as error:
            cleanup["action"] = "preserved_unhashable_target"
            cleanup["error"] = {"code": error.code, "message": str(error)}
            self.history.append({"publication_cleanup": cleanup})
            self.journal.write(self._journal_payload())
            return
        if observed_hash != self._publication_hash:
            cleanup["action"] = "preserved_external_replacement"
            cleanup["expected_sha256"] = self._publication_hash
            cleanup["observed_sha256"] = observed_hash
            self.history.append({"publication_cleanup": cleanup})
            self.journal.write(self._journal_payload())
            return
        try:
            shutil.move(str(self.target_path), str(candidate))
        except OSError as error:
            cleanup["action"] = "preserved_move_failure"
            cleanup["error"] = {"type": type(error).__name__, "message": str(error)}
        else:
            cleanup["action"] = "quarantined_candidate"
        self.history.append({"publication_cleanup": cleanup})
        self.journal.write(self._journal_payload())


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
    allow_test_double: bool = False,
    trusted_threshold_sources: Any = None,
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
        allow_test_double=allow_test_double,
        trusted_threshold_sources=trusted_threshold_sources,
    ).run()


__all__ = ["LccExecutor", "execute_build"]
