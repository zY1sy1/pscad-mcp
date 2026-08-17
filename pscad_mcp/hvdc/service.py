"""Application service for deterministic HVDC workflows."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
import threading
from typing import Any, Mapping

from ..core.backend.base import BackendError
from ..core.path_policy import PathPolicy, WorkspaceNotConfiguredError
from .classifier import classify_topology, extract_assets
from .mappings import MappingResolution, resolve_mappings
from .profiles import list_profiles, load_profile, register_profile
from .scanner import scan_project


class HvdcDomainService:
    """Coordinate read-only inspection and safe domain operations."""

    def __init__(self, backend_service: Any | None = None, *, path_policy: Any | None = None) -> None:
        self.backend_service = backend_service
        self.path_policy = path_policy or PathPolicy()
        self._cache: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
        self._scenarios: dict[str, dict[str, Any]] = {}
        self._scenario_tasks: dict[str, asyncio.Task[None]] = {}
        self._scenario_run_tasks: dict[str, asyncio.Task[Any]] = {}
        self._scenario_operation_tasks: dict[str, dict[asyncio.Task[Any], str]] = {}
        self._scenario_settlement_tokens: dict[str, dict[Any, str]] = {}
        self._scenario_settlement_lock = threading.Lock()
        self._scenario_cleanup_tasks: dict[str, asyncio.Task[None]] = {}
        self._scenario_release_after_operations: set[str] = set()
        self._scenario_reservation_lock = asyncio.Lock()
        self._active_scenario_id: str | None = None

    def _pending_scenario_operations(self, scenario_id: str) -> list[str]:
        pending = [
            operation
            for task, operation in self._scenario_operation_tasks.get(scenario_id, {}).items()
            if not task.done()
        ]
        with self._scenario_settlement_lock:
            pending.extend(self._scenario_settlement_tokens.get(scenario_id, {}).values())
        return pending

    def _finish_scenario_operations_if_ready(self, scenario_id: str) -> None:
        if self._pending_scenario_operations(scenario_id):
            return
        self._scenario_operation_tasks.pop(scenario_id, None)
        with self._scenario_settlement_lock:
            self._scenario_settlement_tokens.pop(scenario_id, None)
        record = self._scenarios.get(scenario_id)
        if record is None or scenario_id not in self._scenario_release_after_operations:
            return
        self._scenario_release_after_operations.discard(scenario_id)
        if record.get("outcome") == "needs_review":
            record["outcome"] = "unknown_outcome"
            containment = record.get("containment")
            if isinstance(containment, dict) and containment.get("status") == "pending_operations":
                containment["status"] = "operations_completed"
                containment["outcome_known"] = False
        cleanup = asyncio.create_task(
            self._release_after_operation_completion(scenario_id),
            name=f"{scenario_id}-operation-cleanup",
        )
        self._scenario_cleanup_tasks[scenario_id] = cleanup

        def cleanup_finished(done: asyncio.Task[None]) -> None:
            if self._scenario_cleanup_tasks.get(scenario_id) is done:
                self._scenario_cleanup_tasks.pop(scenario_id, None)
            if not done.cancelled():
                done.exception()

        cleanup.add_done_callback(cleanup_finished)

    def _settlement_finished_on_origin_loop(
        self,
        scenario_id: str,
        token: Any,
    ) -> None:
        with self._scenario_settlement_lock:
            tracked = self._scenario_settlement_tokens.get(scenario_id)
            if tracked is None or token not in tracked:
                return
            operation = tracked.pop(token)
            if not tracked:
                self._scenario_settlement_tokens.pop(scenario_id, None)
        operations = self._scenario_operation_tasks.get(scenario_id)
        if operations is not None and all(task.done() for task in operations):
            self._scenario_operation_tasks.pop(scenario_id, None)
        record = self._scenarios.get(scenario_id)
        if record is not None:
            record.setdefault("operation_history", []).append(
                {
                    "operation": operation,
                    "status": "vendor_settled",
                    "generation": getattr(token, "generation", None),
                    "operation_id": getattr(token, "operation_id", None),
                }
            )
            record["pending_operations"] = self._pending_scenario_operations(scenario_id)
        self._finish_scenario_operations_if_ready(scenario_id)

    def _settlement_origin_loop_unavailable(
        self,
        scenario_id: str,
        token: Any,
    ) -> None:
        with self._scenario_settlement_lock:
            tracked = self._scenario_settlement_tokens.get(scenario_id)
            if tracked is None or token not in tracked:
                return
            tracked.pop(token)
            if not tracked:
                self._scenario_settlement_tokens.pop(scenario_id, None)
        operations = self._scenario_operation_tasks.get(scenario_id)
        if operations is not None and all(task.done() for task in operations):
            self._scenario_operation_tasks.pop(scenario_id, None)
        record = self._scenarios.get(scenario_id)
        if record is None:
            return
        warning = {
            "code": "SETTLEMENT_LOOP_UNAVAILABLE",
            "message": "The vendor operation settled after its scenario event loop closed; the application-wide lease remains held for review.",
            "operation_id": getattr(token, "operation_id", None),
            "generation": getattr(token, "generation", None),
        }
        if warning not in record.setdefault("warnings", []):
            record["warnings"].append(warning)
        record["pending_operations"] = []
        record["outcome"] = "unknown_outcome"
        record["containment"] = {
            "status": "settled_after_loop_closed",
            "outcome_known": False,
        }

    def _track_scenario_operation(
        self,
        scenario_id: str,
        task: asyncio.Task[Any],
        operation: str,
    ) -> None:
        operations = self._scenario_operation_tasks.setdefault(scenario_id, {})
        operations[task] = operation
        record = self._scenarios.get(scenario_id)
        if record is not None:
            record["pending_operations"] = list(operations.values())

        def operation_finished(completed: asyncio.Task[Any]) -> None:
            current = self._scenario_operation_tasks.get(scenario_id)
            if current is None or completed not in current:
                return
            name = current.pop(completed)
            result: dict[str, Any] = {"operation": name}
            if completed.cancelled():
                result["status"] = "cancelled"
            else:
                error = completed.exception()
                if error is None:
                    result["status"] = "completed"
                else:
                    result["status"] = "failed"
                    if isinstance(error, BackendError):
                        result["error"] = error.to_dict()
                    else:
                        result["error"] = {
                            "code": "HVDC_SCENARIO_EXECUTION_FAILED",
                            "message": str(error),
                            "backend": "hvdc",
                            "operation": name,
                        }
            executor = getattr(self.backend_service, "executor", None)
            pending_for = getattr(executor, "pending_settlements_for", None)
            settlements = list(pending_for(completed)) if callable(pending_for) else []
            added_settlements = 0
            origin_loop = completed.get_loop()
            for token in settlements:
                with self._scenario_settlement_lock:
                    tracked = self._scenario_settlement_tokens.setdefault(scenario_id, {})
                    if token in tracked:
                        continue
                    tracked[token] = f"{name}:vendor_settlement"

                def token_finished(settled: Any, *, loop: asyncio.AbstractEventLoop = origin_loop) -> None:
                    if loop.is_closed() or not loop.is_running():
                        self._settlement_origin_loop_unavailable(scenario_id, settled)
                        return
                    try:
                        loop.call_soon_threadsafe(
                            self._settlement_finished_on_origin_loop,
                            scenario_id,
                            settled,
                        )
                    except RuntimeError:
                        self._settlement_origin_loop_unavailable(scenario_id, settled)

                token.add_done_callback(token_finished)
                added_settlements += 1
            if added_settlements:
                result["status"] = "awaiting_vendor_settlement"
                result["settlement_count"] = added_settlements
            current_record = self._scenarios.get(scenario_id)
            if current_record is not None:
                current_record.setdefault("operation_history", []).append(result)
                current_record["pending_operations"] = self._pending_scenario_operations(scenario_id)
            self._finish_scenario_operations_if_ready(scenario_id)

        task.add_done_callback(operation_finished)

    async def _release_after_operation_completion(self, scenario_id: str) -> None:
        if self._pending_scenario_operations(scenario_id):
            return
        await self._release_scenario(scenario_id)

    async def _request_scenario_release(
        self,
        scenario_id: str,
        *,
        after_pending_operations: bool,
    ) -> bool:
        pending = self._pending_scenario_operations(scenario_id)
        operations_tracked = scenario_id in self._scenario_operation_tasks
        if pending or operations_tracked:
            record = self._scenarios.get(scenario_id)
            if record is not None:
                record["pending_operations"] = pending
            if after_pending_operations:
                self._scenario_release_after_operations.add(scenario_id)
            return False
        if after_pending_operations:
            await self._release_after_operation_completion(scenario_id)
            return True
        return False

    async def _reserve_scenario(self, scenario_id: str) -> None:
        async with self._scenario_reservation_lock:
            if self._active_scenario_id is not None:
                active = self._scenarios.get(self._active_scenario_id, {})
                raise BackendError(
                    "HVDC_SCENARIO_CONFLICT",
                    "Only one application-wide HVDC scenario may be active at a time.",
                    "hvdc",
                    "run_hvdc_scenario",
                    {
                        "active_scenario_id": self._active_scenario_id,
                        "active_status": active.get("status"),
                        "active_outcome": active.get("outcome"),
                    },
                )
            self._active_scenario_id = scenario_id

    async def _release_scenario(self, scenario_id: str) -> bool:
        async with self._scenario_reservation_lock:
            if self._active_scenario_id != scenario_id:
                return False
            self._active_scenario_id = None
            self._scenario_release_after_operations.discard(scenario_id)
            record = self._scenarios.get(scenario_id)
            if record is not None:
                record["reservation_held"] = False
            return True

    def _workspace_root(self) -> Path | None:
        root = getattr(self.path_policy, "workspace_root", None)
        return Path(root).resolve() if root is not None else None

    def _resolve_project(self, project_name: str) -> Path:
        if not isinstance(project_name, str) or not project_name.strip():
            raise BackendError("INVALID_ARGUMENT", "project_name must be a non-empty string.", "hvdc", "inspect_hvdc_project")
        candidate = Path(project_name).expanduser()
        if candidate.suffix.lower() != ".pscx":
            candidate = candidate.with_suffix(".pscx")
        # Inspection is strictly read-only, so an existing absolute PSCX may
        # be scanned as an external source. Mutation paths still require the
        # configured workspace and confirmation gates below.
        if candidate.is_absolute() and candidate.exists():
            return candidate.resolve()
        try:
            try:
                return self.path_policy.resolve(str(candidate), suffixes={".pscx"}, must_exist=True)
            except TypeError:
                return self.path_policy.resolve(str(candidate))
        except WorkspaceNotConfiguredError as error:
            raise BackendError("WORKSPACE_NOT_CONFIGURED", str(error), "hvdc", "inspect_hvdc_project", {"candidate": project_name}) from error
        except FileNotFoundError as error:
            raise BackendError("NOT_FOUND", f"HVDC project '{project_name}' was not found.", "hvdc", "inspect_hvdc_project", {"candidate": project_name}) from error
        except ValueError as error:
            raise BackendError("INVALID_ARGUMENT", str(error), "hvdc", "inspect_hvdc_project", {"candidate": project_name}) from error

    def _resolve_mutation_project(self, project_name: str) -> Path:
        candidate = Path(project_name).expanduser()
        if candidate.suffix.lower() != ".pscx":
            candidate = candidate.with_suffix(".pscx")
        try:
            try:
                return self.path_policy.resolve(str(candidate), suffixes={".pscx"}, must_exist=True)
            except TypeError:
                return self.path_policy.resolve(str(candidate))
        except WorkspaceNotConfiguredError as error:
            raise BackendError("WORKSPACE_NOT_CONFIGURED", str(error), "hvdc", "run_hvdc_scenario", {"candidate": project_name}) from error
        except FileNotFoundError as error:
            raise BackendError("NOT_FOUND", f"HVDC target project '{project_name}' was not found.", "hvdc", "run_hvdc_scenario", {"candidate": project_name}) from error
        except ValueError as error:
            raise BackendError("INVALID_ARGUMENT", str(error), "hvdc", "run_hvdc_scenario", {"candidate": project_name}) from error

    def _resolve_output_file(self, file_path: str, *, must_exist: bool = False) -> Path:
        try:
            try:
                return self.path_policy.resolve(
                    file_path,
                    suffixes={".psout", ".out"},
                    must_exist=must_exist,
                )
            except TypeError:
                return self.path_policy.resolve(file_path)
        except WorkspaceNotConfiguredError as error:
            raise BackendError("WORKSPACE_NOT_CONFIGURED", str(error), "hvdc", "run_hvdc_scenario", {"candidate": file_path}) from error
        except FileNotFoundError as error:
            raise BackendError("NOT_FOUND", f"HVDC output file '{file_path}' was not found.", "hvdc", "run_hvdc_scenario", {"candidate": file_path}) from error
        except ValueError as error:
            raise BackendError("INVALID_ARGUMENT", str(error), "hvdc", "run_hvdc_scenario", {"candidate": file_path}) from error

    def _inspection(self, project_name: str, canvas_name: str = "Main") -> dict[str, Any]:
        path = self._resolve_project(project_name)
        key = (str(path), canvas_name.casefold())
        mtime = path.stat().st_mtime_ns
        cached = self._cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        evidence = scan_project(path, canvas_name)
        topology = classify_topology(evidence)
        assets = extract_assets(evidence)
        profile_name = "hvdc_breaker_difforder" if any(asset.kind == "breaker" for asset in assets) else "auto"
        mappings: MappingResolution
        unresolved: list[str]
        if profile_name == "auto":
            mappings = MappingResolution((), (), ())
            unresolved = []
        else:
            mappings = resolve_mappings(evidence, load_profile(profile_name, workspace_root=self._workspace_root()))
            unresolved = list(mappings.unresolved)
        result = {
            "project": {"name": evidence.project_name, "path": evidence.project_path, "pscad_version": evidence.pscad_version, "canvas": canvas_name},
            "evidence": asdict(evidence),
            "topology": asdict(topology),
            "assets": [asdict(asset) for asset in assets],
            "mappings": [asdict(mapping) for mapping in mappings.mappings],
            "unresolved": unresolved,
            "mapping_conflicts": list(mappings.conflicts),
            "warnings": list(evidence.warnings) + list(mappings.warnings),
            "confidence": topology.confidence,
        }
        self._cache[key] = (mtime, result)
        return result

    def inspect_project(self, project_name: str, canvas_name: str = "Main") -> dict[str, Any]:
        return self._inspection(project_name, canvas_name)

    def get_assets(self, project_name: str, kind: str | None = None, canvas_name: str = "Main") -> list[dict[str, Any]]:
        assets = self._inspection(project_name, canvas_name)["assets"]
        return [asset for asset in assets if kind is None or asset["kind"] == kind]

    def get_mappings(self, project_name: str, canonical: str | None = None, canvas_name: str = "Main") -> dict[str, Any]:
        result = self._inspection(project_name, canvas_name)
        mappings = [item for item in result["mappings"] if canonical is None or item["canonical"] == canonical]
        return {"mappings": mappings, "unresolved": result["unresolved"], "conflicts": result.get("mapping_conflicts", []), "warnings": result["warnings"]}

    def resolve_scenario_mappings(self, project_name: str, profile: str, canvas_name: str = "Main") -> dict[str, Any]:
        """Resolve mutation bindings against the explicitly selected profile."""
        evidence = scan_project(self._resolve_project(project_name), canvas_name)
        resolution = resolve_mappings(
            evidence,
            load_profile(profile, workspace_root=self._workspace_root()),
        )
        return {
            "mappings": [asdict(mapping) for mapping in resolution.mappings],
            "unresolved": list(resolution.unresolved),
            "conflicts": list(resolution.conflicts),
            "warnings": list(resolution.warnings),
        }

    def validate_project(self, project_name: str, profile: str = "auto", canvas_name: str = "Main") -> dict[str, Any]:
        result = self._inspection(project_name, canvas_name)
        profile_name = profile
        if profile == "auto":
            profile_name = "hvdc_breaker_difforder" if any(item["kind"] == "breaker" for item in result["assets"]) else "lcc_bipolar_generic"
        loaded = load_profile(profile_name, workspace_root=self._workspace_root())
        if profile_name != "auto":
            evidence = scan_project(self._resolve_project(project_name), canvas_name)
            resolution = resolve_mappings(evidence, loaded)
            result = dict(result)
            result["mappings"] = [asdict(mapping) for mapping in resolution.mappings]
            result["unresolved"] = list(resolution.unresolved)
            result["mapping_conflicts"] = list(resolution.conflicts)
            result["warnings"] = list(result.get("warnings", [])) + list(resolution.warnings)
        found = {item["kind"] for item in result["assets"]}
        missing_assets = sorted(set(loaded.get("required_assets", [])) - found)
        errors: list[dict[str, Any]] = []
        if result["topology"]["family"] == "unknown":
            errors.append({"code": "HVDC_TOPOLOGY_AMBIGUOUS", "message": "Topology family is unknown.", "evidence": result["topology"]["evidence"]})
        if missing_assets:
            errors.append({"code": "HVDC_MAPPING_MISSING", "message": "Required HVDC assets are missing.", "missing_assets": missing_assets})
        if result.get("mapping_conflicts"):
            errors.append({"code": "HVDC_MAPPING_CONFLICT", "message": "One or more semantic mappings have duplicate or incompatible evidence.", "conflicts": result["mapping_conflicts"]})
        return {"valid": not errors and not result["unresolved"], "profile": profile_name, "missing_assets": missing_assets, "unresolved": result["unresolved"], "errors": errors, "warnings": result["warnings"], "topology": result["topology"]}

    def list_profiles(self) -> list[dict[str, Any]]:
        root = self._workspace_root()
        return [{"name": name, "profile": load_profile(name, workspace_root=root)} for name in list_profiles(root)]

    def register_profile(self, profile_name: str, mapping_file: str) -> dict[str, Any]:
        try:
            try:
                resolved = self.path_policy.resolve(mapping_file, suffixes={".json"}, must_exist=True)
            except TypeError:
                resolved = self.path_policy.resolve(mapping_file)
        except WorkspaceNotConfiguredError as error:
            raise BackendError("WORKSPACE_NOT_CONFIGURED", str(error), "hvdc", "register_hvdc_profile", {"candidate": mapping_file}) from error
        except FileNotFoundError as error:
            raise BackendError("NOT_FOUND", f"HVDC mapping file '{mapping_file}' was not found.", "hvdc", "register_hvdc_profile", {"candidate": mapping_file}) from error
        except ValueError as error:
            raise BackendError("INVALID_ARGUMENT", str(error), "hvdc", "register_hvdc_profile", {"candidate": mapping_file}) from error
        return register_profile(profile_name, str(resolved), workspace_root=self._workspace_root())

    async def validate_scenario(self, scenario: Mapping[str, Any]) -> dict[str, Any]:
        from .scenarios import validate_scenario
        return validate_scenario(scenario, workspace_root=self._workspace_root())

    async def run_scenario(self, project_name: str, scenario: Mapping[str, Any], confirm: bool = False) -> dict[str, Any]:
        from .scenarios import run_scenario
        return await run_scenario(self, project_name, scenario, confirm=confirm, workspace_root=self._workspace_root())

    async def scenario_status(self, scenario_id: str) -> dict[str, Any]:
        if scenario_id not in self._scenarios:
            raise BackendError("NOT_FOUND", f"Scenario '{scenario_id}' was not found.", "hvdc", "get_hvdc_scenario_status", {"scenario_id": scenario_id})
        record = self._scenarios[scenario_id]
        backend = self.backend_service
        target_project = record.get("target_project")
        if backend is not None and target_project:
            get_status = getattr(backend, "get_run_status", None)
            if callable(get_status):
                try:
                    project_status = await get_status(target_project)
                    if isinstance(project_status, Mapping):
                        record["project_status"] = dict(project_status)
                        status = str(project_status.get("status", "")).casefold()
                        task = self._scenario_tasks.get(scenario_id)
                        orchestration_active = task is not None and not task.done()
                        pending_operations = self._pending_scenario_operations(scenario_id)
                        operations_tracked = scenario_id in self._scenario_operation_tasks
                        if (
                            not orchestration_active
                            and not pending_operations
                            and not operations_tracked
                            and record.get("outcome") == "needs_review"
                            and status in {"completed", "complete", "finished", "done", "idle", "stopped", "failed", "error", "aborted"}
                        ):
                            record["containment"] = {
                                "status": "contained",
                                "project_status": dict(project_status),
                                "confirmed_by": "get_hvdc_scenario_status",
                            }
                            record["outcome"] = "contained_after_status_refresh"
                            await self._release_scenario(scenario_id)
                        if not orchestration_active and record.get("status") in {"validated", "running"}:
                            if status in {"completed", "complete", "finished", "done", "idle", "stopped"}:
                                from .scenarios import transition_scenario
                                transition_scenario(record, "completed")
                            elif status in {"failed", "error", "aborted"}:
                                from .scenarios import transition_scenario
                                record["error"] = BackendError(
                                    "HVDC_SCENARIO_RUN_FAILED",
                                    f"PSCAD project '{target_project}' reported terminal status '{status}'.",
                                    "hvdc",
                                    "get_hvdc_scenario_status",
                                    {"project_name": target_project, "project_status": dict(project_status)},
                                ).to_dict()
                                transition_scenario(record, "failed")
                except Exception as error:
                    warning = {
                        "code": "PROJECT_STATUS_UNAVAILABLE",
                        "message": str(error),
                    }
                    if isinstance(error, BackendError):
                        warning["error"] = error.to_dict()
                    if warning not in record.setdefault("warnings", []):
                        record["warnings"].append(warning)
            get_messages = getattr(backend, "get_project_output", None)
            if callable(get_messages):
                try:
                    messages = await get_messages(target_project, structured=True)
                    if isinstance(messages, list):
                        record["messages"] = [dict(item) if isinstance(item, Mapping) else {"severity": "info", "text": str(item), "source": None} for item in messages]
                except Exception as error:
                    warning = {"code": "PROJECT_MESSAGES_UNAVAILABLE", "message": str(error)}
                    if isinstance(error, BackendError):
                        warning["error"] = error.to_dict()
                    if warning not in record.setdefault("warnings", []):
                        record["warnings"].append(warning)
        return dict(record)

    async def analyze_results(self, scenario_id: str, metrics: list[str] | None = None) -> dict[str, Any]:
        from .metrics import calculate_metrics
        from .results import resolve_result_channels

        record = self._scenarios.get(scenario_id)
        if record is None:
            raise BackendError("NOT_FOUND", f"Scenario '{scenario_id}' was not found.", "hvdc", "analyze_hvdc_results", {"scenario_id": scenario_id})
        samples = record.get("samples")
        if samples is None and record.get("output_files") and self.backend_service is not None:
            try:
                samples = await self.backend_service.read_output_file(record["output_files"][0], summary_only=False)
            except Exception as error:
                record.setdefault("warnings", []).append(str(error))
        samples = samples or {"time": [], "channels": {}}
        profile = load_profile(
            record.get("profile", "lcc_bipolar_generic"),
            workspace_root=self._workspace_root(),
        )
        resolution = resolve_result_channels(samples, profile)
        analysis = record.get("analysis", {})
        analysis_baselines = (
            analysis.get("recovery_baselines", {})
            if isinstance(analysis, Mapping)
            else {}
        )
        normalized_samples = dict(resolution["samples"])
        recovery_baselines: dict[str, Any] = {}
        for source in (
            analysis_baselines,
            record.get("recovery_baselines", {}),
        ):
            if isinstance(source, Mapping):
                recovery_baselines.update(source)
        normalized_samples["recovery_baselines"] = recovery_baselines
        record["recovery_baselines"] = dict(recovery_baselines)
        configured_metrics = (
            analysis.get("metrics") if isinstance(analysis, Mapping) else None
        )
        selected_metrics = metrics if metrics is not None else configured_metrics
        result = calculate_metrics(normalized_samples, selected_metrics, profile=profile)
        result["warnings"] = [*resolution["warnings"], *result["warnings"]]
        record["resolved_channels"] = resolution["resolved_channels"]
        record["metrics"] = result["metrics"]
        record["verdict"] = result["verdict"]
        record.setdefault("warnings", []).extend(result["warnings"])
        return {
            "scenario_id": scenario_id,
            "resolved_channels": list(record["resolved_channels"]),
            **result,
        }

    async def compare_scenarios(self, scenario_ids: list[str], metrics: list[str] | None = None) -> dict[str, Any]:
        if not isinstance(scenario_ids, list) or not scenario_ids:
            raise BackendError("INVALID_ARGUMENT", "scenario_ids must not be empty.", "hvdc", "compare_hvdc_scenarios")
        records: list[dict[str, Any]] = []
        for scenario_id in scenario_ids:
            if scenario_id not in self._scenarios:
                raise BackendError("NOT_FOUND", f"Scenario '{scenario_id}' was not found.", "hvdc", "compare_hvdc_scenarios", {"scenario_id": scenario_id})
            if metrics is not None or not self._scenarios[scenario_id].get("metrics"):
                await self.analyze_results(scenario_id, metrics)
            records.append(self._scenarios[scenario_id])
        names = metrics or sorted({item["name"] for record in records for item in record.get("metrics", [])})
        comparisons: list[dict[str, Any]] = []
        for name in names:
            values = [next((item.get("value") for item in record.get("metrics", []) if item.get("name") == name), None) for record in records]
            baseline = values[0]
            for index, value in enumerate(values[1:], start=1):
                comparisons.append({"metric": name, "baseline": scenario_ids[0], "scenario_id": scenario_ids[index], "baseline_value": baseline, "value": value, "delta": None if baseline is None or value is None else value - baseline})
        return {"scenario_ids": scenario_ids, "comparisons": comparisons, "verdicts": {record["scenario_id"]: record.get("verdict") for record in records}}
