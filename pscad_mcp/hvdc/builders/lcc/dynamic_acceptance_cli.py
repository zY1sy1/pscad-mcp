"""CLI for evaluating fixed LCC dynamic evidence exported from PSCAD."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....acceptance.preflight import PreflightRequest, run_static_preflight
from ....core.backend.base import BackendError
from ....core.backend.legacy import LegacyBackend
from ....core.executor import robust_executor
from ....core.path_policy import PathPolicy
from ....core.process_inventory import list_pscad_processes
from ....acceptance.process_scope import acceptance_launch_policy
from ....core.service import PscadService
from .dynamic_acceptance import (
    FAIL,
    INCOMPLETE,
    PASS,
    evaluate_fixed_lcc_dynamic_samples,
    validate_dynamic_lcc_acceptance_report,
)
from .dynamic_runner import (
    DynamicLccRunRequest,
    build_dynamic_lcc_failure_report,
    run_fixed_lcc_dynamic_acceptance,
)
from .service import LccBuilderService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--samples", type=Path, required=True)
    evaluate.add_argument("--golden", type=Path, required=True)
    evaluate.add_argument("--contract", type=Path, required=True)
    evaluate.add_argument("--report", type=Path, required=True)
    evaluate.add_argument("--commit", required=True)
    evaluate.add_argument("--branch", required=True)
    evaluate.add_argument("--project-name", default="WP1C_FIXED_LCC")
    evaluate.add_argument("--event-kind", default="inverter_ac_disturbance")
    evaluate.add_argument("--event-time", type=float, required=True)
    evaluate.add_argument("--event-duration", type=float, required=True)
    evaluate.add_argument("--recovery-window", type=float, required=True)
    run = commands.add_parser("run")
    run.add_argument("--repository-root", type=Path, required=True)
    run.add_argument("--workspace-root", type=Path, required=True)
    run.add_argument("--master-path", type=Path, required=True)
    run.add_argument("--compiler-configuration", type=Path, required=True)
    run.add_argument("--compiler-executable", type=Path, required=True)
    run.add_argument("--report", type=Path, required=True)
    run.add_argument("--commit", required=True)
    run.add_argument("--branch", required=True)
    run.add_argument("--project-name", default="WP1C_FIXED_LCC")
    run.add_argument("--simulation-duration", type=float, default=1.5)
    run.add_argument("--output-step", type=float, default=0.00005)
    return parser


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, allow_nan=False, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _required_channels(contract: Mapping[str, Any]) -> list[str]:
    value = contract.get("required_channels", ())
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ["Main/VDC_RECT"]
    result = [str(item) for item in value]
    return result or ["Main/VDC_RECT"]


def _safe_commit(value: Any) -> str:
    text = value if isinstance(value, str) else ""
    if len(text) == 40 and all(char in "0123456789abcdef" for char in text):
        return text
    return "0" * 40


def _safe_float(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) else 0.0


def _report(
    arguments: argparse.Namespace,
    *,
    status: str,
    contract: Mapping[str, Any],
    golden: Mapping[str, Any],
    result: Mapping[str, Any] | None,
    failure: BaseException | None,
) -> dict[str, Any]:
    dynamic_result = result.get("dynamic", {}) if isinstance(result, Mapping) else {}
    physical_result = result.get("physical", {}) if isinstance(result, Mapping) else {}
    physical_verdict = (
        physical_result.get("verdict", INCOMPLETE)
        if isinstance(physical_result, Mapping)
        else INCOMPLETE
    )
    report = {
        "schema_version": 1,
        "run_id": arguments.report.resolve().parent.name or arguments.report.resolve().stem,
        "scope": "lcc.fixed_autonomous",
        "builder_path": "lcc.fixed_autonomous",
        "kind": "licensed_acceptance",
        "capability_state": "simulated",
        "commit": _safe_commit(arguments.commit),
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "repository": {
            "branch": arguments.branch,
            "commit": _safe_commit(arguments.commit),
            "clean": True,
        },
        "dynamic": {
            "evidence_source": "caller_supplied_diagnostic",
            "durable": False,
            "event": {
                "kind": arguments.event_kind,
                "time_s": _safe_float(arguments.event_time),
                "duration_s": _safe_float(arguments.event_duration) or 0.1,
            },
            "recovery": {
                "observed": bool(dynamic_result.get("checks", {}).get("recovered", False)),
                "window_s": _safe_float(arguments.recovery_window) or 0.5,
            },
            "required_channels": _required_channels(contract),
            "physical": {
                "verdict": physical_verdict,
                "event_checks": dynamic_result.get("checks", {}),
                "waveform_checks": physical_result.get("physical_checks", [])
                if isinstance(physical_result, Mapping)
                else [],
                "golden_checks": result.get("waveform", {}).get("golden_checks", [])
                if isinstance(result, Mapping) and isinstance(result.get("waveform", {}), Mapping)
                else [],
                "missing_channels": result.get("missing_channels", []) if isinstance(result, Mapping) else [],
            },
        },
        "golden": dict(golden),
        "explicit_exclusions": ["independent_golden", "final_accepted"],
        "failure": (
            {
                "stage": "input" if failure is not None else "evaluation",
                "code": (
                    failure.code
                    if isinstance(failure, BackendError)
                    else type(failure).__name__
                    if failure is not None
                    else "LCC_DYNAMIC_ACCEPTANCE_FAILED"
                ),
                "message": (
                    str(failure)[:1024]
                    if failure is not None
                    else "Dynamic evidence did not satisfy the acceptance contract."
                ),
            }
            if failure is not None or status == FAIL
            else None
        ),
        "evidence_source": "caller_supplied_diagnostic",
        "durable": False,
    }
    return _validate_diagnostic_report(report)


def _validate_diagnostic_report(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the historical caller-supplied diagnostic envelope.

    This intentionally does not call the durable licensed-runner validator.
    """
    report = dict(value)
    if report.get("evidence_source") != "caller_supplied_diagnostic" or report.get("durable") is not False:
        raise BackendError(
            "LCC_DYNAMIC_DIAGNOSTIC_INVALID",
            "Diagnostic reports must identify caller-supplied, non-durable evidence.",
            "hvdc",
            "dynamic_acceptance_cli",
        )
    return report


