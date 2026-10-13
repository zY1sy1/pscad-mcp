"""Background campaigns above isolated PscadService sessions."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from ...core.path_policy import PathPolicy
from ...core.service import ConfirmationRequired, PscadService
from .analysis import compare, legacy_dataset_paths, rank, read_legacy, summarize
from .models import SweepSpec
from .store import (
    SweepStore,
    WorkspaceLease,
    atomic_json,
    contained,
    file_hash,
    process_alive,
    reject_link,
    sweep_error,
)

TERMINAL = frozenset({"complete", "completed", "stopped", "failed", "idle"})


class _Cancelled(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return str(actual).casefold() == str(expected).casefold() or actual == expected
    if isinstance(expected, (float, int)):
        try:
            return not isinstance(actual, bool) and float(actual) == expected
        except (ValueError, TypeError):
            return False
    return actual == expected


class SweepService:
    def __init__(
        self,
        path_policy: PathPolicy,
        *,
        session_factory: Callable[..., Any],
        process_alive: Callable[..., bool] = process_alive,
    ):
        self.path_policy = path_policy
        self.store = SweepStore(path_policy)
        self.session_factory = session_factory
        self.process_alive = process_alive
        self.tasks: dict[str, asyncio.Task] = {}
        self.events: dict[str, asyncio.Event] = {}
        self.cleanup_sessions: dict[str, Any] = {}
        self.closing = False

    def _parse(self, raw: Any) -> SweepSpec:
        try:
            spec = SweepSpec.parse(raw, self.path_policy)
            original = Path(raw["source_root"])
            if not original.is_absolute():
                original = self.store.workspace / original
            for path in (original, *original.parents):
                if path.exists() or path.is_symlink():
                    reject_link(path)
                if path == self.store.workspace:
                    break
            return spec
        except (ValueError, OSError) as error:
            raise sweep_error("SWEEP_INVALID_SPEC", str(error)) from error

    def plan(self, spec: Any) -> dict[str, Any]:
        return self.store.plan(self._parse(spec))

    def create(
        self, spec: Any, *, expected_plan_hash: str, confirm: bool = False
    ) -> dict[str, Any]:
        if confirm is not True:
            raise ConfirmationRequired("create_parameter_sweep")
        parsed = self._parse(spec)
        plan = self.store.plan(parsed)
        if plan["plan_hash"] != expected_plan_hash:
            raise sweep_error(
                "SWEEP_PLAN_STALE",
                "The specification or source no longer matches the reviewed plan.",
            )
        cid = self.store.create(parsed, plan)
        return self.status(cid)

    @staticmethod
    def _spec(manifest: dict[str, Any], policy: PathPolicy) -> SweepSpec:
        raw = deepcopy(manifest["spec"])
        for scenario in raw["scenarios"]:
            scenario.pop("directory_key", None)
        return SweepSpec.parse(raw, policy)

    def _report(
        self, cid: str, manifest: dict[str, Any], checkpoint: dict[str, Any]
    ) -> dict[str, Any]:
        scenarios = []
        for scenario in checkpoint["scenarios"]:
            result = {}
            for reference in scenario["results"]:
                result = self.store.result(cid, reference)
            scenarios.append(
                {
                    **result,
                    "name": scenario["name"],
                    "state": scenario["state"],
                    "attempt_count": scenario["attempt_count"],
                }
            )
        return compare(
            {
                "campaign_id": cid,
                "state": checkpoint["state"],
                "plan_hash": manifest["plan_hash"],
                "source_hash": manifest["source_hash"],
                "statistics_scope": "bounded_sample",
                "scenarios": scenarios,
            },
            manifest["spec"]["baseline_scenario"],
        )

    def status(
        self,
        campaign_id: str,
        *,
        include_report: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise sweep_error(
                "SWEEP_INVALID_SPEC",
                "Pagination needs offset >= 0 and 1 <= limit <= 100.",
            )
        manifest, checkpoint = self.store.load(campaign_id)
        scenarios = [
            {
                key: scenario[key]
                for key in ("name", "directory_key", "state", "attempt_count")
            }
            for scenario in checkpoint["scenarios"]
        ]
        result = {
            "campaign_id": campaign_id,
            "state": checkpoint["state"],
            "revision": checkpoint["revision"],
            "total_scenarios": len(scenarios),
            "counts": {
                state: Counter(item["state"] for item in scenarios)[state]
                for state in (
                    "pending",
                    "preparing",
                    "building",
                    "running",
                    "collecting",
                    "restoring",
                    "succeeded",
                    "failed",
                    "cancelled",
                    "needs_review",
                )
            },
            "scenarios": scenarios[offset : offset + limit],
            "offset": offset,
            "limit": limit,
            "active_attempt": checkpoint.get("active_attempt"),
            "worker_active": campaign_id in self.tasks
            and not self.tasks[campaign_id].done(),
            "cancel_requested": self._cancel_path(campaign_id).exists(),
            "error": checkpoint.get("error"),
            "campaign_directory": str(self.store.campaign_path(campaign_id)),
        }
        if include_report:
            report = self._report(campaign_id, manifest, checkpoint)
            report["scenarios"] = report["scenarios"][offset : offset + limit]
            result["report"] = report
        return result

    def analyze(
        self,
        campaign_id: str,
        *,
        objective: dict[str, Any] | None = None,
        constraints: list[dict[str, Any]] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        manifest, checkpoint = self.store.load(campaign_id)
        report = self._report(campaign_id, manifest, checkpoint)
        result = rank(report, objective, constraints, limit)
        result["report"]["scenarios"] = result["report"]["scenarios"][:limit]
        return result

    def _cancel_path(self, cid: str) -> Path:
        return contained(self.store.campaign_path(cid), "cancel.json")

    async def cancel(
        self, campaign_id: str, *, confirm: bool = False
    ) -> dict[str, Any]:
        if confirm is not True:
            raise ConfirmationRequired("cancel_parameter_sweep")
        _manifest, checkpoint = self.store.load(campaign_id)
        if checkpoint["state"] in {"ready", "running"}:
            atomic_json(self._cancel_path(campaign_id), {"requested_at": _now()})
            if campaign_id in self.events:
                self.events[campaign_id].set()
        return self.status(campaign_id)

    async def start(self, campaign_id: str, *, confirm: bool = False) -> dict[str, Any]:
        return await self._start(
            campaign_id, confirm=confirm, resume=False, retry_scenarios=None
        )

    async def resume(
        self,
        campaign_id: str,
        *,
        retry_scenarios: list[str] | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        return await self._start(
            campaign_id, confirm=confirm, resume=True, retry_scenarios=retry_scenarios
        )

    def _recover(self, cid: str, checkpoint: dict[str, Any]) -> None:
        attempt = checkpoint.get("active_attempt")
        if not attempt:
            return
        if attempt.get("ownership_unknown") or self.process_alive(
            attempt.get("owned_session")
        ):
            checkpoint["state"] = "blocked"
            checkpoint["scenarios"][attempt["index"]]["state"] = "needs_review"
            checkpoint["error"] = {
                "code": "SWEEP_NEEDS_REVIEW",
                "message": "The previous owned session has not been verified absent.",
            }
            self.store.save(cid, checkpoint)
            raise sweep_error(
                "SWEEP_NEEDS_REVIEW",
                "Legacy running sessions cannot be reattached after restart.",
            )
        scenario = checkpoint["scenarios"][attempt["index"]]
        root = self.store.campaign_path(cid)
        result_path = contained(root, attempt["path"] + "/result.json")
        if result_path.exists():
            reference = {
                "path": str(result_path.relative_to(root)),
                "sha256": file_hash(result_path),
            }
            result = self.store.result(cid, reference)
        else:
            result = {
                "name": scenario["name"],
                "state": "failed",
                "outputs": [],
                "artifacts": [],
                "error": {
                    "code": "SWEEP_INTERRUPTED",
                    "message": "An unfinished attempt was interrupted; its owned process is absent.",
                },
                "cleanup": {"session_absent": True},
                "finished_at": _now(),
            }
            atomic_json(result_path, result)
            reference = {
                "path": str(result_path.relative_to(root)),
                "sha256": file_hash(result_path),
            }
        if reference not in scenario["results"]:
            scenario["results"].append(reference)
        scenario["state"] = result["state"]
        checkpoint["active_attempt"] = None

    async def _start(
        self,
        cid: str,
        *,
        confirm: bool,
        resume: bool,
        retry_scenarios: list[str] | None,
    ) -> dict[str, Any]:
        operation = "resume_parameter_sweep" if resume else "run_parameter_sweep"
        if confirm is not True:
            raise ConfirmationRequired(operation)
        if self.closing:
            raise sweep_error("SWEEP_CLOSING", "The sweep runtime is shutting down.")
        if cid in self.tasks and not self.tasks[cid].done():
            if retry_scenarios:
                raise sweep_error("SWEEP_BUSY", "Cannot retry an active campaign.")
            return self.status(cid)
        manifest, checkpoint = self.store.load(cid)
        self.store.verify_inputs(manifest)
        self._report(
            cid, manifest, checkpoint
        )  # Verify retained evidence before skipping completed work.
        names = {item["name"]: item for item in checkpoint["scenarios"]}
        if retry_scenarios is not None and (
            not isinstance(retry_scenarios, list)
            or not retry_scenarios
            or not all(
                isinstance(name, str) and name in names for name in retry_scenarios
            )
            or len(set(retry_scenarios)) != len(retry_scenarios)
        ):
            raise sweep_error(
                "SWEEP_INVALID_SPEC",
                "retry_scenarios must be a non-empty list of unique campaign names.",
            )
        if not resume and checkpoint["state"] != "ready":
            if checkpoint["state"] in {"completed", "completed_with_failures"}:
                return self.status(cid)
            raise sweep_error(
                "SWEEP_RESUME_REQUIRED",
                "Use resume_parameter_sweep for an interrupted or cancelled campaign.",
            )
        lease = WorkspaceLease(self.store.root, self.process_alive)
        try:
            lease.acquire(cid)
        except Exception as error:
            if getattr(error, "code", None) == "SWEEP_NEEDS_REVIEW" and checkpoint.get(
                "active_attempt"
            ):
                checkpoint["state"] = "blocked"
                checkpoint["scenarios"][checkpoint["active_attempt"]["index"]][
                    "state"
                ] = "needs_review"
                self.store.save(cid, checkpoint)
            raise
        try:
            self._recover(cid, checkpoint)
            if retry_scenarios:
                if any(
                    names[name]["state"] not in {"failed", "cancelled", "needs_review"}
                    for name in retry_scenarios
                ):
                    raise sweep_error(
                        "SWEEP_INVALID_SPEC",
                        "Only failed, cancelled or reviewed interrupted scenarios may be retried.",
                    )
                for name in retry_scenarios:
                    names[name]["state"] = "pending"
            if resume:
                for scenario in checkpoint["scenarios"]:
                    if scenario["state"] == "cancelled":
                        scenario["state"] = "pending"
                self._cancel_path(cid).unlink(missing_ok=True)
            if checkpoint["state"] == "blocked" and not retry_scenarios:
                raise sweep_error(
                    "SWEEP_NEEDS_REVIEW",
                    "Specify the scenarios to retry after the owned process is absent.",
                )
            checkpoint.pop("error", None)
            checkpoint["state"] = "running"
            checkpoint["worker"] = {
                "pid": os.getpid(),
                "create_time": psutil.Process().create_time(),
            }
            self.store.save(cid, checkpoint)
            event = asyncio.Event()
            self.events[cid] = event
            task = asyncio.create_task(
                self._worker(cid, manifest, checkpoint, lease, event),
                name=f"pscad-{cid}",
            )
            task.add_done_callback(
                lambda finished: (
                    finished.exception() if not finished.cancelled() else None
                )
            )
            self.tasks[cid] = task
        except BaseException:
            lease.release()
            raise
        return self.status(cid)

    async def wait(self, cid: str, timeout: float = 20) -> None:
        task = self.tasks.get(cid)
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), timeout)

    async def _worker(
        self,
        cid: str,
        manifest: dict[str, Any],
        checkpoint: dict[str, Any],
        lease: WorkspaceLease,
        event: asyncio.Event,
    ) -> None:
        preserve = False
        try:
            spec = self._spec(manifest, self.path_policy)
            for index, scenario in enumerate(checkpoint["scenarios"]):
                if event.is_set() or self._cancel_path(cid).exists():
                    checkpoint["state"] = "cancelled"
                    break
                if scenario["state"] != "pending":
                    continue
                self.store.verify_inputs(manifest)
                safe = await self._attempt(
                    cid, manifest, checkpoint, index, spec, lease, event
                )
                if not safe:
                    checkpoint["state"] = "blocked"
                    preserve = bool(
                        lease.owner.get("ownership_unknown")
                        or self.process_alive(lease.owner.get("owned_session"))
                    )
                    break
                self.store.verify_inputs(manifest)
            else:
                checkpoint["state"] = (
                    "completed_with_failures"
                    if any(
                        item["state"] != "succeeded" for item in checkpoint["scenarios"]
                    )
                    else "completed"
                )
            if checkpoint["state"] != "blocked" and (
                event.is_set() or self._cancel_path(cid).exists()
            ):
                checkpoint["state"] = "cancelled"
        except BaseException as error:  # noqa: BLE001 - persist interruption before releasing ownership
            checkpoint["state"] = "blocked"
            checkpoint["error"] = PscadService.error_payload(error, "parameter_sweep")[
                "error"
            ]
            preserve = bool(
                lease.owner.get("ownership_unknown")
                or self.process_alive(lease.owner.get("owned_session"))
            )
        finally:
            try:
                self.store.save(cid, checkpoint)
                report = self._report(cid, manifest, checkpoint)
                atomic_json(
                    contained(self.store.campaign_path(cid), "report.json"), report
                )
            except Exception as error:  # noqa: BLE001 - a broken report is never a completed campaign
                checkpoint["state"] = "blocked"
                checkpoint["error"] = PscadService.error_payload(error, "report_sweep")[
                    "error"
                ]
                self.store.save(cid, checkpoint)
            finally:
                lease.release(preserve_owner=preserve)

    def _checkpoint_phase(self, cid, checkpoint, index, phase):
        checkpoint["scenarios"][index]["state"] = phase
        checkpoint["active_attempt"]["phase"] = phase
        self.store.save(cid, checkpoint)

    def _check_cancel(self, cid, event):
        if event.is_set() or self._cancel_path(cid).exists():
            raise _Cancelled()

    @staticmethod
    async def _stop_owned_run(session, project_name):
        if (await session.get_run_status(project_name)).get(
            "status", ""
        ).casefold() in TERMINAL:
            return
        try:
            await session.stop_simulation(project_name)
        except Exception as error:
            if getattr(error, "code", None) != "RUN_NOT_ACTIVE":
                raise
        if (await session.get_run_status(project_name)).get(
            "status", ""
        ).casefold() not in TERMINAL:
            raise sweep_error("SWEEP_STOP_UNVERIFIED", "The owned run has not stopped.")

    @staticmethod
    def _remove_outputs(work: Path, spec: SweepSpec) -> None:
        for output in spec.outputs:
            path = contained(work, output.path)
            paths = [path]
            if path.suffix.casefold() == ".out":
                base = re.sub(r"_\d{2}$", "", path.stem)
                paths += list(path.parent.glob(f"{base}_*.out"))
            for artifact in paths:
                if artifact.exists():
                    reject_link(artifact)
                    if not artifact.is_file():
                        raise sweep_error(
                            "SWEEP_UNSAFE_PATH",
                            "A declared output is not a regular file.",
                        )
                    artifact.unlink()

    async def _attempt(
        self, cid, manifest, checkpoint, index, spec, lease, event
    ) -> bool:
        scenario_record = checkpoint["scenarios"][index]
        scenario = spec.scenarios[index]
        scenario_record["attempt_count"] += 1
        attempt_relative = f"attempts/{scenario.directory_key}/attempt-{scenario_record['attempt_count']}"
        root = self.store.campaign_path(cid)
        attempt = contained(root, attempt_relative)
        attempt.mkdir(parents=True, exist_ok=False)
        work = attempt / "work"
        checkpoint["active_attempt"] = {
            "index": index,
            "number": scenario_record["attempt_count"],
            "path": attempt_relative,
            "phase": "preparing",
            "owned_session": None,
            "ownership_unknown": False,
            "started_at": _now(),
            "dispatched": False,
        }
        self._checkpoint_phase(cid, checkpoint, index, "preparing")
        result = {
            "name": scenario.name,
            "state": "failed",
            "outputs": [],
            "artifacts": [],
            "messages": [],
            "attempt": scenario_record["attempt_count"],
            "started_at": _now(),
        }
        session = None
        snapshots = {}
        changed = set()
        running = False
        identity = None
        cleanup_ok = True
        shutdown_ok = False
        try:
            self.store.copy_snapshot(
                root / "baseline", work, manifest["source_inventory"]
            )
            self._remove_outputs(work, spec)
            self._check_cancel(cid, event)
            session = self.session_factory()
            checkpoint["active_attempt"]["ownership_unknown"] = True
            self.store.save(cid, checkpoint)
            lease.record_session(None, unknown=True)
            await session.attach_local()
            details = await session.status()
            pid = details.get("session", {}).get("managed_pid")
            if (
                not details.get("owns_process")
                or isinstance(pid, bool)
                or not isinstance(pid, int)
                or pid <= 0
            ):
                checkpoint["active_attempt"]["ownership_unknown"] = True
                lease.record_session(None, unknown=True)
                raise sweep_error(
                    "SWEEP_CAPABILITY_UNAVAILABLE",
                    "The backend must report a managed owned PID before sweep mutation.",
                )
            identity = {"pid": pid, "create_time": psutil.Process(pid).create_time()}
            checkpoint["active_attempt"]["owned_session"] = identity
            checkpoint["active_attempt"]["ownership_unknown"] = False
            result["owned_session"] = identity
            result["backend"] = details.get("backend")
            result["version"] = details.get("version")
            lease.record_session(identity)
            self.store.save(cid, checkpoint)
            libraries = [
                str(contained(work, relative))
                for relative in manifest["source_inventory"]
                if Path(relative).suffix.casefold() == ".pslx"
                and relative != spec.entry_file
            ]
            await session.load_projects(
                [*libraries, str(contained(work, spec.entry_file, must_exist=True))]
            )
            projects = await session.list_projects()
            if not any(
                item.get("name") == spec.project_name
                and item.get("type", "").casefold() == "case"
                for item in projects
            ):
                raise sweep_error(
                    "SWEEP_PROJECT_MISSING",
                    "The copied entry did not load the requested case.",
                )
            targets = {}
            for update in scenario.updates:
                targets.setdefault(update.component_id, {}).update(update.parameters)
            for component_id, parameters in targets.items():
                current = await session.get_component_parameters(
                    spec.project_name, component_id
                )
                if not all(name in current for name in parameters):
                    raise sweep_error(
                        "SWEEP_PARAMETER_INVALID",
                        "A requested parameter is not present.",
                    )
                snapshots[component_id] = {name: current[name] for name in parameters}
                validated = await session.validate_component_parameters(
                    spec.project_name, component_id, parameters
                )
                if set(validated) != set(parameters) or not all(
                    item.get("valid") is True for item in validated.values()
                ):
                    raise sweep_error(
                        "SWEEP_PARAMETER_INVALID",
                        "A proposed parameter has no verified legal range.",
                    )
            result["parameter_snapshot"] = snapshots
            checkpoint["active_attempt"]["parameter_snapshot"] = snapshots
            self.store.save(cid, checkpoint)
            for component_id, parameters in targets.items():
                self._check_cancel(cid, event)
                changed.add(component_id)
                await session.set_component_parameters(
                    spec.project_name, component_id, parameters
                )
                observed = await session.get_component_parameters(
                    spec.project_name, component_id
                )
                if not all(
                    _matches(observed.get(name), value)
                    for name, value in parameters.items()
                ):
                    raise sweep_error(
                        "SWEEP_READBACK_FAILED",
                        "A parameter write did not read back correctly.",
                    )
            await session.save_project(spec.project_name)
            self._check_cancel(cid, event)
            self._checkpoint_phase(cid, checkpoint, index, "building")
            await session.build_project(spec.project_name)
            result["messages"] = (
                await session.get_project_output(spec.project_name, structured=True)
            )[:100]
            if any(
                item.get("severity", "").casefold() in {"error", "fatal"}
                for item in result["messages"]
            ):
                raise sweep_error(
                    "SWEEP_BUILD_FAILED", "The compiler reported an error."
                )
            self._check_cancel(cid, event)
            self._remove_outputs(work, spec)
            boundaries = {}
            for output in spec.outputs:
                output_path = contained(work, output.path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=output_path.parent, delete=False
                ) as clock:
                    clock_path = Path(clock.name)
                try:
                    boundaries[output.path] = clock_path.stat().st_mtime_ns
                finally:
                    clock_path.unlink()
            checkpoint["active_attempt"]["dispatched"] = True
            checkpoint["active_attempt"]["filesystem_boundaries_ns"] = boundaries
            self._checkpoint_phase(cid, checkpoint, index, "running")
            running = True  # Dispatch can fail after starting the native run.
            await session.run_project(spec.project_name)
            deadline = time.monotonic() + spec.run_timeout_seconds
            while True:
                self._check_cancel(cid, event)
                state = (
                    (await session.get_run_status(spec.project_name))
                    .get("status", "")
                    .casefold()
                )
                if state in TERMINAL:
                    running = False
                    if state in {"stopped", "failed"}:
                        raise sweep_error(
                            "SWEEP_RUN_FAILED",
                            "The simulation did not complete normally.",
                        )
                    break
                if state not in {"running", "starting", "building", "paused"}:
                    raise sweep_error(
                        "SWEEP_RUN_UNVERIFIED",
                        "The run status cannot be interpreted safely.",
                    )
                if time.monotonic() >= deadline:
                    raise sweep_error(
                        "SWEEP_TIMEOUT", "The attempt exceeded its simulation deadline."
                    )
                try:
                    await asyncio.wait_for(event.wait(), spec.poll_interval_seconds)
                except asyncio.TimeoutError:
                    pass
            self._checkpoint_phase(cid, checkpoint, index, "collecting")
            await self._collect(
                cid, session, work, attempt, spec, boundaries, result, event
            )
            result["state"] = "succeeded"
        except _Cancelled:
            result["state"] = "cancelled"
            result["error"] = {
                "code": "SWEEP_CANCELLED",
                "message": "Cancellation was requested.",
            }
        except asyncio.CancelledError:
            event.set()
            result["state"] = "cancelled"
            result["error"] = {
                "code": "SWEEP_INTERRUPTED",
                "message": "The campaign worker was interrupted.",
            }
        except Exception as error:  # noqa: BLE001 - retain vendor and parser failure evidence
            result["error"] = PscadService.error_payload(error, "parameter_sweep")[
                "error"
            ]
        finally:
            try:
                self._checkpoint_phase(cid, checkpoint, index, "restoring")
            except (OSError, ValueError) as error:
                cleanup_ok = False
                result["checkpoint_error"] = PscadService.error_payload(
                    error, "checkpoint_sweep"
                )["error"]
            result["cleanup"] = {"parameters_restored": False, "session_absent": False}
            if session is not None:
                try:
                    if running:
                        await self._stop_owned_run(session, spec.project_name)
                    for component_id in changed:
                        await session.set_component_parameters(
                            spec.project_name, component_id, snapshots[component_id]
                        )
                        observed = await session.get_component_parameters(
                            spec.project_name, component_id
                        )
                        if not all(
                            _matches(observed.get(name), value)
                            for name, value in snapshots[component_id].items()
                        ):
                            raise sweep_error(
                                "SWEEP_RESTORE_FAILED",
                                "Original parameters did not read back after restoration.",
                            )
                    if changed:
                        await session.save_project(spec.project_name)
                    result["cleanup"]["parameters_restored"] = True
                except BaseException as error:  # noqa: BLE001 - cancellation must not hide incomplete restoration
                    cleanup_ok = False
                    result["cleanup"]["restore_error"] = PscadService.error_payload(
                        error, "restore_sweep"
                    )["error"]
                try:
                    await session.shutdown()
                    end = time.monotonic() + 3
                    while (
                        identity
                        and self.process_alive(identity)
                        and time.monotonic() < end
                    ):
                        await asyncio.sleep(0.1)
                    if identity and self.process_alive(identity):
                        raise sweep_error(
                            "SWEEP_SHUTDOWN_UNVERIFIED",
                            "The owned process is still alive after shutdown.",
                        )
                    result["cleanup"]["session_absent"] = True
                    shutdown_ok = True
                    lease.record_session(None)
                    executor = getattr(session, "executor", None)
                    if executor is not None and hasattr(
                        executor, "shutdown_if_settled"
                    ):
                        executor.shutdown_if_settled()
                except BaseException as error:  # noqa: BLE001 - retain ownership when shutdown is interrupted
                    cleanup_ok = False
                    self.cleanup_sessions[cid] = session
                    result["cleanup"]["shutdown_error"] = PscadService.error_payload(
                        error, "shutdown_sweep"
                    )["error"]
            else:
                result["cleanup"] = {
                    "parameters_restored": True,
                    "session_absent": True,
                }
                shutdown_ok = True
            if not cleanup_ok:
                result["state"] = "needs_review"
                checkpoint["error"] = {
                    "code": "SWEEP_CLEANUP_UNVERIFIED",
                    "message": "Restoration or owned-session shutdown needs review.",
                }
            result["finished_at"] = _now()
            result_path = attempt / "result.json"
            atomic_json(result_path, result)
            scenario_record["results"].append(
                {
                    "path": str(result_path.relative_to(root)),
                    "sha256": file_hash(result_path),
                }
            )
            scenario_record["state"] = result["state"]
            if shutdown_ok:
                checkpoint["active_attempt"] = None
            self.store.save(cid, checkpoint)
        return cleanup_ok

    async def _collect(
        self, cid, session, work, attempt, spec, boundaries, result, event
    ):
        for output in spec.outputs:
            self._check_cancel(cid, event)
            primary = contained(work, output.path, must_exist=True)
            metadata = None
            files = [primary]
            if primary.suffix.casefold() == ".out":
                metadata, files = legacy_dataset_paths(work, output.path)
            observations = {}
            for path in files:
                reject_link(path)
                info = path.stat()
                if not info.st_size or info.st_mtime_ns < boundaries[output.path]:
                    raise sweep_error(
                        "SWEEP_OUTPUT_STALE",
                        "A run output is empty or predates dispatch.",
                    )
                observations[path] = (info.st_size, info.st_mtime_ns, file_hash(path))
            await asyncio.sleep(spec.output_stability_seconds)
            self._check_cancel(cid, event)
            if metadata:
                files = [metadata, *files]
            for path in files:
                reject_link(path)
                relative = path.relative_to(work).as_posix()
                destination = contained(attempt / "outputs", relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                before = file_hash(path)
                shutil.copyfile(path, destination)
                if path in observations:
                    info = path.stat()
                    if observations[path] != (info.st_size, info.st_mtime_ns, before):
                        raise sweep_error(
                            "SWEEP_OUTPUT_UNSTABLE",
                            "A terminal output changed during collection.",
                        )
                if before != file_hash(destination) or before != file_hash(path):
                    raise sweep_error(
                        "SWEEP_OUTPUT_UNSTABLE", "An output changed while copying."
                    )
                artifact_relative = destination.relative_to(
                    self.store.campaign_path(cid)
                ).as_posix()
                result["artifacts"].append(
                    {
                        "path": str(destination),
                        "relative_path": artifact_relative,
                        "sha256": before,
                    }
                )
            copied = contained(attempt / "outputs", output.path, must_exist=True)
            if metadata:
                payload = await asyncio.to_thread(
                    read_legacy,
                    attempt / "outputs",
                    output.path,
                    output.channels,
                    spec.max_samples,
                )
            else:
                payload = await session.read_output_file(
                    str(copied), max_samples=spec.max_samples, summary_only=False
                )
            result["outputs"].append(
                {
                    "path": output.path,
                    "channels": summarize(payload, output.channels, spec.max_samples),
                    "warnings": [
                        str(item)[:256] for item in payload.get("warnings", [])[:20]
                    ],
                }
            )

    async def shutdown(self, timeout_s: float = 5) -> None:
        self.closing = True
        active = [task for task in self.tasks.values() if not task.done()]
        for cid, task in self.tasks.items():
            if not task.done():
                self.events[cid].set()
                atomic_json(
                    self._cancel_path(cid),
                    {"requested_at": _now(), "reason": "runtime_shutdown"},
                )
        if active:
            _done, pending = await asyncio.wait(active, timeout=timeout_s)
            if pending:
                from ...runtime import PendingCleanupError

                raise PendingCleanupError(tuple(pending))
        for cid, session in list(self.cleanup_sessions.items()):
            await session.shutdown()
            self.cleanup_sessions.pop(cid)
