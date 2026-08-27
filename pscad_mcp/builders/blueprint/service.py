"""Asynchronous planning, execution, validation, and publication service."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import secrets
import shutil
from typing import Any, Awaitable, Callable, Mapping
import uuid

from ...core.backend.base import BackendError
from ...core.path_policy import PathPolicy
from ...core.service import ConfirmationRequired
from .assets import BlueprintAsset, audit_source_package, load_blueprint_asset
from .executor import execute_build
from .inventory import InventorySnapshot, read_live_inventory
from .journal import BuildJournal, WorkspaceBuildLease, next_state, write_json_atomic
from .models import BlueprintBuildRecord, BlueprintBuildState, BlueprintPlan, freeze, json_safe
from .planner import create_plan, plan_from_dict
from .validator import validate_staging, write_validation_report


def _error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "blueprint", operation, details)


class BlueprintBuilderService:
    def __init__(
        self,
        pscad_service: Any,
        *,
        workspace_root: str | Path | None = None,
        asset_root: str | Path | None = None,
        inventory_reader: Callable[[Any, str, str | None], Awaitable[InventorySnapshot]] = read_live_inventory,
        executor_factory: Callable[..., Awaitable[BlueprintBuildRecord]] = execute_build,
        trusted_source_classes: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.pscad_service = pscad_service
        configured = workspace_root
        if configured is None:
            configured = getattr(getattr(pscad_service, "path_policy", None), "workspace_root", None)
        if configured is None:
            raise _error("BLUEPRINT_WORKSPACE_REQUIRED", "A configured workspace is required.", "plan_pscad_project_build")
        self.workspace_root = Path(configured).expanduser().resolve()
        self.path_policy = PathPolicy(str(self.workspace_root))
        self.asset_root = Path(asset_root).resolve() if asset_root is not None else None
        self.inventory_reader = inventory_reader
        self.executor_factory = executor_factory
        self.trusted_source_classes = trusted_source_classes
        self._plans: dict[str, BlueprintPlan] = {}
        self._records: dict[str, BlueprintBuildRecord] = {}
        self._tasks: dict[str, asyncio.Task[BlueprintBuildRecord]] = {}
        self._leases: dict[str, WorkspaceBuildLease] = {}

    def _load_asset(self, value: str | Mapping[str, Any]) -> BlueprintAsset:
        return load_blueprint_asset(value, asset_root=self.asset_root)

    async def _create_plan(
        self,
        blueprint: str | Mapping[str, Any],
        source_package_path: str,
        target_name: str,
        parameter_overrides: Mapping[str, Mapping[str, Any]] | None,
    ) -> BlueprintPlan:
        asset = self._load_asset(blueprint)
        audit = audit_source_package(asset.blueprint, source_package_path, self.path_policy)
        await self.pscad_service.load_projects([audit.entry_point])
        project_name = Path(audit.entry_point).stem
        inventory = await self.inventory_reader(
            self.pscad_service,
            project_name,
            asset.blueprint.identity.inspection_profile,
        )
        return create_plan(
            asset,
            source_package_path,
            target_name,
            inventory,
            self.path_policy,
            parameter_overrides=parameter_overrides,
        )

    async def plan_project(
        self,
        blueprint: str | Mapping[str, Any],
        source_package_path: str,
        target_name: str,
        parameter_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        plan = await self._create_plan(blueprint, source_package_path, target_name, parameter_overrides)
        self._plans[plan.plan_hash] = plan
        return plan.to_dict()

    async def build_project(
        self,
        expected_plan_hash: str,
        blueprint: str | Mapping[str, Any],
        source_package_path: str,
        target_name: str,
        parameter_overrides: Mapping[str, Mapping[str, Any]] | None = None,
        *,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise ConfirmationRequired("build_pscad_project")
        plan = await self._create_plan(blueprint, source_package_path, target_name, parameter_overrides)
        expected = expected_plan_hash if isinstance(expected_plan_hash, str) else ""
        if not secrets.compare_digest(plan.plan_hash, expected):
            raise _error(
                "BLUEPRINT_PLAN_STALE",
                "The supplied plan hash does not match the current audited plan.",
                "build_pscad_project",
                expected_plan_hash=expected,
                observed_plan_hash=plan.plan_hash,
                retryable=True,
                suggested_action="Call plan_pscad_project_build again and confirm the new plan hash.",
            )
        self._plans[plan.plan_hash] = plan
        build_id = uuid.uuid4().hex
        lease = WorkspaceBuildLease.acquire(self.workspace_root, build_id)
        initial = BlueprintBuildRecord(
            build_id,
            BlueprintBuildState.PLANNED,
            plan,
            freeze(({"state": "planned"},)),
            freeze(plan.resolved_selectors),
        )
        self._records[build_id] = initial
        self._leases[build_id] = lease
        try:
            task = asyncio.create_task(self._run_build(build_id, plan, lease))
            self._tasks[build_id] = task
            task.add_done_callback(lambda completed, identity=build_id: self._task_done(identity, completed))
        except BaseException:
            self._leases.pop(build_id, None)
            lease.release(lease.token)
            raise
        return {
            "build_id": build_id,
            "state": "planned",
            "plan_hash": plan.plan_hash,
            "status_tool": "get_pscad_project_build_status",
        }

    def _task_done(self, build_id: str, task: asyncio.Task[BlueprintBuildRecord]) -> None:
        try:
            task.exception()
        except (asyncio.CancelledError, Exception):
            pass

    async def _run_build(
        self,
        build_id: str,
        plan: BlueprintPlan,
        lease: WorkspaceBuildLease,
    ) -> BlueprintBuildRecord:
        try:
            record = await self.executor_factory(
                plan,
                self.pscad_service,
                self.workspace_root,
                build_id=build_id,
                trusted_source_classes=self.trusted_source_classes,
            )
            if record.state is BlueprintBuildState.ACCEPTANCE_PASSED and plan.blueprint.publication.delivery_package:
                record = self._publish(record)
            self._records[build_id] = record
            return record
        except BaseException as caught:
            error = caught if isinstance(caught, BackendError) else _error(
                "BLUEPRINT_BUILD_FAILED",
                "Blueprint orchestration failed.",
                "build_pscad_project",
                exception=type(caught).__name__,
            )
            current = self._records[build_id]
            failed = replace(
                current,
                state=BlueprintBuildState.FAILED,
                history=freeze((*current.history, {"state": "failed"})),
                error=freeze(error.to_dict()),
            )
            self._records[build_id] = failed
            return failed
        finally:
            self._leases.pop(build_id, None)
            lease.release(lease.token)

    def _publish(self, record: BlueprintBuildRecord) -> BlueprintBuildRecord:
        if record.staging_path is None or record.result is None:
            raise _error("BLUEPRINT_PUBLICATION_REJECTED", "Accepted staging evidence is missing.", "publish_blueprint_build")
        staging = self.path_policy.resolve(record.staging_path, must_exist=True)
        if staging.resolve() == Path(record.plan.source_path).resolve():
            raise _error("BLUEPRINT_PUBLICATION_REJECTED", "The source package cannot be a publication target.", "publish_blueprint_build")
        publication = self.workspace_root / ".pscad-mcp" / "blueprint-publications" / f"{record.plan.target_name}-{record.build_id}"
        if publication.exists() or publication.is_symlink():
            raise _error("BLUEPRINT_PUBLICATION_REJECTED", "Publication target already exists.", "publish_blueprint_build")
        scope = record.plan.blueprint.publication.scope
        if scope == "physical_and_model" and not record.result.get("physical_acceptance"):
            raise _error("BLUEPRINT_PUBLICATION_REJECTED", "Physical publication requires trusted physical acceptance.", "publish_blueprint_build")
        evidence_root = staging / "evidence"
        manifest_path = evidence_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update({"state": "published", "published": True, "publication_scope": scope})
        write_json_atomic(manifest_path, manifest)
        included = sorted(record.plan.blueprint.publication.evidence_files)
        publication_evidence = publication / "evidence"
        publication_evidence.mkdir(parents=True)
        for name in included:
            source = evidence_root / name
            if not source.is_file() or source.is_symlink() or source.resolve().parent != evidence_root.resolve():
                shutil.rmtree(publication)
                raise _error("BLUEPRINT_PUBLICATION_REJECTED", "A declared evidence file is missing or unsafe.", "publish_blueprint_build", evidence=name)
            shutil.copy2(source, publication_evidence / name)
        publication_manifest = {
            "build_id": record.build_id,
            "plan_hash": record.plan.plan_hash,
            "publication_scope": scope,
            "included": included,
            "source_package_included": False,
            "staging_project_included": False,
        }
        write_json_atomic(publication / "publication-manifest.json", publication_manifest)
        journal = BuildJournal(self.workspace_root, record.build_id)
        next_state(record.state, BlueprintBuildState.PUBLISHED)
        journal.append("state", {"state": "published", "publication_scope": scope})
        result = {**dict(record.result), "published": True, "publication_scope": scope, "publication_path": str(publication)}
        evidence = {**dict(record.evidence or {}), "publication_manifest": str(publication / "publication-manifest.json")}
        return replace(
            record,
            state=BlueprintBuildState.PUBLISHED,
            history=freeze((*record.history, {"state": "published"})),
            result=freeze(result),
            evidence=freeze(evidence),
        )

    def _status(self, record: BlueprintBuildRecord) -> dict[str, Any]:
        payload = record.to_dict()
        result = dict(record.result or {})
        payload.update(
            {
                "published": bool(result.get("published", record.state is BlueprintBuildState.PUBLISHED)),
                "publication_scope": result.get("publication_scope"),
                "publication_path": result.get("publication_path"),
                "pending_operation": None if record.state in {BlueprintBuildState.PUBLISHED, BlueprintBuildState.QUARANTINED, BlueprintBuildState.FAILED, BlueprintBuildState.REJECTED} else "build_pscad_project",
            }
        )
        return payload

    def get_build_status(self, build_id: str) -> dict[str, Any]:
        record = self._records.get(build_id)
        if record is None:
            raise _error("BLUEPRINT_BUILD_NOT_FOUND", "Blueprint build ID was not found.", "get_pscad_project_build_status", build_id=build_id)
        if record.state is BlueprintBuildState.PLANNED:
            journal_path = BuildJournal(self.workspace_root, build_id).path
            if journal_path.is_file():
                try:
                    events = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines() if line]
                except (OSError, json.JSONDecodeError):
                    events = []
                states = [event.get("state") for event in events if event.get("event") == "state"]
                payload = self._status(record)
                if states and states[-1] in {state.value for state in BlueprintBuildState}:
                    payload["state"] = states[-1]
                payload["completed_history"] = events
                return payload
        return self._status(record)

    async def wait_for_build(self, build_id: str) -> dict[str, Any]:
        task = self._tasks.get(build_id)
        if task is None:
            return self.get_build_status(build_id)
        await task
        return self.get_build_status(build_id)

    async def validate_project_build(
        self,
        *,
        build_id: str | None = None,
        staging_path: str | None = None,
    ) -> dict[str, Any]:
        if (build_id is None) == (staging_path is None):
            raise _error(
                "BLUEPRINT_VALIDATION_TARGET_INVALID",
                "Provide exactly one of build_id or staging_path.",
                "validate_pscad_project_build",
            )
        if build_id is not None:
            record = self._records.get(build_id)
            if record is None or record.staging_path is None:
                raise _error("BLUEPRINT_VALIDATION_TARGET_INVALID", "Build validation target was not found.", "validate_pscad_project_build", build_id=build_id)
            plan = record.plan
            candidate = record.staging_path
        else:
            try:
                resolved = self.path_policy.resolve(str(staging_path), must_exist=True)
            except (OSError, ValueError) as error:
                raise _error("BLUEPRINT_VALIDATION_TARGET_INVALID", "Staging validation path is outside the workspace or missing.", "validate_pscad_project_build") from error
            candidate = str(resolved)
            plan_path = resolved / "evidence" / "plan.json"
            try:
                plan = plan_from_dict(json.loads(plan_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, BackendError) as error:
                raise _error("BLUEPRINT_VALIDATION_TARGET_INVALID", "Staging plan evidence is missing or invalid.", "validate_pscad_project_build") from error
        messages: list[Mapping[str, Any]] = []
        try:
            value = await self.pscad_service.get_project_output(plan.target_name, structured=True)
            if isinstance(value, list):
                messages = [item for item in value if isinstance(item, Mapping)]
        except BaseException:
            messages = []
        report = validate_staging(
            plan,
            candidate,
            messages=messages,
            trusted_source_classes=self.trusted_source_classes,
        )
        write_validation_report(candidate, report)
        return report

