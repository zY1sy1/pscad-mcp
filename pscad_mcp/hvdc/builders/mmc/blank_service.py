"""Explicit template-backed lifecycle for blank MMC requests.

The repository-owned AVM contract is useful for planning, but it is not a
PSCAD-instantiable full converter.  This service therefore plans blank MMC
requests from an audited official PSCAD project/library pair and keeps the
native-template mode explicit.  Dynamic fault execution is intentionally
delegated to the template-native path; no wall-clock event is inferred.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import json
import math
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from ....core.path_policy import PathPolicy
from ....core.service import ConfirmationRequired
from ....runtime import PendingCleanupError
from ..lcc.executor import _select_output_dataset
from .blank import BlankMmcRequest
from .journal import AtomicJournal, WorkspaceBuildLease
from .models import SubmoduleTopology
from .template_audit import (
    audit_mmc_template,
    discover_official_mmc_template,
)
from .template_native import (
    evaluate_template_native_dc_fault,
    materialize_template_native_scenario,
)

_TERMINAL_SUCCESS = {"completed", "complete", "finished", "done", "idle", "stopped"}
_TERMINAL_FAILURE = {"failed", "error", "aborted", "cancelled", "canceled"}


def _error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _status_value(value: Any) -> str:
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, Mapping):
        for key in ("status", "state", "run_state"):
            item = value.get(key)
            if isinstance(item, str):
                return item.casefold()
    return ""


def _run_sync(factory: Callable[[], Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    result: list[Any] = []
    failure: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(factory()))
        except BaseException as error:  # noqa: BLE001 - preserve reader failure identity
            failure.append(error)

    thread = threading.Thread(target=runner, name="blank-mmc-validation-reader", daemon=True)
    thread.start()
    thread.join()
    if failure:
        raise failure[0]
    return result[0]


def _workspace(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise _error("MMC_LAYOUT_INVALID", "The blank MMC workspace is not a directory.", "plan_blank_mmc_model")
    return root


def _project_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error("MMC_LAYOUT_INVALID", "project_name must be a non-empty string.", "plan_blank_mmc_model")
    name = Path(value.strip()).name
    if name.casefold().endswith(".pscx"):
        name = name[:-5]
    if not name or name != value.strip() and any(char in value.strip() for char in "/\\"):
        raise _error("MMC_LAYOUT_INVALID", "project_name must be a single PSCAD identity.", "plan_blank_mmc_model")
    if not name[0].isalpha() or len(name) > 128 or any(not (char.isalnum() or char in "_.-") for char in name):
        raise _error("MMC_LAYOUT_INVALID", "project_name contains unsupported characters.", "plan_blank_mmc_model")
    return name


def _regular(value: str | Path, suffix: str, operation: str) -> Path:
    raw = Path(value).expanduser()
    if raw.is_symlink():
        raise _error("MMC_TEMPLATE_NOT_FOUND", "The official MMC template pair must contain regular files.", operation, path=str(raw))
    path = raw.resolve()
    if path.suffix.casefold() != suffix or path.is_symlink() or not path.is_file():
        raise _error("MMC_TEMPLATE_NOT_FOUND", "The official MMC template pair must contain regular files.", operation, path=str(path))
    return path


class BlankMmcBuilderService:
    """Plan and (when supported) execute an official-template blank MMC case."""

    def __init__(self, pscad_service: Any, *, workspace_root: str | Path, audit_loader: Callable[..., Any] = audit_mmc_template) -> None:
        self.pscad_service = pscad_service
        self.workspace_root = _workspace(workspace_root)
        self.path_policy = PathPolicy(workspace_root=str(self.workspace_root))
        self.audit_loader = audit_loader
        self._plans: dict[str, dict[str, Any]] = {}
        self._statuses: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._leases: dict[str, WorkspaceBuildLease] = {}
        self._closing = False

    def _pair(self, template_path: str | Path | None, library_path: str | Path | None) -> tuple[Path, Path]:
        if template_path is None and library_path is None:
            return discover_official_mmc_template()
        if template_path is None or library_path is None:
            raise _error("MMC_TEMPLATE_PAIR_INVALID", "template_path and library_path must be supplied together.", "plan_blank_mmc_model")
        return _regular(template_path, ".pscx", "plan_blank_mmc_model"), _regular(library_path, ".pslx", "plan_blank_mmc_model")

    def plan_model(
        self,
        request: BlankMmcRequest | Mapping[str, Any] | str,
        folder: str | None = None,
        simulation_duration_s: float | None = None,
        blueprint: str = "cigre_b4_p2p_avm_v1",
        *,
        template_path: str | Path | None = None,
        library_path: str | Path | None = None,
    ) -> dict[str, Any]:
        if blueprint != "cigre_b4_p2p_avm_v1":
            raise _error("MMC_BLUEPRINT_NOT_FOUND", "Only the fixed blank MMC profile is supported.", "plan_blank_mmc_model", blueprint=blueprint)
        parsed = request if isinstance(request, BlankMmcRequest) else BlankMmcRequest.from_dict(request) if isinstance(request, Mapping) else BlankMmcRequest(project_name=request, folder=folder)
        name = _project_name(parsed.project_name)
        template_path = template_path or parsed.template_path
        library_path = library_path or parsed.library_path
        template, library = self._pair(template_path, library_path)
        try:
            template.relative_to(self.workspace_root)
            raise _error("MMC_LAYOUT_INVALID", "The read-only MMC template must be outside the build workspace.", "plan_blank_mmc_model")
        except ValueError:
            pass
        audit = self.audit_loader(str(template), str(library))
        if hasattr(audit, "to_dict") and callable(audit.to_dict):
            audit = audit.to_dict()
        if not isinstance(audit, Mapping) or audit.get("compatible") is not True:
            raise _error("MMC_TEMPLATE_INCOMPATIBLE", "The official MMC template failed its audit.", "plan_blank_mmc_model", audit=dict(audit) if isinstance(audit, Mapping) else None)
        observed_topology = audit.get("submodule_topology", {})
        observed_name = observed_topology.get("declared") if isinstance(observed_topology, Mapping) else "unknown"
        requested_topology = parsed.submodule_topology.value
        if observed_name not in {requested_topology, "unknown"}:
            raise _error("MMC_TEMPLATE_TOPOLOGY_MISMATCH", "The official MMC template topology differs from the request.", "plan_blank_mmc_model", requested=requested_topology, observed=observed_name)
        requested_folder = parsed.folder if parsed.folder is not None else folder
        parent = self.workspace_root if requested_folder is None else self.path_policy.resolve(requested_folder)
        raw_target = Path(parent) / f"{name}.pscx"
        if raw_target.is_symlink():
            raise _error(
                "MMC_BUILD_CONFLICT",
                "The blank MMC destination already exists.",
                "plan_blank_mmc_model",
                target_path=str(raw_target),
            )
        target = self.path_policy.resolve_child(str(parent), f"{name}.pscx", suffixes={".pscx"})
        if target.exists() or target.is_symlink():
            raise _error("MMC_BUILD_CONFLICT", "The blank MMC destination already exists.", "plan_blank_mmc_model", target_path=str(target))
        duration = 1.3 if simulation_duration_s is None else simulation_duration_s
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(float(duration))
            or duration <= 0
        ):
            raise _error("MMC_BLUEPRINT_INVALID", "simulation_duration_s must be finite and positive.", "plan_blank_mmc_model")
        source_hashes = dict(audit.get("source_hashes", {}))
        if set(source_hashes) != {"project", "library"}:
            source_hashes = {"project": hashlib.sha256(template.read_bytes()).hexdigest(), "library": hashlib.sha256(library.read_bytes()).hexdigest()}
        payload = {
            "schema_version": 1,
            "kind": "blank_mmc_native",
            "request": parsed.to_dict(),
            "project_name": name,
            "workspace": str(self.workspace_root),
            "target_path": str(target),
            "staging_path": str(self.workspace_root / ".pscad-mcp" / "blank-mmc-builds" / f"{name}-{source_hashes['project'][:12]}.staging"),
            "settings": {"simulation_duration_s": float(duration), "time_step_s": 50e-6, "output_step_s": 250e-6, "output_enabled": True},
            "fault": {"kind": "dc_pole_to_pole", "time_s": 0.3, "removal_time_s": 0.5},
            "template_native": {"source_paths": {"project": str(template), "library": str(library)}, "source_hashes": source_hashes, "submodule_topology": dict(observed_topology) if isinstance(observed_topology, Mapping) else {}, "controls": dict(audit.get("template_native_controls", {})) if isinstance(audit.get("template_native_controls", {}), Mapping) else {}},
            "capabilities": {**SubmoduleTopology.capabilities(parsed.submodule_topology), "template_submodule_topology": observed_name, "native_schedule": False, "template_native_timing": bool(isinstance(audit.get("template_native_controls"), Mapping) and audit["template_native_controls"].get("available") is True)},
            "operations": ["audit_source", "stage_template_pair", "compile", "simulate_template_native_fault", "validate_fault_evidence", "publish"],
        }
        plan = {**payload, "plan_hash": hashlib.sha256(json_bytes(payload)).hexdigest(), "status": "planned"}
        self._plans[plan["plan_hash"]] = copy.deepcopy(plan)
        return plan

    async def build_model(
        self,
        request: BlankMmcRequest | Mapping[str, Any] | str,
        expected_plan_hash: str,
        *args: Any,
        confirm: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not confirm:
            raise ConfirmationRequired("build_blank_mmc_model")
        parsed = (
            request
            if isinstance(request, BlankMmcRequest)
            else BlankMmcRequest.from_dict(request)
            if isinstance(request, Mapping)
            else BlankMmcRequest(project_name=request)
        )
        folder = kwargs.get("folder", parsed.folder)
        duration = kwargs.get("simulation_duration_s")
        if duration is None and args:
            duration = args[0]
        blueprint = kwargs.get("blueprint", "cigre_b4_p2p_avm_v1")
        template_path = kwargs.get("template_path", parsed.template_path)
        library_path = kwargs.get("library_path", parsed.library_path)
        plan = self.plan_model(
            parsed,
            folder=folder,
            simulation_duration_s=duration,
            blueprint=blueprint,
            template_path=template_path,
            library_path=library_path,
        )
        if not isinstance(expected_plan_hash, str) or not hmac.compare_digest(
            expected_plan_hash, plan["plan_hash"]
        ):
            raise _error(
                "MMC_PLAN_STALE",
                "The supplied blank MMC plan hash is stale.",
                "build_blank_mmc_model",
                expected_plan_hash=expected_plan_hash if isinstance(expected_plan_hash, str) else "",
                observed_plan_hash=plan["plan_hash"],
            )
        target = Path(plan["target_path"])
        staging = Path(plan["staging_path"])
        if target.exists() or target.is_symlink() or staging.exists() or staging.is_symlink():
            raise _error(
                "MMC_BUILD_CONFLICT",
                "A planned blank MMC destination already exists.",
                "build_blank_mmc_model",
                target_path=str(target),
                staging_path=str(staging),
            )
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
        task = asyncio.create_task(
            self._run(build_id, plan, journal, lease),
            name=f"blank-mmc-{build_id}",
        )
        self._tasks[build_id] = task
        task.add_done_callback(lambda completed: self._task_done(build_id, completed))
        await asyncio.sleep(0)
        return {
            key: initial[key]
            for key in ("build_id", "state", "plan_hash", "target_path", "staging_path")
        }

    async def _run(
        self,
        build_id: str,
        plan: dict[str, Any],
        journal: AtomicJournal,
        lease: WorkspaceBuildLease,
    ) -> dict[str, Any]:
        try:
            record = await _execute_native_mmc_plan(
                plan,
                self.pscad_service,
                self.workspace_root,
                build_id=build_id,
                journal=journal,
            )
        except asyncio.CancelledError:
            record = {
                "build_id": build_id,
                "state": "interrupted",
                "plan_hash": plan["plan_hash"],
                "plan": copy.deepcopy(plan),
                "error": _error(
                    "MMC_BUILD_FAILED",
                    "The blank MMC build was interrupted.",
                    "build_blank_mmc_model",
                ).to_dict(),
                "result": None,
                "history": [{"state": "validated"}, {"state": "interrupted"}],
                "workspace": str(self.workspace_root),
            }
        except BaseException as error:  # noqa: BLE001 - lifecycle records capture vendor failures
            backend_error = (
                error
                if isinstance(error, BackendError)
                else _error(
                    "MMC_BUILD_FAILED",
                    "The blank MMC build failed.",
                    "build_blank_mmc_model",
                    exception=type(error).__name__,
                )
            )
            record = {
                "build_id": build_id,
                "state": "failed",
                "plan_hash": plan["plan_hash"],
                "plan": copy.deepcopy(plan),
                "error": backend_error.to_dict(),
                "result": None,
                "history": [
                    {"state": "validated"},
                    {"state": "failed", "reason": backend_error.code},
                ],
                "workspace": str(self.workspace_root),
            }
        finally:
            self._statuses[build_id] = record
            journal.write(record)
            lease.release(lease.token)
            self._leases.pop(build_id, None)
        return record

    def _task_done(self, build_id: str, task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except BaseException:  # noqa: BLE001,S110 - consume terminal task failures
            pass
        self._tasks.pop(build_id, None)

    def get_build_status(self, build_id: str) -> dict[str, Any]:
        if build_id not in self._statuses:
            path = AtomicJournal(self.workspace_root, build_id).path
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise _error(
                    "NOT_FOUND",
                    "The blank MMC build was not found.",
                    "get_blank_mmc_build_status",
                    build_id=build_id,
                ) from error
            if not isinstance(value, dict):
                raise _error(
                    "MMC_JOURNAL_INVALID",
                    "The blank MMC journal is not an object.",
                    "get_blank_mmc_build_status",
                    build_id=build_id,
                )
            self._statuses[build_id] = value
        return copy.deepcopy(self._statuses[build_id])

    def validate_model(
        self,
        project_name: str,
        blueprint: str = "cigre_b4_p2p_avm_v1",
        output_file: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        if blueprint != "cigre_b4_p2p_avm_v1":
            raise _error("MMC_BLUEPRINT_NOT_FOUND", "Only the fixed blank MMC profile is supported.", "validate_blank_mmc_model")
        raw_candidate = Path(project_name).expanduser()
        if not raw_candidate.is_absolute():
            raw_candidate = self.workspace_root / raw_candidate
        if raw_candidate.is_symlink():
            raise _error(
                "MMC_LAYOUT_INVALID",
                "The MMC project must not be a symbolic link.",
                "validate_blank_mmc_model",
                project_name=str(raw_candidate),
            )
        candidate = raw_candidate
        if candidate.suffix.casefold() != ".pscx":
            candidate = candidate.with_suffix(".pscx")
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError as error:
            raise _error("MMC_LAYOUT_INVALID", "The MMC project is outside the workspace.", "validate_blank_mmc_model") from error
        if not candidate.is_file() or candidate.is_symlink():
            raise _error("NOT_FOUND", "The blank MMC project was not found.", "validate_blank_mmc_model", project_name=str(candidate))
        template_path = _.get("template_path")
        library_path = _.get("library_path")
        if (template_path is None) != (library_path is None):
            raise _error(
                "MMC_TEMPLATE_PAIR_INVALID",
                "template_path and library_path must be supplied together.",
                "validate_blank_mmc_model",
            )
        topology_name = "unknown"
        native_audit: dict[str, Any] | None = None
        if template_path is not None and library_path is not None:
            audited = self.audit_loader(str(template_path), str(library_path))
            if hasattr(audited, "to_dict") and callable(audited.to_dict):
                audited = audited.to_dict()
            if isinstance(audited, Mapping):
                native_audit = dict(audited)
                topology = audited.get("submodule_topology")
                if isinstance(topology, Mapping) and isinstance(topology.get("declared"), str):
                    topology_name = topology["declared"]
        audit_valid = native_audit is None or native_audit.get("compatible") is True
        result: dict[str, Any] = {
            "project_file": str(candidate),
            "project_sha256": _sha256(candidate),
            "valid": audit_valid,
            "accepted": False,
            "output_file": None,
            "acceptance": {"status": "not_evaluated", "verdict": "not_evaluated"},
            "native_template": native_audit,
            "capabilities": SubmoduleTopology.capabilities(
                SubmoduleTopology.FULL_BRIDGE
                if topology_name == "full_bridge"
                else SubmoduleTopology.HALF_BRIDGE
            )
            if topology_name in {"full_bridge", "half_bridge"}
            else {"intrinsic_dc_fault_blocking": False},
        }
        if output_file is None:
            return result
        raw_output = Path(output_file).expanduser()
        if raw_output.is_symlink():
            raise _error(
                "MMC_LAYOUT_INVALID",
                "The MMC output must not be a symbolic link.",
                "validate_blank_mmc_model",
                output_file=str(raw_output),
            )
        output = raw_output.resolve()
        try:
            output.relative_to(self.workspace_root)
        except ValueError as error:
            raise _error("MMC_LAYOUT_INVALID", "The MMC output is outside the workspace.", "validate_blank_mmc_model") from error
        reader = getattr(self.pscad_service, "read_output_file", None)
        if not callable(reader):
            raise _error("MMC_OUTPUT_INCOMPLETE", "The PSCAD service does not expose an output reader.", "validate_blank_mmc_model")
        samples = _run_sync(lambda: _read_async(reader, str(output)))
        if topology_name not in {"full_bridge", "half_bridge"}:
            acceptance = {
                "verdict": "INCOMPLETE_ANALYSIS",
                "reason": "The MMC template topology was not explicitly audited.",
            }
        else:
            topology = SubmoduleTopology(topology_name)
            acceptance = evaluate_template_native_dc_fault(
                samples,
                fault_current_limit_ka=20.0,
                topology=topology,
            )
        result["output_file"] = str(output)
        result["acceptance"] = {**acceptance, "status": "evaluated"}
        result["accepted"] = bool(
            audit_valid and acceptance.get("verdict") == "PASS"
        )
        return result

    async def shutdown(self, timeout_s: float = 5.0) -> None:
        self._closing = True
        tasks = tuple(task for task in self._tasks.values() if not task.done())
        for task in tasks:
            task.cancel()
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=max(0.0, timeout_s))
            if pending:
                raise PendingCleanupError(tuple(pending))
            for task in done:
                try:
                    task.result()
                except BaseException:  # noqa: BLE001,S110 - consume terminal cancellation
                    pass
        for build_id, lease in tuple(self._leases.items()):
            record = self._statuses.get(build_id)
            if record is not None:
                AtomicJournal(self.workspace_root, build_id).write(record)
            lease.release(lease.token)
            self._leases.pop(build_id, None)


def json_bytes(value: Any) -> bytes:
    import json

    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


async def _read_async(reader: Any, output_file: str) -> Any:
    try:
        return await reader(output_file, max_samples=1_000_000, summary_only=False)
    except TypeError:
        return await reader(output_file)


async def _execute_native_mmc_plan(
    plan: Mapping[str, Any],
    service: Any,
    workspace: Path,
    *,
    build_id: str,
    journal: AtomicJournal,
) -> dict[str, Any]:
    """Run one audited official MMC template and retain incomplete evidence."""

    source_paths = plan["template_native"]["source_paths"]
    source_hashes = plan["template_native"]["source_hashes"]
    source_project = Path(str(source_paths["project"])).expanduser().resolve()
    source_library = Path(str(source_paths["library"])).expanduser().resolve()
    for key, path in (("project", source_project), ("library", source_library)):
        if not path.is_file() or path.is_symlink() or _sha256(path) != str(source_hashes[key]):
            raise _error("MMC_PLAN_STALE", "An official MMC source changed after planning.", "build_blank_mmc_model", source=key, path=str(path))
    staging = Path(str(plan["staging_path"])).expanduser().resolve()
    project_name = str(plan["project_name"])
    staging.mkdir(parents=True, exist_ok=False)
    staged_library = staging / source_library.name
    staged_project = staging / f"{project_name}.pscx"
    shutil.copy2(source_library, staged_library)
    support = source_library.parent / "Obj_Files_2016_03_25"
    if support.is_dir():
        shutil.copytree(support, staging / support.name)
    from ....core.backend import legacy_support

    legacy_support.rewrite_template_identity(
        source_project,
        staged_project,
        project_name,
    )
    loader = getattr(service, "load_projects", None)
    writer = getattr(service, "set_project_settings", None)
    settings_reader = getattr(service, "get_project_settings", None)
    saver = getattr(service, "save_project", None)
    builder = getattr(service, "build_project", None)
    runner = getattr(service, "run_project", None)
    status_reader = getattr(service, "get_run_status", None)
    discover = getattr(service, "discover_output_files", None)
    reader = getattr(service, "read_output_file", None)
    required = {
        "load_projects": loader,
        "set_project_settings": writer,
        "get_project_settings": settings_reader,
        "save_project": saver,
        "build_project": builder,
        "run_project": runner,
        "get_run_status": status_reader,
        "discover_output_files": discover,
        "read_output_file": reader,
    }
    missing = sorted(name for name, method in required.items() if not callable(method))
    if missing:
        raise _error("MMC_BUILD_UNAVAILABLE", "The PSCAD service lacks native blank MMC lifecycle capabilities.", "build_blank_mmc_model", missing=missing)
    await loader([str(staged_library), str(staged_project)])
    requested = {
        "time_duration": str(plan["settings"]["simulation_duration_s"]),
        "time_step": "50",
        "sample_step": "250",
        "PlotType": "1",
        "output_filename": f"{project_name}.out",
    }
    await writer(project_name, requested)
    observed = await settings_reader(project_name)
    if not isinstance(observed, Mapping) or any(str(observed.get(key)) != value for key, value in requested.items()):
        raise _error("MMC_POSTCONDITION_FAILED", "Native MMC project settings did not read back exactly.", "build_blank_mmc_model", expected=requested, observed=observed)
    await saver(project_name, confirm=True)
    await builder(project_name)
    scenario = staging / f"{project_name}_scenario_source.pscx"
    materialize_template_native_scenario(
        staged_project,
        scenario,
        dc_fault_time_s=float(plan["fault"]["time_s"]),
        fault_duration_s=float(plan["fault"]["removal_time_s"] - plan["fault"]["time_s"]),
    )
    await loader([str(staged_library), str(scenario)])
    await writer(scenario.stem, {**requested, "output_filename": f"{scenario.stem}.out"})
    await saver(scenario.stem, confirm=True)
    await builder(scenario.stem)
    started_after = time.time()
    await runner(scenario.stem)
    deadline = time.monotonic() + 900.0
    while True:
        state = await status_reader(scenario.stem)
        value = _status_value(state)
        if value in _TERMINAL_FAILURE:
            raise _error("MMC_BUILD_FAILED", "The native MMC simulation failed.", "build_blank_mmc_model", status=state)
        if value in _TERMINAL_SUCCESS:
            break
        if time.monotonic() >= deadline:
            raise _error("MMC_BUILD_TIMED_OUT", "The native MMC simulation did not finish in time.", "build_blank_mmc_model")
        await asyncio.sleep(0.25)
    paths = await discover(str(scenario), started_after=started_after, max_files=32)
    candidates = sorted({str(Path(path).expanduser().resolve()) for path in paths if isinstance(path, str) and path}, key=str.casefold)
    for path in candidates:
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            raise _error("MMC_OUTPUT_INCOMPLETE", "A native MMC output is not a regular file.", "build_blank_mmc_model", path=path)
        try:
            candidate.relative_to(staging)
        except ValueError as error:
            raise _error("MMC_OUTPUT_INCOMPLETE", "A native MMC output escaped staging.", "build_blank_mmc_model", path=path) from error
    if not candidates:
        raise _error("MMC_OUTPUT_INCOMPLETE", "The native MMC simulation produced no output.", "build_blank_mmc_model")
    output_file, output_parts = _select_output_dataset(candidates)
    samples = await reader(output_file, max_samples=1_000_000, summary_only=False)
    topology = SubmoduleTopology(plan["request"]["submodule_topology"])
    acceptance = evaluate_template_native_dc_fault(samples, fault_current_limit_ka=20.0, topology=topology)
    target = Path(str(plan["target_path"])).expanduser().resolve()
    archive = target.with_name(f"{target.stem}.outputs")
    if archive.exists() or archive.is_symlink():
        raise _error("MMC_BUILD_CONFLICT", "The native MMC output evidence directory already exists.", "build_blank_mmc_model", path=str(archive))
    archive.mkdir(parents=True, exist_ok=False)
    archived_parts: list[str] = []
    for path in output_parts:
        destination = archive / Path(path).name
        shutil.copy2(path, destination)
        archived_parts.append(str(destination.resolve()))
    base = re.sub(r"_\d{2}$", "", Path(output_file).stem)
    for suffix in (".inf", ".infx"):
        metadata = Path(output_file).with_name(base + suffix)
        if metadata.is_file() and not metadata.is_symlink():
            shutil.copy2(metadata, archive / metadata.name)
    persisted_output = str(archive / Path(output_file).name)
    if acceptance.get("verdict") != "PASS":
        code = "MMC_ACCEPTANCE_INCOMPLETE" if acceptance.get("verdict") == "INCOMPLETE_ANALYSIS" else "MMC_ACCEPTANCE_FAILED"
        return {
            "build_id": build_id,
            "state": "failed",
            "plan_hash": plan["plan_hash"],
            "target_path": str(target),
            "staging_path": str(staging),
            "workspace": str(workspace),
            "history": [{"state": "validated"}, {"state": "staging_created"}, {"state": "compiled"}, {"state": "simulated", "output_file": persisted_output}, {"state": "acceptance_incomplete", "verdict": acceptance.get("verdict")}],
            "error": _error(code, "The native MMC fault evidence is not sufficient for the requested topology.", "build_blank_mmc_model", acceptance=acceptance).to_dict(),
            "result": {"output_file": persisted_output, "output_parts": archived_parts, "acceptance": acceptance, "scenario_source": str(scenario), "template_native": dict(plan["template_native"])},
        }
    save_as = getattr(service, "save_project_as", None)
    if not callable(save_as):
        raise _error("MMC_BUILD_UNAVAILABLE", "The PSCAD service cannot publish the native MMC project.", "build_blank_mmc_model")
    target.parent.mkdir(parents=True, exist_ok=True)
    await save_as(staged_project.stem, target.name, str(target.parent), confirm=False)
    final_library = target.parent / source_library.name
    if final_library.exists() or final_library.is_symlink():
        raise _error("MMC_BUILD_CONFLICT", "The native MMC companion publication target already exists.", "build_blank_mmc_model", path=str(final_library))
    shutil.copy2(staged_library, final_library)
    scenario_target = target.with_name(f"{target.stem}_scenario_source.pscx")
    shutil.copy2(target, scenario_target)
    await loader([str(final_library), str(target)])
    await builder(target.stem)
    return {
        "build_id": build_id,
        "state": "published",
        "plan_hash": plan["plan_hash"],
        "target_path": str(target),
        "staging_path": str(staging),
        "workspace": str(workspace),
        "history": [{"state": "validated"}, {"state": "published"}],
        "error": None,
        "result": {"output_file": persisted_output, "output_parts": archived_parts, "acceptance": acceptance, "final_library_path": str(final_library), "scenario_source": str(scenario_target), "final_project_sha256": _sha256(target)},
    }


__all__ = ["BlankMmcBuilderService"]
