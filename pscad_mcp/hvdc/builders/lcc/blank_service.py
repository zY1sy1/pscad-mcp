"""Lifecycle service for blank LCC builds backed by a real PSCAD template."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import json
import math
import os
import re
import threading
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from ....core.path_policy import PathPolicy
from ....core.service import ConfirmationRequired
from ....runtime import PendingCleanupError
from ..common.serialization import content_hash
from .blank import BlankLccRequest
from .executor import _select_output_dataset
from .journal import AtomicJournal, WorkspaceBuildLease
from .native_template import (
    audit_native_lcc_template,
    evaluate_native_lcc_commutation,
    materialize_native_lcc_bundle,
)

_TERMINAL_SUCCESS = {"completed", "complete", "finished", "done", "idle", "stopped"}
_TERMINAL_FAILURE = {"failed", "error", "aborted", "cancelled", "canceled"}
_RUNNING = {"running", "started", "starting", "simulating", "busy", "queued", "pending"}
def _error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _status(value: Any) -> str:
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, Mapping):
        for key in ("status", "state", "run_state"):
            item = value.get(key)
            if isinstance(item, str):
                return item.casefold()
    return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_sync(factory: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    result: list[Any] = []
    failure: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(factory()))
        except BaseException as error:  # noqa: BLE001 - preserve cancellation/error identity across the reader thread
            failure.append(error)

    thread = threading.Thread(target=runner, name="blank-lcc-validation-reader", daemon=True)
    thread.start()
    thread.join()
    if failure:
        raise failure[0]
    return result[0]


def _workspace_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise _error("LCC_LAYOUT_INVALID", "The blank LCC workspace is not a directory.", "plan_blank_lcc_model", workspace=str(root))
    return root


def _safe_project_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error("LCC_LAYOUT_INVALID", "project_name must be a non-empty string.", "plan_blank_lcc_model")
    name = value.strip()
    if name.casefold().endswith(".pscx"):
        name = name[:-5]
    if not name or any(token in name for token in ("/", "\\")) or name in {".", ".."}:
        raise _error("LCC_LAYOUT_INVALID", "project_name must be a single PSCAD identity.", "plan_blank_lcc_model", project_name=value)
    if not name[0].isalpha() or any(not (char.isalnum() or char in "_.-") for char in name) or len(name) > 128:
        raise _error("LCC_LAYOUT_INVALID", "project_name contains unsupported characters.", "plan_blank_lcc_model", project_name=value)
    return name


def _resolve_template(value: str | Path | None) -> Path:
    candidate = value or os.environ.get("PSCAD_MCP_LCC_TEMPLATE")
    if not isinstance(candidate, (str, Path)) or not str(candidate).strip():
        raise _error(
            "LCC_TEMPLATE_REQUIRED",
            "A downloaded PSCAD 4.6 LCC example is required; pass template_path or set PSCAD_MCP_LCC_TEMPLATE.",
            "plan_blank_lcc_model",
            suggested_action="Extract cigre_lcc_bidirectional.zip and provide its .pscx path.",
        )
    raw = Path(candidate).expanduser()
    if raw.is_symlink():
        raise _error("LCC_TEMPLATE_INCOMPATIBLE", "template_path must be an existing regular PSCX file.", "plan_blank_lcc_model", path=str(raw))
    path = raw.resolve()
    if path.suffix.casefold() != ".pscx" or path.is_symlink() or not path.is_file():
        raise _error("LCC_TEMPLATE_INCOMPATIBLE", "template_path must be an existing regular PSCX file.", "plan_blank_lcc_model", path=str(path))
    return path


def _contained(path: Path, root: Path, *, label: str, operation: str) -> Path:
    raw = path.expanduser()
    if raw.is_symlink():
        raise _error(
            "LCC_LAYOUT_INVALID",
            f"{label} must not be a symbolic link.",
            operation,
            path=str(raw),
        )
    resolved = raw.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise _error("LCC_LAYOUT_INVALID", f"{label} is outside the configured workspace.", operation, path=str(resolved)) from error
    return resolved


def _plan_payload(
    request: BlankLccRequest,
    *,
    workspace: Path,
    template: Path,
    audit: Mapping[str, Any],
    target: Path,
    staging: Path,
    duration: float,
    fault_time: float,
    fault_duration: float,
    fault_resistance: float,
    current_limit: float,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "blank_lcc_native",
        "request": request.to_dict(),
        "workspace": str(workspace),
        "target_path": str(target),
        "staging_path": str(staging),
        "native_template": {
            "source": str(template),
            "source_sha256": audit["source_sha256"],
            "pscad_version": audit.get("pscad_version"),
            "definitions": list(audit.get("definitions", ())),
            "output_channels": list(audit.get("output_channels", ())),
        },
        "companion": {
            "namespace": "cigre_lcc_v1",
            "filename": "cigre_lcc_v1.pslx",
            "source": "extracted_from_audited_official_definitions",
        },
        "settings": {
            "simulation_duration_s": duration,
            "time_step_s": 50e-6,
            "output_step_s": 250e-6,
            "output_enabled": True,
        },
        "fault": {
            "kind": "inverter_ac_three_phase",
            "time_s": fault_time,
            "duration_s": fault_duration,
            "resistance_ohm": fault_resistance,
            "phase_mask": [1, 1, 1],
            "current_limit_pu": current_limit,
            "recovery_delay_s": 0.5,
        },
        "operations": [
            "audit_source",
            "materialize_native_bundle",
            "load_companion_and_project",
            "set_and_verify_settings",
            "compile",
            "simulate",
            "evaluate_commutation_fault",
            "publish",
        ],
    }


class BlankLccBuilderService:
    """Build a real CIGRE LCC example into a new contained workspace target."""

    def __init__(self, pscad_service: Any, *, workspace_root: str | Path) -> None:
        self.pscad_service = pscad_service
        self.workspace_root = _workspace_root(workspace_root)
        self.path_policy = PathPolicy(workspace_root=str(self.workspace_root))
        self._plans: dict[str, dict[str, Any]] = {}
        self._statuses: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._leases: dict[str, WorkspaceBuildLease] = {}
        self._closing = False

    def _compose(
        self,
        project_name: str,
        folder: str | None,
        simulation_duration_s: float | None,
        template_path: str | Path | None,
        request: BlankLccRequest | None = None,
    ) -> dict[str, Any]:
        name = _safe_project_name(project_name)
        template = _resolve_template(template_path)
        try:
            template.relative_to(self.workspace_root)
        except ValueError:
            pass
        else:
            raise _error(
                "LCC_LAYOUT_INVALID",
                "The read-only source template must be outside the build workspace.",
                "plan_blank_lcc_model",
                template=str(template),
            )
        audit = audit_native_lcc_template(template).to_dict()
        if not audit.get("compatible"):
            raise _error(
                "LCC_TEMPLATE_INCOMPATIBLE",
                "The supplied LCC template failed its native audit.",
                "plan_blank_lcc_model",
                errors=list(audit.get("errors", ())),
            )
        try:
            parent = self.workspace_root if folder is None else self.path_policy.resolve(folder)
            raw_target = Path(parent) / f"{name}.pscx"
            if raw_target.is_symlink():
                raise _error(
                    "LCC_BUILD_CONFLICT",
                    "The blank LCC destination already exists.",
                    "plan_blank_lcc_model",
                    target_path=str(raw_target),
                )
            target = self.path_policy.resolve_child(str(parent), f"{name}.pscx", suffixes={".pscx"})
        except (ValueError, OSError) as error:
            raise _error("LCC_LAYOUT_INVALID", str(error), "plan_blank_lcc_model", folder=folder) from error
        if target.exists() or target.is_symlink():
            raise _error("LCC_BUILD_CONFLICT", "The blank LCC destination already exists.", "plan_blank_lcc_model", target_path=str(target))
        fault_time = 0.8
        fault_duration = 0.1
        duration = 2.5 if simulation_duration_s is None else simulation_duration_s
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(float(duration))
            or not 0 < float(duration)
        ):
            raise _error("LCC_BLUEPRINT_INVALID", "simulation_duration_s must be finite and positive.", "plan_blank_lcc_model")
        if float(duration) < fault_time + fault_duration + 0.5:
            raise _error("LCC_BLUEPRINT_INVALID", "simulation_duration_s is too short to observe fault recovery.", "plan_blank_lcc_model", minimum=fault_time + fault_duration + 0.5)
        staging = self.workspace_root / ".pscad-mcp" / "blank-lcc-builds" / f"{name}-{audit['source_sha256'][:12]}.staging"
        payload = _plan_payload(
            request or BlankLccRequest(project_name=name, folder=str(parent)),
            workspace=self.workspace_root,
            template=template,
            audit=audit,
            target=target,
            staging=staging,
            duration=float(duration),
            fault_time=fault_time,
            fault_duration=fault_duration,
            fault_resistance=1e-6,
            current_limit=3.0,
        )
        return {**payload, "plan_hash": content_hash(payload), "status": "planned"}

    def plan_model(
        self,
        project_name: str,
        folder: str | None = None,
        simulation_duration_s: float | None = None,
        blueprint: str = "cigre_lcc_monopole_v1",
        *,
        template_path: str | Path | None = None,
        request: BlankLccRequest | None = None,
    ) -> dict[str, Any]:
        if blueprint != "cigre_lcc_monopole_v1":
            raise _error("LCC_BLUEPRINT_NOT_FOUND", "Only the fixed CIGRE LCC blank profile is supported.", "plan_blank_lcc_model", blueprint=blueprint)
        parsed = request or BlankLccRequest(project_name=project_name, folder=folder)
        effective_folder = folder if folder is not None else parsed.folder
        effective_template = template_path or parsed.template_path
        plan = self._compose(
            project_name,
            effective_folder,
            simulation_duration_s,
            effective_template,
            parsed,
        )
        self._plans[plan["plan_hash"]] = copy.deepcopy(plan)
        return plan

    async def build_model(
        self,
        project_name: str,
        expected_plan_hash: str,
        folder: str | None = None,
        simulation_duration_s: float | None = None,
        blueprint: str = "cigre_lcc_monopole_v1",
        confirm: bool = False,
        *,
        template_path: str | Path | None = None,
        request: BlankLccRequest | None = None,
    ) -> dict[str, Any]:
        if not confirm:
            raise ConfirmationRequired("build_blank_lcc_model")
        parsed = request or BlankLccRequest(project_name=project_name, folder=folder)
        effective_folder = folder if folder is not None else parsed.folder
        effective_template = template_path or parsed.template_path
        plan = self._compose(
            project_name,
            effective_folder,
            simulation_duration_s,
            effective_template,
            parsed,
        )
        if not isinstance(expected_plan_hash, str) or not hmac.compare_digest(expected_plan_hash, plan["plan_hash"]):
            raise _error("LCC_PLAN_STALE", "The supplied blank LCC plan hash is stale.", "build_blank_lcc_model", expected_plan_hash=expected_plan_hash if isinstance(expected_plan_hash, str) else "", observed_plan_hash=plan["plan_hash"])
        target = Path(plan["target_path"])
        staging = Path(plan["staging_path"])
        if target.exists() or target.is_symlink() or staging.exists() or staging.is_symlink():
            raise _error("LCC_BUILD_CONFLICT", "A planned blank LCC destination already exists.", "build_blank_lcc_model", target_path=str(target), staging_path=str(staging))
        build_id = uuid.uuid4().hex
        lease = WorkspaceBuildLease.acquire(self.workspace_root, build_id)
        journal = AtomicJournal(self.workspace_root, build_id)
        initial = {
            "build_id": build_id,
            "state": "validated",
            "plan_hash": plan["plan_hash"],
            "target_path": plan["target_path"],
            "staging_path": plan["staging_path"],
            "workspace": str(self.workspace_root),
            "plan": copy.deepcopy(plan),
            "history": [{"state": "validated"}],
            "error": None,
            "result": None,
        }
        self._statuses[build_id] = initial
        self._leases[build_id] = lease
        journal.write(initial)
        task = asyncio.create_task(self._run(build_id, plan, journal, lease), name=f"blank-lcc-{build_id}")
        self._tasks[build_id] = task
        task.add_done_callback(lambda completed: self._task_done(build_id, completed))
        await asyncio.sleep(0)
        return {key: initial[key] for key in ("build_id", "state", "plan_hash", "target_path", "staging_path")}

    async def _run(self, build_id: str, plan: dict[str, Any], journal: AtomicJournal, lease: WorkspaceBuildLease) -> dict[str, Any]:
        try:
            record = await _execute_native_plan(plan, self.pscad_service, self.workspace_root, build_id=build_id, journal=journal)
        except asyncio.CancelledError:
            record = {"build_id": build_id, "state": "interrupted", "plan_hash": plan["plan_hash"], "plan": copy.deepcopy(plan), "error": _error("LCC_BUILD_FAILED", "The blank LCC build was interrupted.", "build_blank_lcc_model").to_dict(), "result": None, "history": [{"state": "validated"}, {"state": "interrupted"}], "workspace": str(self.workspace_root)}
        except BaseException as error:  # noqa: BLE001 - lifecycle records must capture every failure class
            backend_error = error if isinstance(error, BackendError) else _error("LCC_BUILD_FAILED", "The blank LCC build failed.", "build_blank_lcc_model", exception=type(error).__name__)
            record = {"build_id": build_id, "state": "failed", "plan_hash": plan["plan_hash"], "plan": copy.deepcopy(plan), "error": backend_error.to_dict(), "result": None, "history": [{"state": "validated"}, {"state": "failed", "reason": backend_error.code}], "workspace": str(self.workspace_root)}
        finally:
            self._statuses[build_id] = record
            journal.write(record)
            lease.release(lease.token)
            self._leases.pop(build_id, None)
        return record

    def _task_done(self, build_id: str, task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except BaseException:  # noqa: BLE001,S110 - consume task failures after journaling
            pass
        self._tasks.pop(build_id, None)

    def get_build_status(self, build_id: str) -> dict[str, Any]:
        if build_id not in self._statuses:
            path = AtomicJournal(self.workspace_root, build_id).path
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise _error("NOT_FOUND", "The blank LCC build was not found.", "get_blank_lcc_build_status", build_id=build_id) from error
            if not isinstance(value, dict):
                raise _error("LCC_JOURNAL_INVALID", "The blank LCC journal is not an object.", "get_blank_lcc_build_status", build_id=build_id)
            self._statuses[build_id] = value
        return copy.deepcopy(self._statuses[build_id])

    def validate_model(self, project_name: str, blueprint: str = "cigre_lcc_monopole_v1", output_file: str | None = None, *, template_path: str | Path | None = None) -> dict[str, Any]:
        if blueprint != "cigre_lcc_monopole_v1":
            raise _error("LCC_BLUEPRINT_NOT_FOUND", "Only the fixed CIGRE LCC blank profile is supported.", "validate_blank_lcc_model")
        candidate = Path(project_name).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace_root / _safe_project_name(project_name)
        if candidate.suffix.casefold() != ".pscx":
            candidate = candidate.with_suffix(".pscx")
        project = _contained(candidate, self.workspace_root, label="project", operation="validate_blank_lcc_model")
        if not project.is_file() or project.is_symlink():
            raise _error("NOT_FOUND", "The blank LCC project was not found.", "validate_blank_lcc_model", project_name=str(project))
        audit = audit_native_lcc_template(project).to_dict()
        external_library = project.parent / "cigre_lcc_v1.pslx"
        valid = bool(audit.get("compatible")) or (external_library.is_file() and set(audit.get("errors", ())) <= {"fault_timer_not_unique", "fault_timer_parameters_missing"})
        result: dict[str, Any] = {"valid": valid, "project_file": str(project), "project_sha256": _sha256(project), "output_file": None, "accepted": False, "native_template": audit}
        if output_file is None:
            result["acceptance"] = {"status": "not_evaluated", "verdict": "not_evaluated"}
            return result
        waveform = _contained(Path(output_file).expanduser(), self.workspace_root, label="output", operation="validate_blank_lcc_model")
        reader = getattr(self.pscad_service, "read_output_file", None)
        if not callable(reader):
            raise _error("LCC_OUTPUT_INCOMPLETE", "The PSCAD service does not expose an output reader.", "validate_blank_lcc_model")
        samples = _run_sync(lambda: _read_async(reader, str(waveform)))
        acceptance = evaluate_native_lcc_commutation(samples, fault_time_s=0.8, fault_duration_s=0.1, current_limit_pu=3.0)
        result["output_file"] = str(waveform)
        result["acceptance"] = {**acceptance, "status": "evaluated"}
        result["accepted"] = bool(valid and acceptance.get("verdict") == "PASS")
        return result

    async def shutdown(self, timeout_s: float = 5.0) -> None:
        self._closing = True
        tasks = tuple(task for task in self._tasks.values() if not task.done())
        for task in tasks:
            task.cancel()
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=timeout_s)
            if pending:
                raise PendingCleanupError(tuple(pending))
            for task in done:
                try:
                    task.result()
                except BaseException:  # noqa: BLE001,S110 - consume completed cancellation/error
                    pass


async def _read_async(reader: Any, output_file: str) -> Any:
    try:
        return await reader(output_file, max_samples=1_000_000, summary_only=False)
    except TypeError:
        return await reader(output_file)


async def _execute_native_plan(plan: Mapping[str, Any], service: Any, workspace: Path, *, build_id: str, journal: AtomicJournal) -> dict[str, Any]:
    source = Path(str(plan["native_template"]["source"])).expanduser().resolve()
    if not source.is_file() or source.is_symlink() or _sha256(source) != str(plan["native_template"]["source_sha256"]):
        raise _error("LCC_PLAN_STALE", "The official LCC source changed after planning.", "build_blank_lcc_model", source=str(source))
    staging = Path(str(plan["staging_path"])).resolve()
    project = staging / f"{Path(str(plan['target_path'])).stem}.pscx"
    library = staging / "cigre_lcc_v1.pslx"
    staging.mkdir(parents=True, exist_ok=False)
    materialized = materialize_native_lcc_bundle(
        source,
        project,
        library,
        project_name=project.stem,
        fault_time_s=float(plan["fault"]["time_s"]),
        fault_duration_s=float(plan["fault"]["duration_s"]),
        time_duration_s=float(plan["settings"]["simulation_duration_s"]),
        fault_resistance_ohm=float(plan["fault"]["resistance_ohm"]),
    )
    loader = getattr(service, "load_projects", None)
    settings_writer = getattr(service, "set_project_settings", None)
    settings_reader = getattr(service, "get_project_settings", None)
    saver = getattr(service, "save_project", None)
    builder = getattr(service, "build_project", None)
    runner = getattr(service, "run_project", None)
    status_reader = getattr(service, "get_run_status", None)
    discover = getattr(service, "discover_output_files", None)
    reader = getattr(service, "read_output_file", None)
    required = {"load_projects": loader, "set_project_settings": settings_writer, "get_project_settings": settings_reader, "save_project": saver, "build_project": builder, "run_project": runner, "get_run_status": status_reader, "discover_output_files": discover, "read_output_file": reader}
    missing = sorted(name for name, method in required.items() if not callable(method))
    if missing:
        raise _error("LCC_BUILD_UNAVAILABLE", "The PSCAD service lacks native blank LCC lifecycle capabilities.", "build_blank_lcc_model", missing=missing)
    await loader([str(library), str(project)])
    requested = {"time_duration": str(plan["settings"]["simulation_duration_s"]), "time_step": "50", "sample_step": "250", "PlotType": "1", "output_filename": f"{project.stem}.out"}
    await settings_writer(project.stem, requested)
    observed = await settings_reader(project.stem)
    if not isinstance(observed, Mapping) or any(str(observed.get(key)) != value for key, value in requested.items()):
        raise _error("LCC_POSTCONDITION_FAILED", "Native LCC project settings did not read back exactly.", "build_blank_lcc_model", expected=requested, observed=observed)
    await saver(project.stem, confirm=True)
    await builder(project.stem)
    started_after = time.time()
    await runner(project.stem)
    deadline = time.monotonic() + 900.0
    while True:
        state = await status_reader(project.stem)
        value = _status(state)
        if value in _TERMINAL_FAILURE:
            raise _error("LCC_BUILD_FAILED", "The native LCC simulation failed.", "build_blank_lcc_model", status=state)
        if value in _TERMINAL_SUCCESS:
            break
        if time.monotonic() >= deadline:
            raise _error("LCC_BUILD_TIMED_OUT", "The native LCC simulation did not finish in time.", "build_blank_lcc_model")
        await asyncio.sleep(0.25)
    paths = await discover(str(project), started_after=started_after, max_files=32)
    candidates = [str(Path(path).expanduser().resolve()) for path in paths if isinstance(path, str) and path]
    staging_root = staging.resolve()
    for path in candidates:
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            raise _error("LCC_OUTPUT_INCOMPLETE", "A native LCC output is not a regular file.", "build_blank_lcc_model", path=path)
        try:
            candidate.relative_to(staging_root)
        except ValueError as error:
            raise _error("LCC_OUTPUT_INCOMPLETE", "A native LCC output escaped staging.", "build_blank_lcc_model", path=path) from error
    if not candidates:
        raise _error("LCC_OUTPUT_INCOMPLETE", "The native LCC simulation produced no output.", "build_blank_lcc_model")
    output_file, output_parts = _select_output_dataset(sorted(set(candidates), key=str.casefold))
    samples = await reader(output_file, max_samples=1_000_000, summary_only=False)
    acceptance = evaluate_native_lcc_commutation(samples, fault_time_s=float(plan["fault"]["time_s"]), fault_duration_s=float(plan["fault"]["duration_s"]), current_limit_pu=float(plan["fault"]["current_limit_pu"]), recovery_delay_s=float(plan["fault"]["recovery_delay_s"]))
    if acceptance.get("verdict") != "PASS":
        raise _error("LCC_ACCEPTANCE_FAILED", "The native LCC commutation-fault evidence did not pass.", "build_blank_lcc_model", acceptance=acceptance)
    expected_source_hash = str(plan["native_template"]["source_sha256"])
    observed_source_hash = _sha256(source)
    if observed_source_hash != expected_source_hash:
        raise _error("LCC_PLAN_STALE", "The official LCC source changed during execution.", "build_blank_lcc_model", expected_sha256=expected_source_hash, observed_sha256=observed_source_hash)
    target = Path(str(plan["target_path"])).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    import shutil

    output_archive = target.with_name(f"{target.stem}.outputs")
    if output_archive.exists() or output_archive.is_symlink():
        raise _error("LCC_BUILD_CONFLICT", "The native LCC output evidence directory already exists.", "build_blank_lcc_model", path=str(output_archive))
    output_archive.mkdir(parents=True, exist_ok=False)
    archived_parts: list[str] = []
    for part in output_parts:
        source_part = Path(part)
        destination_part = output_archive / source_part.name
        shutil.copy2(source_part, destination_part)
        archived_parts.append(str(destination_part.resolve()))
    output_stem = Path(output_file).stem
    output_base = re.sub(r"_\d{2}$", "", output_stem)
    for suffix in (".inf", ".infx"):
        metadata = Path(output_file).with_name(output_base + suffix)
        if metadata.is_file() and not metadata.is_symlink():
            shutil.copy2(metadata, output_archive / metadata.name)
    output_file = str(output_archive / Path(output_file).name)
    output_parts = archived_parts
    await saver(project.stem, confirm=True)
    save_as = getattr(service, "save_project_as", None)
    if not callable(save_as):
        raise _error("LCC_BUILD_UNAVAILABLE", "The PSCAD service cannot publish the native LCC project.", "build_blank_lcc_model")
    await save_as(project.stem, target.name, str(target.parent), confirm=False)
    if not target.is_file() or target.is_symlink():
        raise _error("LCC_POSTCONDITION_FAILED", "The native LCC publication file was not created.", "build_blank_lcc_model")
    final_library = target.parent / "cigre_lcc_v1.pslx"
    if final_library.exists() or final_library.is_symlink():
        raise _error("LCC_BUILD_CONFLICT", "The native LCC companion publication target already exists.", "build_blank_lcc_model", path=str(final_library))
    shutil.copy2(library, final_library)
    scenario = target.with_name(f"{target.stem}_scenario_source.pscx")
    if scenario.exists() or scenario.is_symlink():
        raise _error("LCC_BUILD_CONFLICT", "The native LCC scenario source target already exists.", "build_blank_lcc_model", path=str(scenario))
    shutil.copy2(target, scenario)
    await loader([str(final_library), str(target)])
    await builder(target.stem)
    if _sha256(source) != expected_source_hash:
        raise _error("LCC_PLAN_STALE", "The official LCC source changed before publication completed.", "build_blank_lcc_model", expected_sha256=expected_source_hash, observed_sha256=_sha256(source))
    final_hash = _sha256(target)
    return {
        "build_id": build_id,
        "state": "published",
        "plan_hash": plan["plan_hash"],
        "target_path": str(target),
        "staging_path": str(staging),
        "workspace": str(workspace),
        "history": [{"state": "validated"}, {"state": "staging_created"}, {"state": "compiled"}, {"state": "simulated", "output_file": output_file}, {"state": "acceptance_passed", "acceptance": acceptance}, {"state": "published", "final_project_sha256": final_hash}],
        "error": None,
        "result": {"output_file": output_file, "output_parts": output_parts, "acceptance": acceptance, "final_project_sha256": final_hash, "final_library_path": str(final_library), "final_library_sha256": _sha256(final_library), "scenario_source": str(scenario), "materialized": materialized},
    }


__all__ = ["BlankLccBuilderService"]