def run_exit_code(*, preflight_status: str, engineering_verdict: str) -> int:
    if preflight_status != PASS:
        return 2
    return 0 if engineering_verdict == PASS else 1


def _dynamic_source_paths(arguments: argparse.Namespace) -> dict[str, Path]:
    root = arguments.repository_root.resolve() / "pscad_mcp" / "assets" / "lcc" / "cigre_lcc_monopole_v1"
    return {
        "blueprint": root / "blueprint.json",
        "catalog": root / "catalog-pscad-4.6.2.json",
        "dynamic": root / "dynamic.json",
        "registry": root / "master-bindings-pscad-4.6.2.json",
        "manifest": root / "manifest.json",
        "companion": root / "library" / "cigre_lcc_v1.pslx",
        "master": arguments.master_path.resolve(),
        "compiler_configuration": arguments.compiler_configuration.resolve(),
        "compiler_executable": arguments.compiler_executable.resolve(),
    }


def _preflight(arguments: argparse.Namespace) -> dict[str, Any]:
    sources = _dynamic_source_paths(arguments)
    static: dict[str, Any] = {"status": FAIL}
    try:
        static = run_static_preflight(
            PreflightRequest(
                repository_root=arguments.repository_root.resolve(),
                workspace_root=arguments.workspace_root.resolve(),
                master_path=arguments.master_path.resolve(),
                compiler_configuration=arguments.compiler_configuration.resolve(),
                compiler_executable=arguments.compiler_executable.resolve(),
                expected_commit=arguments.commit,
                expected_branch=arguments.branch,
                read_only_sources=tuple(sources[name] for name in ("blueprint", "catalog", "dynamic", "registry", "manifest", "companion")),
            )
        )
        status = str(static.get("status", FAIL))
        snapshot = {
            name: {"path": str(path.absolute()), "sha256": _sha256_file(path)}
            for name, path in sources.items()
            if path.is_file() and not path.is_symlink()
        }
        if set(snapshot) != set(sources):
            status = FAIL
    except Exception as error:  # noqa: BLE001
        status = FAIL
        static = {"status": FAIL, "error": {"type": type(error).__name__, "message": str(error)[:1024]}}
        snapshot = {name: {"path": str(path.absolute()), "sha256": "0" * 64} for name, path in sources.items()}
        snapshot["error"] = {"type": type(error).__name__, "message": str(error)[:1024]}
    return {
        "status": status,
        "sha256": _canonical_hash(snapshot),
        "snapshot": snapshot,
        "static": static,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _service_factory(request: DynamicLccRunRequest) -> tuple[Any, Any]:
    backend = LegacyBackend(
        robust_executor,
        version="4.6.2",
        x64=True,
        definition_paths={"master": request.master_path},
        legacy_minimize=True,
        process_probe=list_pscad_processes,
        legacy_existing_policy=acceptance_launch_policy(),
    )
    service = PscadService(
        lambda: backend,
        executor=robust_executor,
        path_policy=PathPolicy(workspace_root=str(request.workspace_root)),
    )
    return service, LccBuilderService(service, workspace_root=request.workspace_root)


def _print_run_fields(report_path: Path, report: Mapping[str, Any] | None, *, engineering: str, status: str) -> None:
    print(f"FIXED_LCC_DYNAMIC_REPORT={report_path.absolute()}")
    print(f"FIXED_LCC_DYNAMIC_REPORT_SHA256={_sha256_file(report_path) if report_path.is_file() else ''}")
    print(f"FIXED_LCC_DYNAMIC_ENGINEERING_VERDICT={engineering}")
    print(f"FIXED_LCC_DYNAMIC_STATUS={status}")


def _write_failure_if_absent(
    report_path: Path,
    request: DynamicLccRunRequest,
    *,
    stage: str,
    error: BaseException,
) -> None:
    """Persist a failure only to a new, non-link report path."""
    if report_path.exists() or report_path.is_symlink():
        return
    parent = report_path.parent
    for candidate in (parent, *parent.parents):
        if _is_reparse_or_symlink(candidate):
            return
        if candidate == request.workspace_root:
            break
    fallback = build_dynamic_lcc_failure_report(request, stage=stage, error=error)
    _atomic_write(report_path, fallback)


def _preflight_failure_error(preflight: Mapping[str, Any]) -> BackendError:
    details = preflight.get("details")
    original = preflight.get("error")
    fragments = []
    if original is not None:
        fragments.append(f"error={json.dumps(original, ensure_ascii=True, sort_keys=True)}")
    if details is not None:
        fragments.append(f"details={json.dumps(details, ensure_ascii=True, sort_keys=True)}")
    static = preflight.get("static")
    if static is not None:
        fragments.append(f"static={json.dumps(static, ensure_ascii=True, sort_keys=True)}")
    message = "Dynamic LCC static preflight failed."
    if fragments:
        message += " " + "; ".join(fragments)
    return BackendError(
        "LCC_DYNAMIC_PREFLIGHT_FAILED",
        message,
        "hvdc",
        "dynamic_acceptance_cli",
        {"preflight": dict(preflight)},
    )


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        return bool(getattr(path.stat(), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def _report_parent_is_safe(report_path: Path, workspace_root: Path) -> bool:
    try:
        report_path.relative_to(workspace_root)
    except ValueError:
        return False
    for parent in (report_path.parent, *report_path.parent.parents):
        if _is_reparse_or_symlink(parent):
            return False
        if parent == workspace_root:
            break
    return True


def main(
    argv: Sequence[str] | None = None,
    *,
    run_action: Any = run_fixed_lcc_dynamic_acceptance,
    service_factory: Any = _service_factory,
    preflight_action: Any = _preflight,
) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.action == "run":
        repository_root = arguments.repository_root.absolute()
        workspace_root = arguments.workspace_root.absolute()
        workspace_root.mkdir(parents=True, exist_ok=True)
        report_path = arguments.report.absolute()
        if not _report_parent_is_safe(report_path, workspace_root):
            error = ValueError("--report must be inside --workspace-root and use regular parent directories")
            raise SystemExit("--report must be inside --workspace-root") from error
        try:
            preflight = preflight_action(arguments)
        except Exception:  # noqa: BLE001 - preflight failures map to exit 2
            preflight = {"status": FAIL, "sha256": "0" * 64, "snapshot": {}}
        request = DynamicLccRunRequest(
            repository_root=repository_root,
            workspace_root=workspace_root,
            master_path=arguments.master_path.resolve(),
            compiler_configuration=arguments.compiler_configuration.resolve(),
            compiler_executable=arguments.compiler_executable.resolve(),
            report_path=report_path,
            commit=arguments.commit,
            branch=arguments.branch,
            project_name=arguments.project_name,
            simulation_duration_s=arguments.simulation_duration,
            output_step_s=arguments.output_step,
            preflight=preflight,
        )
        if preflight.get("status") != PASS:
            try:
                _write_failure_if_absent(
                    report_path,
                    request,
                    stage="setup",
                    error=_preflight_failure_error(preflight),
                )
            except Exception as persistence_error:  # noqa: BLE001 - preserve exit 2 even if persistence fails
                _ = persistence_error
            _print_run_fields(report_path, None, engineering=FAIL, status=FAIL)
            return run_exit_code(preflight_status=str(preflight.get("status")), engineering_verdict=FAIL)
        try:
            service, builder = service_factory(request)
            result_value = run_action(request, service=service, builder=builder)
            result = asyncio.run(result_value) if hasattr(result_value, "__await__") else result_value
            if (not isinstance(result, Mapping) or "engineering_verdict" not in result) and report_path.is_file():
                result = _load_json(report_path)
            if not isinstance(result, Mapping):
                raise BackendError("LCC_DYNAMIC_REPORT_INVALID", "Runner did not return a report.", "hvdc", "dynamic_acceptance_cli")
            validated = validate_dynamic_lcc_acceptance_report(result)
            engineering = str(validated.get("engineering_verdict", FAIL))
            status = str(validated.get("status", FAIL))
            _print_run_fields(report_path, validated, engineering=engineering, status=status)
            return run_exit_code(preflight_status=str(preflight.get("status")), engineering_verdict=engineering)
        except Exception as error:  # noqa: BLE001 - CLI lifecycle failures are exit 1
            persisted = None
            if report_path.is_file():
                try:
                    persisted = validate_dynamic_lcc_acceptance_report(_load_json(report_path))
                except Exception:  # noqa: BLE001 - replace invalid/partial reports
                    persisted = None
            if persisted is None:
                try:
                    _write_failure_if_absent(report_path, request, stage="setup", error=error)
                except Exception as persistence_error:  # noqa: BLE001 - report persistence must not mask exit 1
                    _ = persistence_error
            _print_run_fields(report_path, persisted, engineering=FAIL, status=FAIL)
            return 1
    if arguments.action != "evaluate":
        raise SystemExit(f"Unsupported action: {arguments.action}")
    result: dict[str, Any] | None = None
    failure: BaseException | None = None
    contract: Mapping[str, Any] = {}
    golden: Mapping[str, Any] = {}
    try:
        samples = _load_json(arguments.samples)
        loaded_golden = _load_json(arguments.golden)
        loaded_contract = _load_json(arguments.contract)
        if not isinstance(loaded_golden, Mapping) or not isinstance(loaded_contract, Mapping):
            raise BackendError("LCC_DYNAMIC_INPUT_INVALID", "golden and contract must be objects.", "hvdc", "evaluate_fixed_lcc_dynamic")
        golden = loaded_golden
        contract = loaded_contract
        result = evaluate_fixed_lcc_dynamic_samples(samples, golden, contract)
        status = str(result["verdict"])
    except BaseException as error:  # noqa: BLE001 - persist every input failure
        failure = error
        status = FAIL
    report = _report(
        arguments,
        status=status,
        contract=contract,
        golden=golden,
        result=result,
        failure=failure,
    )
    _atomic_write(arguments.report, report)
    print(f"FIXED_LCC_DYNAMIC_ACCEPTANCE={status}")
    print(f"FIXED_LCC_DYNAMIC_REPORT={arguments.report.resolve()}")
    return 0 if status == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_exit_code"]
