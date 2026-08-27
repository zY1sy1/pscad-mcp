"""Public parent lifecycle for parameterized dual-engine MMC models."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import json
import os
import threading
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ....core.backend.base import BackendError
from ....core.path_policy import PathPolicy
from ....core.service import ConfirmationRequired
from ...scanner import scan_project
from .adjustment import choose_next_candidate
from .assets import load_packaged_asset_set
from .derivation import derive_mmc_parameters
from .engines.avm import AvmBlueprintEngine
from .engines.pwm import PwmTemplateEngine
from .inspection import inspect_mmc_evidence
from .journal import AtomicJournal, WorkspaceBuildLease
from .parametric_models import MmcParametricRequest, MmcParentPlan, parse_parametric_request
from .parametric_planner import create_parametric_plan
from .scenarios import recommend_scenarios
from .template_audit import audit_mmc_template


_CACHE_MAX = 64
_TERMINAL = {"published", "failed", "interrupted"}


def _error(code: str, message: str, operation: str, **details: object) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _run_coroutine_sync(factory: Callable[[], Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    result: list[Any] = []
    failure: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(factory()))
        except BaseException as error:
            failure.append(error)

    thread = threading.Thread(target=runner, name="mmc-parametric-reader", daemon=True)
    thread.start()
    thread.join()
    if failure:
        raise failure[0]
    return result[0]


class ParametricMmcBuilderService:
    def __init__(
        self,
        pscad_service: Any = None,
        *,
        workspace_root: str | Path | None = None,
        pwm_engine: Any = None,
        avm_engine: Any = None,
        audit_loader: Callable[..., Any] = audit_mmc_template,
        asset_loader: Callable[[], Any] = load_packaged_asset_set,
    ) -> None:
        self.pscad_service = pscad_service
        candidate = workspace_root
        if candidate is None:
            policy = getattr(pscad_service, "path_policy", None)
            candidate = getattr(policy, "workspace_root", None)
        self.workspace_root = (
            Path(candidate).expanduser().resolve() if candidate is not None else None
        )
        self.path_policy = (
            PathPolicy(workspace_root=str(self.workspace_root))
            if self.workspace_root is not None
            else PathPolicy()
        )
        self.audit_loader = audit_loader
        self.asset_loader = asset_loader
        self.pwm_engine = PwmTemplateEngine() if pwm_engine is None else pwm_engine
        self.avm_engine = AvmBlueprintEngine() if avm_engine is None else avm_engine
        self._plans: dict[str, MmcParentPlan] = {}
        self._statuses: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._leases: dict[str, WorkspaceBuildLease] = {}

    def _workspace(self, folder: str | Path, operation: str) -> Path:
        if self.workspace_root is None:
            raise _error(
                "MMC_LAYOUT_INVALID",
                "A configured workspace is required for parametric MMC planning.",
                operation,
            )
        if not isinstance(folder, (str, Path)) or not Path(folder).expanduser().is_absolute():
            raise _error(
                "MMC_LAYOUT_INVALID",
                "folder must be an absolute path inside the configured workspace.",
                operation,
            )
        resolved = Path(folder).expanduser().resolve()
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as error:
            raise _error(
                "MMC_LAYOUT_INVALID",
                "folder is outside the configured workspace.",
                operation,
                folder=str(resolved),
            ) from error
        if resolved.exists() and not resolved.is_dir():
            raise _error(
                "MMC_LAYOUT_INVALID",
                "folder is not a directory.",
                operation,
                folder=str(resolved),
            )
        return resolved

    @staticmethod
    def _needs_pwm(request: MmcParametricRequest) -> bool:
        return request.model_fidelity in {"detailed_pwm", "both"}

    def _audit(
        self,
        request: MmcParametricRequest,
        template_path: str | Path | None,
        library_path: str | Path | None,
    ) -> Any | None:
        if not self._needs_pwm(request):
            return None
        return self.audit_loader(template_path, library_path)

    def audit_template(
        self,
        template_path: str | Path | None = None,
        library_path: str | Path | None = None,
    ) -> dict[str, Any]:
        report = self.audit_loader(template_path, library_path)
        if hasattr(report, "to_dict") and callable(report.to_dict):
            report = report.to_dict()
        if not isinstance(report, Mapping):
            raise _error(
                "MMC_TEMPLATE_INVALID",
                "The template audit returned an invalid record.",
                "audit_mmc_template",
            )
        return copy.deepcopy(dict(report))

    def derive_parameters(
        self, request: MmcParametricRequest | Mapping[str, Any]
    ) -> dict[str, Any]:
        return derive_mmc_parameters(parse_parametric_request(request)).to_dict()

    def _compose_plan(
        self,
        request: MmcParametricRequest | Mapping[str, Any],
        project_name: str,
        folder: str | Path,
        *,
        template_path: str | Path | None,
        library_path: str | Path | None,
        operation: str,
    ) -> MmcParentPlan:
        parsed = parse_parametric_request(request)
        workspace = self._workspace(folder, operation)
        audit = self._audit(parsed, template_path, library_path)
        assets = self.asset_loader()
        return create_parametric_plan(
            parsed, project_name, workspace, audit, assets
        )

    def plan_model(
        self,
        request: MmcParametricRequest | Mapping[str, Any],
        project_name: str,
        folder: str | Path,
        *,
        template_path: str | Path | None = None,
        library_path: str | Path | None = None,
    ) -> dict[str, Any]:
        plan = self._compose_plan(
            request,
            project_name,
            folder,
            template_path=template_path,
            library_path=library_path,
            operation="plan_parametric_mmc_model",
        )
        self._plans[plan.plan_hash] = plan
        while len(self._plans) > _CACHE_MAX:
            self._plans.pop(next(iter(self._plans)))
        return {**plan.to_dict(), "status": "planned"}

    async def build_model(
        self,
        request: MmcParametricRequest | Mapping[str, Any],
        expected_plan_hash: str,
        project_name: str,
        folder: str | Path,
        *,
        template_path: str | Path | None = None,
        library_path: str | Path | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise ConfirmationRequired("build_parametric_mmc_model")
        plan = self._compose_plan(
            request,
            project_name,
            folder,
            template_path=template_path,
            library_path=library_path,
            operation="build_parametric_mmc_model",
        )
        if not isinstance(expected_plan_hash, str) or not hmac.compare_digest(
            expected_plan_hash, plan.plan_hash
        ):
            raise _error(
                "MMC_PLAN_STALE",
                "The supplied MMC parent plan hash is stale.",
                "build_parametric_mmc_model",
                expected_plan_hash=(
                    expected_plan_hash if isinstance(expected_plan_hash, str) else ""
                ),
                observed_plan_hash=plan.plan_hash,
            )
        cached = self._plans.get(expected_plan_hash)
        if cached is not None and cached.to_dict() != plan.to_dict():
            raise _error(
                "MMC_PLAN_STALE",
                "The recomposed MMC plan differs from the cached immutable plan.",
                "build_parametric_mmc_model",
            )
        if self.workspace_root is None:
            raise _error(
                "MMC_BUILD_UNAVAILABLE",
                "A configured workspace is required for MMC builds.",
                "build_parametric_mmc_model",
            )
        for child in plan.engine_plans:
            target = Path(child.target_path)
            if target.exists() or target.is_symlink():
                raise _error(
                    "MMC_BUILD_CONFLICT",
                    "A planned MMC final target already exists.",
                    "build_parametric_mmc_model",
                    target_path=str(target),
                )
        for method in ("load_projects", "build_project"):
            if not callable(getattr(self.pscad_service, method, None)):
                raise _error(
                    "MMC_BUILD_UNAVAILABLE",
                    "The PSCAD service lacks final reopen/compile capabilities.",
                    "build_parametric_mmc_model",
                    missing=method,
                )
        build_id = uuid.uuid4().hex
        lease = WorkspaceBuildLease.acquire(self.workspace_root, build_id)
        journal = AtomicJournal(self.workspace_root, build_id)
        initial = {
            "build_id": build_id,
            "state": "validated",
            "plan_hash": plan.plan_hash,
            "workspace": str(self.workspace_root),
            "engines": [
                {
                    "engine": child.engine,
                    "state": "planned",
                    "capability_level": "planned",
                    "attempts": [],
                    "final_path": child.target_path,
                }
                for child in plan.engine_plans
            ],
            "history": [{"state": "validated"}],
            "error": None,
            "result": None,
        }
        try:
            self._statuses[build_id] = initial
            self._leases[build_id] = lease
            journal.write(initial)
            task = asyncio.create_task(
                self._run_parent(build_id, plan, journal, lease),
                name=f"mmc-parametric-{build_id}",
            )
            self._tasks[build_id] = task
            task.add_done_callback(
                lambda completed: self._task_done(build_id, completed)
            )
            await asyncio.sleep(0)
        except BaseException:
            self._tasks.pop(build_id, None)
            self._leases.pop(build_id, None)
            self._statuses.pop(build_id, None)
            lease.release(lease.token)
            raise
        return {
            "build_id": build_id,
            "state": "validated",
            "plan_hash": plan.plan_hash,
            "engines": [item.engine for item in plan.engine_plans],
        }

    def _engine_for(self, name: str) -> Any:
        return self.pwm_engine if name == "detailed_pwm" else self.avm_engine

    async def _execute_child(
        self, plan: MmcParentPlan, child: Any
    ) -> dict[str, Any]:
        engine = self._engine_for(child.engine)
        attempted: list[str] = []
        attempts: list[dict[str, Any]] = []
        signatures: list[str] = []
        candidate_id = child.candidates[0].candidate_id
        while True:
            attempted.append(candidate_id)
            try:
                result = await engine.execute_candidate(
                    child, self.pscad_service, candidate_id=candidate_id
                )
                if not isinstance(result, Mapping) or result.get("state") != "accepted":
                    raise _error(
                        "MMC_ACCEPTANCE_FAILED",
                        "An MMC engine returned a non-accepted candidate record.",
                        "build_parametric_mmc_model",
                        engine=child.engine,
                        candidate_id=candidate_id,
                    )
                result_dict = copy.deepcopy(dict(result))
                attempts.append(
                    {
                        "candidate_id": candidate_id,
                        "state": "accepted",
                        "parameter_hash": next(
                            item.parameter_hash
                            for item in child.candidates
                            if item.candidate_id == candidate_id
                        ),
                    }
                )
                return {
                    "engine": child.engine,
                    "state": "accepted",
                    "capability_level": "accepted",
                    "attempts": attempts,
                    "candidate_result": result_dict,
                    "final_path": child.target_path,
                    "error": None,
                }
            except asyncio.CancelledError:
                raise
            except BaseException as failure:
                backend_error = (
                    failure
                    if isinstance(failure, BackendError)
                    else _error(
                        "MMC_BUILD_FAILED",
                        "An MMC engine candidate failed unexpectedly.",
                        "build_parametric_mmc_model",
                        engine=child.engine,
                        candidate_id=candidate_id,
                        exception=type(failure).__name__,
                    )
                )
                decision_error = BackendError(
                    backend_error.code,
                    str(backend_error),
                    backend_error.backend,
                    backend_error.operation,
                    {
                        **backend_error.details,
                        "candidate_id": candidate_id,
                        "previous_failure_signatures": list(signatures),
                    },
                )
                try:
                    decision = choose_next_candidate(
                        plan,
                        child.engine,
                        attempted=tuple(attempted),
                        failure=decision_error,
                    )
                except BackendError as stop:
                    attempts.append(
                        {
                            "candidate_id": candidate_id,
                            "state": "failed",
                            "error": backend_error.to_dict(),
                            "stop": stop.to_dict(),
                        }
                    )
                    return {
                        "engine": child.engine,
                        "state": "failed",
                        "capability_level": "planned",
                        "attempts": attempts,
                        "candidate_result": None,
                        "final_path": child.target_path,
                        "error": backend_error.to_dict(),
                    }
                attempts.append(
                    {
                        "candidate_id": candidate_id,
                        "state": "failed",
                        "error": backend_error.to_dict(),
                        "adjustment": decision.adjustment.to_dict(),
                        "next_candidate_id": decision.candidate_id,
                        "failure_signature": decision.failure_signature,
                    }
                )
                signatures.append(decision.failure_signature)
                candidate_id = decision.candidate_id

    def _candidate_project(self, engine_record: Mapping[str, Any]) -> Path:
        result = engine_record.get("candidate_result")
        value = result.get("project_path") if isinstance(result, Mapping) else None
        if not isinstance(value, str):
            raise _error(
                "MMC_POSTCONDITION_FAILED",
                "An accepted MMC candidate has no project path.",
                "build_parametric_mmc_model",
                engine=engine_record.get("engine"),
            )
        source = Path(value).expanduser().resolve()
        if self.workspace_root is None:
            raise _error(
                "MMC_LAYOUT_INVALID", "MMC workspace is unavailable.", "build_parametric_mmc_model"
            )
        try:
            source.relative_to(self.workspace_root)
        except ValueError as error:
            raise _error(
                "MMC_POSTCONDITION_FAILED",
                "An accepted candidate project is outside the workspace.",
                "build_parametric_mmc_model",
                path=str(source),
            ) from error
        if source.is_symlink() or not source.is_file():
            raise _error(
                "MMC_POSTCONDITION_FAILED",
                "An accepted candidate project is not a regular file.",
                "build_parametric_mmc_model",
                path=str(source),
            )
        return source

    async def _publish(self, engines: list[dict[str, Any]]) -> list[str]:
        moved: list[tuple[Path, Path]] = []
        try:
            for record in engines:
                source = self._candidate_project(record)
                target = Path(str(record["final_path"])).resolve()
                if self.workspace_root is None:
                    raise _error(
                        "MMC_LAYOUT_INVALID", "MMC workspace is unavailable.", "build_parametric_mmc_model"
                    )
                try:
                    target.relative_to(self.workspace_root)
                except ValueError as error:
                    raise _error(
                        "MMC_LAYOUT_INVALID",
                        "A final MMC target is outside the workspace.",
                        "build_parametric_mmc_model",
                        path=str(target),
                    ) from error
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(source, target)
                except FileExistsError as error:
                    raise _error(
                        "MMC_BUILD_CONFLICT",
                        "A final MMC target appeared during publication.",
                        "build_parametric_mmc_model",
                        target_path=str(target),
                    ) from error
                source.unlink()
                moved.append((source, target))
                await self.pscad_service.load_projects([str(target)])
                await self.pscad_service.build_project(target.stem)
            return [str(target) for _, target in moved]
        except BaseException:
            rollback_failures: list[str] = []
            for source, target in reversed(moved):
                try:
                    if target.is_file() and not source.exists():
                        source.parent.mkdir(parents=True, exist_ok=True)
                        os.link(target, source)
                        target.unlink()
                except OSError:
                    rollback_failures.append(str(target))
            if rollback_failures:
                raise _error(
                    "MMC_POSTCONDITION_FAILED",
                    "MMC parent publication rollback was incomplete.",
                    "build_parametric_mmc_model",
                    rollback_failures=rollback_failures,
                )
            raise

    async def _run_parent(
        self,
        build_id: str,
        plan: MmcParentPlan,
        journal: AtomicJournal,
        lease: WorkspaceBuildLease,
    ) -> dict[str, Any]:
        record = self._statuses[build_id]
        try:
            engines: list[dict[str, Any]] = []
            for child in plan.engine_plans:
                child_record = await self._execute_child(plan, child)
                engines.append(child_record)
                record["engines"] = copy.deepcopy(engines)
                record["history"].append(
                    {"state": child_record["state"], "engine": child.engine}
                )
                journal.write(record)
            record["engines"] = engines
            failed = [item for item in engines if item["state"] != "accepted"]
            if failed:
                record["state"] = "failed"
                record["error"] = failed[0]["error"]
                record["history"].append({"state": "failed", "reason": "child_failed"})
            else:
                final_paths = await self._publish(engines)
                for engine_record, final_path in zip(engines, final_paths):
                    engine_record["final_path"] = final_path
                record["state"] = "published"
                record["result"] = {
                    "final_paths": final_paths,
                    "capability_level": "accepted",
                }
                record["history"].append({"state": "published"})
        except asyncio.CancelledError:
            record["state"] = "interrupted"
            record["error"] = _error(
                "MMC_BUILD_INTERRUPTED",
                "The MMC parent build was interrupted.",
                "build_parametric_mmc_model",
            ).to_dict()
            record["history"].append({"state": "interrupted"})
        except BaseException as failure:
            backend_error = (
                failure
                if isinstance(failure, BackendError)
                else _error(
                    "MMC_BUILD_FAILED",
                    "The MMC parent lifecycle failed.",
                    "build_parametric_mmc_model",
                    exception=type(failure).__name__,
                )
            )
            record["state"] = "failed"
            record["error"] = backend_error.to_dict()
            record["history"].append({"state": "failed", "reason": "parent_failed"})
        finally:
            self._statuses[build_id] = record
            try:
                journal.write(record)
            finally:
                lease.release(lease.token)
                self._leases.pop(build_id, None)
        return record

    def _task_done(self, build_id: str, task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except BaseException:
            pass
        self._tasks.pop(build_id, None)

    def get_status(self, build_id: str) -> dict[str, Any]:
        if build_id not in self._statuses:
            if self.workspace_root is None:
                raise _error(
                    "NOT_FOUND",
                    "Parametric MMC build was not found.",
                    "get_parametric_mmc_build_status",
                    build_id=build_id,
                )
            path = AtomicJournal(self.workspace_root, build_id).path
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise _error(
                    "NOT_FOUND",
                    "Parametric MMC build was not found.",
                    "get_parametric_mmc_build_status",
                    build_id=build_id,
                ) from error
            if not isinstance(loaded, dict):
                raise _error(
                    "MMC_JOURNAL_INVALID",
                    "The MMC parent journal is not an object.",
                    "get_parametric_mmc_build_status",
                    build_id=build_id,
                )
            self._statuses[build_id] = loaded
        return copy.deepcopy(self._statuses[build_id])

    def recommend_simulation(
        self,
        request_or_project: MmcParametricRequest | Mapping[str, Any] | str,
        objectives: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        if isinstance(request_or_project, str):
            raise _error(
                "MMC_REQUEST_INVALID",
                "Project-only recommendation requires a stored design request.",
                "recommend_mmc_simulation",
                project_name=request_or_project,
            )
        request = parse_parametric_request(request_or_project)
        fidelities = (
            ("detailed_pwm", "average_value")
            if request.model_fidelity == "both"
            else (request.model_fidelity,)
        )
        selected_names = set(objectives or ())
        recommendations = []
        for fidelity in fidelities:
            design = derive_mmc_parameters(replace(request, model_fidelity=fidelity))
            for item in recommend_scenarios(design):
                if not selected_names or item.name in selected_names:
                    recommendations.append(item.to_dict())
        return {
            "request": request.to_dict(),
            "recommendations": recommendations,
            "capabilities": {"intrinsic_dc_fault_blocking": False},
        }

    def _project_path(self, value: str | Path) -> Path:
        if self.workspace_root is None:
            raise _error(
                "MMC_LAYOUT_INVALID",
                "A configured workspace is required for MMC validation.",
                "validate_mmc_model",
            )
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        if candidate.suffix.casefold() != ".pscx":
            candidate = candidate.with_suffix(".pscx")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as error:
            raise _error(
                "MMC_LAYOUT_INVALID",
                "The MMC project is outside the configured workspace.",
                "validate_mmc_model",
                project_name=str(value),
            ) from error
        if resolved.is_symlink() or not resolved.is_file():
            raise _error(
                "NOT_FOUND",
                "The MMC project file was not found.",
                "validate_mmc_model",
                project_name=str(value),
            )
        return resolved

    def validate_model(
        self,
        project_name: str,
        model_fidelity: str,
        output_files: Sequence[str] | None = None,
        acceptance_scope: str = "full",
    ) -> dict[str, Any]:
        if model_fidelity not in {"detailed_pwm", "average_value"}:
            raise _error(
                "MMC_MODEL_UNSUPPORTED",
                "model_fidelity must be detailed_pwm or average_value.",
                "validate_mmc_model",
            )
        if acceptance_scope not in {"structure", "normal", "fault", "full"}:
            raise _error(
                "MMC_REQUEST_INVALID",
                "acceptance_scope is unsupported.",
                "validate_mmc_model",
            )
        project = self._project_path(project_name)
        evidence = scan_project(project)
        structure = inspect_mmc_evidence(evidence)
        result: dict[str, Any] = {
            "project_file": str(project),
            "project_sha256": hashlib.sha256(project.read_bytes()).hexdigest(),
            "model_fidelity": model_fidelity,
            "structure": structure,
            "capability_level": "built",
            "accepted": False,
            "acceptance": {
                "status": "not_evaluated",
                "reason": "No output files were supplied for independent dynamic validation.",
            },
        }
        if not output_files:
            return result
        reader = getattr(self.pscad_service, "read_output_file", None)
        if not callable(reader):
            raise _error(
                "MMC_OUTPUT_INCOMPLETE",
                "The PSCAD service does not expose an output reader.",
                "validate_mmc_model",
            )
        outputs = []
        for raw in output_files:
            path = Path(raw).expanduser().resolve()
            if self.workspace_root is None or self.workspace_root not in path.parents:
                raise _error(
                    "MMC_LAYOUT_INVALID",
                    "An MMC output file is outside the workspace.",
                    "validate_mmc_model",
                    output_file=str(path),
                )
            if not path.is_file():
                raise _error(
                    "MMC_OUTPUT_INCOMPLETE",
                    "An MMC output file is missing.",
                    "validate_mmc_model",
                    output_file=str(path),
                )
            payload = _run_coroutine_sync(
                lambda path=path: reader(
                    str(path), max_samples=1_000_000, summary_only=False
                )
            )
            outputs.append(payload)
        passed = bool(outputs) and all(
            isinstance(item, Mapping)
            and str(item.get("verdict", "")).upper() == "PASS"
            for item in outputs
        )
        result["capability_level"] = "accepted" if passed else "simulated"
        result["accepted"] = passed
        result["acceptance"] = {
            "status": "evaluated",
            "scope": acceptance_scope,
            "verdict": "PASS" if passed else "INCOMPLETE_ANALYSIS",
            "outputs": outputs,
            "intrinsic_dc_fault_blocking": False,
        }
        return result


__all__ = ["ParametricMmcBuilderService"]
