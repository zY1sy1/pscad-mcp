"""Public asynchronous lifecycle for the fixed LCC builder."""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ....core.backend.base import BackendError
from ....core.path_policy import PathPolicy, WorkspaceNotConfiguredError
from ....core.service import ConfirmationRequired
from .assets import LccAssetSet, load_packaged_asset_set
from .executor import execute_build
from .journal import AtomicJournal, WorkspaceBuildLease
from .models import LccBuildPlan, LccBuildRecord, LccBuildState
from .planner import LccPlanRequest, create_plan
from .project_graph import read_project_graph
from .validator import validate_project_graph


def _service_error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _workspace_from(service: Any, workspace_root: str | Path | None) -> Path:
    candidate = workspace_root
    if candidate is None:
        path_policy = getattr(service, "path_policy", None)
        candidate = getattr(path_policy, "workspace_root", None)
    if candidate is None:
        raise _service_error(
            "LCC_LAYOUT_INVALID",
            "A configured workspace is required for LCC builds.",
            "plan_lcc_model",
        )
    return Path(candidate).expanduser().resolve()


class LccBuilderService:
    """Compose planning, execution, validation, journaling, and leases."""

    def __init__(
        self,
        pscad_service: Any,
        *,
        workspace_root: str | Path | None = None,
        inventory: Any = None,
        asset_loader: Callable[[str], LccAssetSet] = load_packaged_asset_set,
        executor_factory: Callable[..., Any] = execute_build,
    ) -> None:
        self.pscad_service = pscad_service
        self.path_policy = getattr(pscad_service, "path_policy", None) or PathPolicy(workspace_root=str(workspace_root) if workspace_root else None)
        self.workspace_root = _workspace_from(pscad_service, workspace_root)
        self.inventory = inventory
        self.asset_loader = asset_loader
        self.executor_factory = executor_factory
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._records: dict[str, LccBuildRecord | dict[str, Any]] = {}
        self._leases: dict[str, WorkspaceBuildLease] = {}

    def _inventory_for(self, asset_set: LccAssetSet) -> Any:
        if self.inventory is not None:
            return self.inventory() if callable(self.inventory) else self.inventory
        candidate = getattr(self.pscad_service, "lcc_inventory", None)
        if candidate is not None:
            return candidate() if callable(candidate) else candidate
        definitions: dict[str, dict[str, Any]] = {}
        for definition in asset_set.catalog.get("definitions", ()):
            if isinstance(definition, dict) and isinstance(definition.get("scoped_name"), str):
                definitions[definition["scoped_name"]] = {
                    "ports": [port.get("name") for port in definition.get("ports", ()) if isinstance(port, dict)]
                }
        return {"pscad_version": asset_set.pscad_version, "definitions": definitions}

    def _load_assets(self, blueprint: str) -> LccAssetSet:
        return self.asset_loader(blueprint)

    def _create_plan(self, request: LccPlanRequest) -> LccBuildPlan:
        asset_set = self._load_assets(request.blueprint)
        return create_plan(request, asset_set, self._inventory_for(asset_set), self.path_policy)

    def plan_model(
        self,
        project_name: str,
        folder: str | None = None,
        simulation_duration_s: float | None = None,
        blueprint: str = "cigre_lcc_monopole_v1",
    ) -> dict[str, Any]:
        request = LccPlanRequest(project_name, folder, simulation_duration_s, blueprint)
        return self._create_plan(request).to_dict()

    def _plan_stale(self, expected: str, observed: str) -> BackendError:
        return _service_error(
            "LCC_PLAN_STALE",
            "The supplied plan hash no longer matches the current deterministic plan.",
            "build_lcc_model",
            expected_plan_hash=expected,
            observed_plan_hash=observed,
            retryable=True,
            suggested_action="Call plan_lcc_model again and confirm the new plan hash.",
        )

    async def build_model(
        self,
        project_name: str,
        expected_plan_hash: str,
        folder: str | None = None,
        simulation_duration_s: float | None = None,
        blueprint: str = "cigre_lcc_monopole_v1",
        confirm: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise ConfirmationRequired("build_lcc_model")
        request = LccPlanRequest(project_name, folder, simulation_duration_s, blueprint)
        plan = self._create_plan(request)
        if not isinstance(expected_plan_hash, str) or not secrets.compare_digest(plan.plan_hash, expected_plan_hash):
            raise self._plan_stale(expected_plan_hash if isinstance(expected_plan_hash, str) else "", plan.plan_hash)
        return await self._start_build(plan)

    async def _start_build(self, plan: LccBuildPlan) -> dict[str, Any]:
        build_id = uuid.uuid4().hex
        lease = WorkspaceBuildLease.acquire(self.workspace_root, build_id)
        journal = AtomicJournal(self.workspace_root, build_id)
        initial = LccBuildRecord(
            build_id=build_id,
            state=LccBuildState.VALIDATED,
            plan=plan,
            history=({"state": LccBuildState.VALIDATED.value},),
            workspace=str(self.workspace_root),
        )
        self._records[build_id] = initial
        self._leases[build_id] = lease
        journal.write(initial.to_dict())
        asset_set = self._load_assets(plan.metadata.get("blueprint", plan.blueprint.name))
        task = asyncio.create_task(self._run_build(build_id, plan, asset_set, journal, lease))
        self._tasks[build_id] = task
        task.add_done_callback(lambda completed: self._task_done(build_id, completed))
        return {
            "build_id": build_id,
            "state": LccBuildState.VALIDATED.value,
            "plan_hash": plan.plan_hash,
            "target_path": plan.target_path,
        }

    async def _run_build(
        self,
        build_id: str,
        plan: LccBuildPlan,
        asset_set: LccAssetSet,
        journal: AtomicJournal,
        lease: WorkspaceBuildLease,
    ) -> LccBuildRecord:
        try:
            record = await self.executor_factory(
                plan,
                self.pscad_service,
                self.workspace_root,
                asset_set=asset_set,
                build_id=build_id,
                journal=journal,
            )
        except asyncio.CancelledError:
            record = LccBuildRecord(
                build_id=build_id,
                state=LccBuildState.INTERRUPTED,
                plan=plan,
                history=({"state": LccBuildState.VALIDATED.value}, {"state": LccBuildState.INTERRUPTED.value}),
                error=_service_error("LCC_BUILD_FAILED", "The LCC build was interrupted.", "build_lcc_model").to_dict(),
                workspace=str(self.workspace_root),
            )
            journal.write(record.to_dict())
        except BaseException as error:
            backend_error = error if isinstance(error, BackendError) else _service_error("LCC_BUILD_FAILED", str(error), "build_lcc_model", exception=type(error).__name__)
            record = LccBuildRecord(
                build_id=build_id,
                state=LccBuildState.FAILED,
                plan=plan,
                history=({"state": LccBuildState.VALIDATED.value}, {"state": LccBuildState.FAILED.value}),
                error=backend_error.to_dict(),
                workspace=str(self.workspace_root),
            )
            journal.write(record.to_dict())
        finally:
            lease.release(lease.token)
            self._leases.pop(build_id, None)
        if record.error and record.error.get("code") == "LCC_BUILD_TIMED_OUT" and record.state == LccBuildState.FAILED:
            record = replace(record, state=LccBuildState.TIMED_OUT)
            journal.write(record.to_dict())
        self._records[build_id] = record
        return record

    def _task_done(self, build_id: str, task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except BaseException:
            # The lifecycle record is written by _run_build; consume any
            # unexpected task exception so it cannot become an unhandled task.
            pass
        self._tasks.pop(build_id, None)

    def _journal_path(self, build_id: str) -> Path:
        return AtomicJournal(self.workspace_root, build_id).path

    def _load_record(self, build_id: str) -> LccBuildRecord | dict[str, Any]:
        if build_id in self._records:
            return self._records[build_id]
        path = self._journal_path(build_id)
        if not path.is_file():
            raise _service_error("NOT_FOUND", f"LCC build '{build_id}' was not found.", "get_lcc_build_status", build_id=build_id)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise _service_error("LCC_JOURNAL_INVALID", "The LCC build journal could not be read.", "get_lcc_build_status", build_id=build_id) from error
        if not isinstance(record, dict):
            raise _service_error("LCC_JOURNAL_INVALID", "The LCC build journal is not an object.", "get_lcc_build_status", build_id=build_id)
        self._records[build_id] = record
        return record

    def get_build_status(self, build_id: str) -> dict[str, Any]:
        record = self._load_record(build_id)
        return record.to_dict() if isinstance(record, LccBuildRecord) else dict(record)

    def _output_path(self, project_name: str, output_file: str | None) -> Path:
        if output_file is not None:
            try:
                return self.path_policy.resolve(output_file, suffixes={".pscx"}, must_exist=True)
            except (WorkspaceNotConfiguredError, ValueError, OSError) as error:
                raise _service_error("LCC_LAYOUT_INVALID", str(error), "validate_lcc_model", output_file=output_file) from error
        try:
            return self.path_policy.resolve_child(str(self.workspace_root), f"{project_name}.pscx", suffixes={".pscx"}, must_exist=True)
        except (ValueError, OSError) as error:
            raise _service_error("LCC_LAYOUT_INVALID", str(error), "validate_lcc_model", project_name=project_name) from error

    def validate_model(
        self,
        project_name: str,
        blueprint: str = "cigre_lcc_monopole_v1",
        output_file: str | None = None,
    ) -> dict[str, Any]:
        asset_set = self._load_assets(blueprint)
        path = self._output_path(project_name, output_file)
        graph = read_project_graph(path, catalog=asset_set.catalog)
        result = validate_project_graph(graph, asset_set.blueprint, catalog=asset_set.catalog)
        result["output_file"] = str(path)
        return result


__all__ = ["LccBuilderService"]
