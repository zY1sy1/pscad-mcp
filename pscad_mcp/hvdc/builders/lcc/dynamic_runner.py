"""Licensed fixed-LCC dynamic acceptance orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from ....core.process_inventory import list_pscad_processes
from .dynamic_acceptance import (
    FAIL,
    INCOMPLETE,
    PASS,
    combine_dynamic_verdicts,
    validate_dynamic_lcc_acceptance_report,
)
from .dynamic_evidence import derive_fixed_lcc_dynamic_evidence


@dataclass(frozen=True)
class DynamicLccRunRequest:
    repository_root: Path
    workspace_root: Path
    master_path: Path
    compiler_configuration: Path
    compiler_executable: Path
    report_path: Path
    commit: str
    branch: str
    project_name: str = "WP1C_FIXED_LCC"
    simulation_duration_s: float = 1.5
    output_step_s: float = 0.00005
    preflight: Mapping[str, Any] = field(default_factory=dict)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _await(value: Any) -> Any:
    return value


async def _maybe(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _error(stage: str, message: str, code: str = "LCC_DYNAMIC_RUN_FAILED") -> BackendError:
    return BackendError(code, message, "hvdc", "run_fixed_lcc_dynamic_acceptance", {"stage": stage})


def _source_paths(request: DynamicLccRunRequest) -> dict[str, Path]:
    root = request.repository_root / "pscad_mcp" / "assets" / "lcc" / "cigre_lcc_monopole_v1"
    names = {
        "blueprint": "blueprint.json",
        "catalog": "catalog-pscad-4.6.2.json",
        "dynamic": "dynamic.json",
        "registry": "master-bindings-pscad-4.6.2.json",
        "manifest": "manifest.json",
        "companion": "cigre_lcc_v1.pslx",
    }
    result: dict[str, Path] = {
        "master": request.master_path,
        "compiler_configuration": request.compiler_configuration,
        "compiler_executable": request.compiler_executable,
    }
    for key, filename in names.items():
        result[key] = root / ("library" if key == "companion" else "") / filename
    return result


def _regular(path: Path) -> bool:
    """Reject links/reparse points before resolving and require a regular file."""
    try:
        if path.is_symlink() or not path.exists() or not path.is_file():
            return False
        attrs = getattr(path.stat(), "st_file_attributes", 0)
        return not bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return False


def _contained(path: Path, root: Path) -> bool:
    try:
        current = path.absolute()
        root_abs = root.absolute()
        if not current.is_relative_to(root_abs):
            return False
        for parent in (root_abs, *current.parents):
            if parent == current:
                continue
            if parent.is_symlink() or bool(getattr(parent.stat(), "st_file_attributes", 0) & 0x400):
                return False
            if parent == root_abs:
                break
    except OSError:
        return False
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _empty_report(request: DynamicLccRunRequest, sources: Mapping[str, Path]) -> dict[str, Any]:
    zeros = "0" * 64
    source_record = {}
    for name, path in sources.items():
        try:
            digest = _sha(path)
        except BaseException:  # noqa: BLE001 - best effort fail envelope
            digest = zeros
        source_record[name] = {"path": str(path.resolve()), "before": digest, "after": digest}
    commit = request.commit if isinstance(request.commit, str) and re.fullmatch(r"[0-9a-f]{40}", request.commit) else zeros[:40]
    return {
        "schema_version": 1,
        "run_id": request.report_path.absolute().parent.name or request.report_path.stem,
        "scope": "lcc.fixed_autonomous",
        "builder_path": "lcc.fixed_autonomous",
        "kind": "licensed_simulation",
        "capability_state": "simulated",
        "commit": commit,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "engineering_verdict": INCOMPLETE,
        "golden_verdict": INCOMPLETE,
        "status": INCOMPLETE,
        "repository": {"branch": request.branch, "commit": commit, "clean": True},
        "preflight": {"status": ((request.preflight.get("status") if isinstance(request.preflight, Mapping) else FAIL) if isinstance((request.preflight.get("status") if isinstance(request.preflight, Mapping) else None), str) else FAIL), "sha256": ((request.preflight.get("sha256") if isinstance(request.preflight, Mapping) else zeros) if isinstance((request.preflight.get("sha256") if isinstance(request.preflight, Mapping) else None), str) else zeros), "snapshot": {}},
        "sources": source_record,
        "build": {"project_name": request.project_name, "workspace": str(request.workspace_root.resolve()), "build_id": None, "plan_hash": None, "verification_profile": "wp1c_dynamic", "history": [], "terminal_state": "not_started"},
        "artifacts": {"project": None, "library": None, "selected_output": None, "output_parts": [], "output_metadata": [], "normalized_samples": None},
        "dynamic": {"evidence_source": "raw_pscad_output", "engineering_verdict": INCOMPLETE, "checks": {}},
        "physical": {"verdict": INCOMPLETE, "checks": []},
        "golden": {"source": "placeholder", "reviewed": False},
        "runtime": {"remaining_processes": [], "managed_pid": None, "backend": None, "version": None, "x64": None, "licensed": None, "quit_error": None},
        "explicit_exclusions": ["independent_golden", "final_accepted"],
        "failure": None,
    }


def _atomic_write(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(report, ensure_ascii=True, allow_nan=False, sort_keys=True, indent=2) + "\n").encode("ascii")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _fail(report: dict[str, Any], stage: str, error: BaseException) -> dict[str, Any]:
    report["engineering_verdict"] = FAIL
    report["golden_verdict"] = INCOMPLETE
    report["status"] = FAIL
    report["failure"] = {"stage": stage, "code": getattr(error, "code", type(error).__name__), "message": str(error)[:1024]}
    report["build"]["terminal_state"] = "failed"
    report["dynamic"] = {"evidence_source": "raw_pscad_output", "engineering_verdict": FAIL, "checks": {}}
    report["physical"] = {"verdict": FAIL, "checks": [{"name": "runner_failure", "kind": "runner_failure", "required": True, "status": "failed", "outcome": FAIL}]}
    return report


def build_dynamic_lcc_failure_report(
    request: DynamicLccRunRequest,
    *,
    stage: str,
    error: BaseException,
) -> dict[str, Any]:
    """Build a strict, durable FAIL envelope when setup/lifecycle cannot run."""
    sources = _source_paths(request)
    report = _empty_report(request, sources)
    snapshot: dict[str, Any] = {}
    for name, path in sources.items():
        try:
            digest = _sha(path)
        except BaseException:  # noqa: BLE001 - failure envelope uses a zero digest
            digest = "0" * 64
        snapshot[name] = {"path": str(path.absolute()), "sha256": digest}
    report["preflight"] = {
        "status": str(request.preflight.get("status", FAIL)) if isinstance(request.preflight, Mapping) else FAIL,
        "sha256": _canonical_hash(snapshot),
        "snapshot": snapshot,
    }
    report["sources"] = {
        name: {"path": item["path"], "before": item["sha256"], "after": item["sha256"]}
        for name, item in snapshot.items()
    }
    return validate_dynamic_lcc_acceptance_report(_fail(report, stage, error))


def _owned(entry: Mapping[str, Any], run_id: str, managed_pid: Any) -> bool:
    return managed_pid is not None and entry.get("pid") == managed_pid


async def run_fixed_lcc_dynamic_acceptance(
    request: DynamicLccRunRequest,
    *,
    service: Any,
    builder: Any,
    process_reader: Callable[[], Any] = list_pscad_processes,
    process_terminator: Callable[[int], Any] | None = None,
    poll_interval_s: float = 0.5,
    timeout_s: float = 900.0,
) -> dict[str, Any]:
    sources = _source_paths(request)
    report = _empty_report(request, sources)
    run_started = time.time()
    before: dict[str, str] = {}
    setup_failed = False
    report_write_allowed = not (request.report_path.exists() or request.report_path.is_symlink())
    try:
        for name, path in sources.items():
            if not _regular(path):
                raise _error("setup", f"source file is missing or not regular: {name}", "LCC_DYNAMIC_SOURCE_INVALID")
            before[name] = _sha(path)
        requested_snapshot = request.preflight.get("snapshot") if isinstance(request.preflight, Mapping) else None
        if not isinstance(requested_snapshot, Mapping) or set(requested_snapshot) != set(sources):
            raise _error("setup", "preflight snapshot must cover every source", "LCC_DYNAMIC_PREFLIGHT_FAILED")
        for name, item in requested_snapshot.items():
            if not isinstance(item, Mapping) or str(item.get("path")) != str(sources[name].absolute()) or str(item.get("sha256")) != before[name]:
                raise _error("setup", f"preflight snapshot drift for {name}", "LCC_DYNAMIC_SOURCE_DRIFT")
        if not isinstance(request.preflight, Mapping) or str(request.preflight.get("sha256")) != _canonical_hash(requested_snapshot):
            raise _error("setup", "preflight canonical hash mismatch", "LCC_DYNAMIC_PREFLIGHT_FAILED")
        report["sources"] = {
            name: {"path": str(path.absolute()), "before": before[name], "after": before[name]}
            for name, path in sources.items()
        }
        report["preflight"]["snapshot"] = {name: {"path": str(path.absolute()), "sha256": before[name]} for name, path in sources.items()}
    except BaseException as error:  # noqa: BLE001 - persist setup failure envelope
        setup_failed = True
        zeros = "0" * 64
        report["sources"] = {
            name: {"path": str(path.absolute()), "before": before.get(name, zeros), "after": before.get(name, zeros)}
            for name, path in sources.items()
        }
        report["preflight"]["snapshot"] = {
            name: {"path": str(path.absolute()), "sha256": before.get(name, zeros)}
            for name, path in sources.items()
        }
        report["preflight"]["status"] = FAIL
        report["preflight"]["sha256"] = _canonical_hash(report["preflight"]["snapshot"])
        report = _fail(report, "setup", error)
    stage = "setup"
    managed_pid = None
    try:
        if not request.workspace_root.exists() or not request.workspace_root.is_dir():
            raise _error(stage, "workspace_root must be an existing directory")
        if not _contained(request.report_path, request.workspace_root):
            raise _error(stage, "report_path escaped workspace")
        if not report_write_allowed:
            raise _error(stage, "report_path already exists")
        if not re.fullmatch(r"[0-9a-f]{40}", request.commit):
            raise _error(stage, "commit must be a lowercase SHA")
        if len(before) != len(sources):
            raise _error(stage, "source preflight failed", "LCC_DYNAMIC_SOURCE_INVALID")
        if setup_failed:
            raise _error(stage, "source/preflight snapshot validation failed", "LCC_DYNAMIC_PREFLIGHT_FAILED")
        if request.preflight.get("status") != PASS:
            raise _error(stage, "static preflight failed", "LCC_DYNAMIC_PREFLIGHT_FAILED")
        existing_processes = await _maybe(process_reader())
        if existing_processes:
            raise _error(stage, "pre-existing PSCAD processes detected", "LCC_DYNAMIC_PROCESS_PREFLIGHT_FAILED")
        stage = "attach"
        await _maybe(service.attach_local())
        status = await _maybe(service.status())
        if isinstance(status, Mapping):
            session = status.get("session")
            managed_pid = session.get("managed_pid") if isinstance(session, Mapping) else None
            report["runtime"].update({k: status.get(k) for k in ("backend", "version", "x64", "licensed") if k in status})
            report["runtime"]["managed_pid"] = managed_pid
        stage = "plan"
        plan = builder.plan_model(project_name=request.project_name, folder=str(request.workspace_root), simulation_duration_s=request.simulation_duration_s, blueprint="cigre_lcc_monopole_v1", verification_profile="wp1c_dynamic")
        if not isinstance(plan, Mapping) or not isinstance(plan.get("plan_hash"), str):
            raise _error(stage, "invalid plan")
        report["build"]["plan_hash"] = plan["plan_hash"]
        stage = "build"
        started = await _maybe(builder.build_model(project_name=request.project_name, expected_plan_hash=plan["plan_hash"], folder=str(request.workspace_root), simulation_duration_s=request.simulation_duration_s, blueprint="cigre_lcc_monopole_v1", verification_profile="wp1c_dynamic", confirm=True))
        if not isinstance(started, Mapping) or not isinstance(started.get("build_id"), str):
            raise _error(stage, "invalid build identity")
        build_id = started["build_id"]
        report["build"]["build_id"] = build_id
        stage = "poll"
        deadline = time.monotonic() + timeout_s
        while True:
            record = await _maybe(builder.get_build_status(build_id))
            if not isinstance(record, Mapping):
                raise _error(stage, "invalid build status")
            if record.get("state") in {"published", "failed", "timed_out", "interrupted"}:
                break
            if time.monotonic() >= deadline:
                raise _error(stage, "build timed out", "LCC_BUILD_TIMED_OUT")
            await asyncio.sleep(poll_interval_s)
        report["build"].update({"terminal_state": record.get("state"), "history": [item.get("state") for item in record.get("history", []) if isinstance(item, Mapping)]})
        if record.get("state") != "published" or "dynamic_engineering_passed" not in report["build"]["history"]:
            raise _error(stage, "build did not publish dynamic engineering evidence")
        artifact_sources = []
        for candidate in (record, started):
            if isinstance(candidate, Mapping):
                nested = candidate.get("result")
                artifact_sources.append(nested if isinstance(nested, Mapping) else candidate)
        for artifact_key, path_keys, hash_keys in (
            ("project", ("project_path", "project_file", "final_project_path"), ("project_sha256", "final_project_sha256")),
            ("library", ("library_path", "final_library_path"), ("library_sha256", "final_library_sha256")),
        ):
            path_value = next((item.get(key) for item in artifact_sources for key in path_keys if item.get(key)), None)
            hash_value = next((item.get(key) for item in artifact_sources for key in hash_keys if item.get(key)), None)
            if path_value is None:
                fallback = request.workspace_root / (f"{request.project_name}.pscx" if artifact_key == "project" else "cigre_lcc_v1.pslx")
                if _regular(fallback):
                    path_value = str(fallback)
            if path_value is None:
                raise _error(stage, f"build did not report {artifact_key} artifact")
            artifact_path = Path(str(path_value))
            if not _regular(artifact_path) or not _contained(artifact_path.absolute(), request.workspace_root.absolute()):
                raise _error(stage, f"{artifact_key} artifact is not a contained regular file")
            observed_hash = _sha(artifact_path)
            if hash_value is not None and str(hash_value) != observed_hash:
                raise _error(stage, f"{artifact_key} artifact hash mismatch")
            report["artifacts"][artifact_key] = {"path": str(artifact_path.absolute()), "sha256": observed_hash}
        stage = "output"
        discover = getattr(service, "discover_output_files", None)
        file_reader = getattr(service, "read_output_file", None)
        if callable(discover) and callable(file_reader):
            discovered = await _maybe(discover(request.project_name, started_after=run_started, max_files=1000))
            if not isinstance(discovered, Sequence) or isinstance(discovered, (str, bytes, bytearray)):
                raise _error(stage, "output discovery returned no file list")
            output_candidates = [Path(str(item)) for item in discovered if Path(str(item)).suffix.casefold() in {".out", ".psout"}]
            if not output_candidates:
                raise _error(stage, "output discovery returned no OUT file")
            selected_hint = max(output_candidates, key=lambda item: item.stat().st_mtime if item.exists() else 0.0)
            if not _regular(selected_hint) or not _contained(selected_hint.absolute(), request.workspace_root.absolute()):
                raise _error(stage, "selected output is not a contained regular file")
            output = await _maybe(file_reader(str(selected_hint), max_samples=1_000_000, summary_only=False))
            if isinstance(output, Mapping):
                output = dict(output)
                output.setdefault("output_file", str(selected_hint))
                output.setdefault("output_parts", [str(item) for item in discovered])
        else:
            reader = getattr(service, "get_project_output", None)
            if not callable(reader):
                reader = getattr(builder, "get_project_output", None)
            if not callable(reader):
                raise _error(stage, "raw output reader unavailable", "LCC_DYNAMIC_OUTPUT_UNAVAILABLE")
            output = await _maybe(reader(request.project_name))
            if not isinstance(output, Mapping) or not any(key in output for key in ("raw_channels", "raw", "channels")):
                raise _error(stage, "fallback output did not provide raw channels", "LCC_DYNAMIC_OUTPUT_UNAVAILABLE")
        if isinstance(output, Mapping) and isinstance(output.get("result"), Mapping):
            output = output["result"]
        if not isinstance(output, Mapping):
            raise _error(stage, "output reread returned no mapping")
        output_file = output.get("output_file") or output.get("selected_output")
        output_parts = output.get("output_parts") or []
        if output_file is None and output_parts:
            output_file = output_parts[0]
        if not output_file:
            raise _error(stage, "selected output is missing")
        selected_raw = Path(output_file)
        if not _regular(selected_raw):
            raise _error(stage, "selected output is not a regular file")
        selected = selected_raw.resolve()
        staging = selected.parent
        try:
            selected.relative_to(request.workspace_root.resolve())
        except ValueError as error:
            raise _error(stage, "selected output escaped workspace") from error
        if not _regular(selected):
            raise _error(stage, "selected output is not a regular file")
        if selected.stat().st_mtime < run_started:
            raise _error(stage, "selected output is stale")
        stem = re.sub(r"_\d{2}$", "", selected.stem)
        candidates = []
        for path in staging.iterdir():
            matches = path.name == f"{stem}.inf" or path.name == f"{stem}.infx" or re.fullmatch(re.escape(stem) + r"_.*\.out", path.name, re.IGNORECASE)
            if matches and path.is_symlink():
                raise _error(stage, "output dataset contains symlink")
            if path.is_symlink() or not path.is_file() or path.parent.resolve() != staging.resolve():
                continue
            if matches:
                candidates.append(path)
        if any(path.stat().st_mtime < run_started for path in candidates):
            raise _error(stage, "output dataset contains stale files")
        outs = [p for p in candidates if p.suffix.casefold() == ".out"]
        metadata = [p for p in candidates if p.suffix.casefold() in {".inf", ".infx"}]
        if not outs or not metadata:
            raise _error(stage, "output dataset lacks OUT or INF/INFX parts")
        artifacts = [{"path": str(path.resolve()), "sha256": _sha(path)} for path in sorted(candidates, key=lambda p: p.name)]
        report["artifacts"]["selected_output"] = {"path": str(selected), "sha256": _sha(selected)}
        report["artifacts"]["output_parts"] = [item for item in artifacts if Path(item["path"]).suffix.casefold() == ".out"]
        report["artifacts"]["output_metadata"] = [item for item in artifacts if Path(item["path"]).suffix.casefold() in {".inf", ".infx"}]
        stage = "derive"
        raw_channels = output.get("raw_channels") or output.get("raw") or output.get("channels")
        if isinstance(raw_channels, list):
            raw_channels = {"channels": raw_channels}
        if not isinstance(raw_channels, Mapping):
            raise _error(stage, "raw PSCAD channels are missing")
        contract = {}
        try:
            packaged_dynamic = sources["dynamic"]
            contract = json.loads(packaged_dynamic.read_text(encoding="utf-8"))
        except BaseException as error:
            raise _error(stage, "packaged dynamic contract unavailable", "LCC_DYNAMIC_CONTRACT_UNAVAILABLE") from error
        dynamic = derive_fixed_lcc_dynamic_evidence(raw_channels, contract, output_step_s=request.output_step_s)
        published_result = record.get("result") if isinstance(record.get("result"), Mapping) else {}
        executor = published_result.get("dynamic") if isinstance(published_result, Mapping) else None
        if executor is None or json.dumps(executor, sort_keys=True, separators=(",", ":")) != json.dumps(dynamic, sort_keys=True, separators=(",", ":")):
            raise _error(stage, "executor evidence mismatch", "LCC_DYNAMIC_EVIDENCE_MISMATCH")
        physical = published_result.get("physical") if isinstance(published_result, Mapping) else None
        if not isinstance(physical, Mapping):
            raise _error(stage, "published physical evidence is missing", "LCC_DYNAMIC_EVIDENCE_MISMATCH")
        physical_checks = physical.get("physical_checks")
        if not isinstance(physical_checks, list):
            raise _error(stage, "published physical evidence shape is invalid", "LCC_DYNAMIC_EVIDENCE_MISMATCH")
        physical = {"verdict": physical.get("verdict"), "checks": physical_checks}
        report["dynamic"] = {"evidence_source": "raw_pscad_output", "engineering_verdict": dynamic.get("engineering_verdict", FAIL), "checks": dynamic.get("checks", {})}
        report["physical"] = physical
        report["engineering_verdict"] = combine_dynamic_verdicts(dynamic.get("engineering_verdict", FAIL), physical["verdict"])
        report["golden_verdict"] = INCOMPLETE
        report["status"] = combine_dynamic_verdicts(report["engineering_verdict"], report["golden_verdict"])
        normalized_path = request.workspace_root / "normalized-samples.json"
        _atomic_write(normalized_path, raw_channels)
        report["artifacts"]["normalized_samples"] = {"path": str(normalized_path.resolve()), "sha256": _sha(normalized_path)}
    except BaseException as error:  # noqa: BLE001 - persist lifecycle failures
        report = _fail(report, stage, error)
    finally:
        stage = "cleanup"
        cleanup_error: BaseException | None = None
        for target, method in ((builder, "shutdown"), (service, "quit_pscad")):
            fn = getattr(target, method, None)
            if callable(fn):
                try:
                    await _maybe(fn(confirm=True) if method == "quit_pscad" else fn(timeout_s=5.0))
                except BaseException as error:  # noqa: BLE001 - cleanup controls verdict
                    cleanup_error = cleanup_error or error
        try:
            remaining = [dict(item) for item in (await _maybe(process_reader()) or []) if isinstance(item, Mapping)]
        except BaseException as error:  # noqa: BLE001 - process evidence controls verdict
            remaining = []
            cleanup_error = cleanup_error or error
        owned_remaining = [item for item in remaining if _owned(item, report["run_id"], managed_pid)]
        if process_terminator is not None:
            for item in owned_remaining:
                try:
                    await _maybe(process_terminator(int(item["pid"])))
                except BaseException as error:  # noqa: BLE001 - cleanup controls verdict
                    cleanup_error = cleanup_error or error
        try:
            remaining = [dict(item) for item in (await _maybe(process_reader()) or []) if isinstance(item, Mapping)]
            owned_remaining = [item for item in remaining if _owned(item, report["run_id"], managed_pid)]
        except BaseException as error:  # noqa: BLE001 - process evidence controls verdict
            cleanup_error = cleanup_error or error
        report["runtime"]["remaining_processes"] = owned_remaining
        report["runtime"]["quit_error"] = str(cleanup_error)[:1024] if cleanup_error else None
        for name, path in sources.items():
            try:
                report["sources"][name]["after"] = _sha(path)
            except BaseException:  # noqa: BLE001 - source drift controls verdict
                report["sources"][name]["after"] = "0" * 64
        cleanup_issue = cleanup_error or owned_remaining or any(report["sources"][n]["before"] != report["sources"][n]["after"] for n in report["sources"])
        if cleanup_issue and (report["status"] != FAIL or report["failure"] is None):
            report = _fail(report, "cleanup", cleanup_error or RuntimeError("cleanup residue or source drift"))
    stage = "report"
    try:
        normalized = validate_dynamic_lcc_acceptance_report(report)
    except BaseException as error:  # noqa: BLE001 - report validation controls verdict
        normalized = validate_dynamic_lcc_acceptance_report(_fail(report, stage, error))
    if report_write_allowed:
        _atomic_write(request.report_path, normalized)
        loaded = json.loads(request.report_path.read_text(encoding="utf-8"))
        return validate_dynamic_lcc_acceptance_report(loaded)
    return normalized


__all__ = [
    "DynamicLccRunRequest",
    "build_dynamic_lcc_failure_report",
    "run_fixed_lcc_dynamic_acceptance",
]
