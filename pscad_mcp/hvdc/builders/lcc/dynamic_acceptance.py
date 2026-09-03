"""Dynamic disturbance and recovery evidence for the fixed LCC builder."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from .acceptance import evaluate_acceptance, evaluate_commutation_fault

PASS = "PASS"
FAIL = "FAIL"
INCOMPLETE = "INCOMPLETE_ANALYSIS"
REPORT_KEYS = {
    "schema_version",
    "run_id",
    "scope",
    "builder_path",
    "kind",
    "capability_state",
    "commit",
    "generated_at_utc",
    "engineering_verdict",
    "golden_verdict",
    "status",
    "repository",
    "preflight",
    "sources",
    "build",
    "artifacts",
    "dynamic",
    "physical",
    "golden",
    "runtime",
    "explicit_exclusions",
    "failure",
}
_REPOSITORY_KEYS = {"branch", "commit", "clean"}
_ALLOWED_STATUS = {PASS, FAIL, INCOMPLETE}
_ALLOWED_VERDICTS = {PASS, FAIL, INCOMPLETE}
_SOURCE_KEYS = {
    "blueprint", "catalog", "dynamic", "registry", "manifest", "companion",
    "master", "compiler_configuration", "compiler_executable",
}
_REPORT_KEYS = REPORT_KEYS
_HASH = re.compile(r"^[0-9a-f]{64}$")
_PREFLIGHT_KEYS = {"status", "sha256", "snapshot"}
_BUILD_KEYS = {"project_name", "workspace", "build_id", "plan_hash", "verification_profile", "history", "terminal_state"}
_ARTIFACT_KEYS = {"project", "library", "selected_output", "output_parts", "output_metadata", "normalized_samples"}
_DYNAMIC_KEYS = {"evidence_source", "engineering_verdict", "checks"}
_PHYSICAL_KEYS = {"verdict", "checks"}
_GOLDEN_KEYS = {"source", "reviewed"}
_RUNTIME_KEYS = {"remaining_processes", "managed_pid", "backend", "version", "x64", "licensed", "quit_error"}
_FAILURE_KEYS = {"stage", "code", "message"}


def _invalid(field: str, message: str, **details: Any) -> BackendError:
    return BackendError(
        "LCC_DYNAMIC_REPORT_INVALID",
        message,
        "hvdc",
        "validate_dynamic_lcc_acceptance_report",
        {"field": field, **details},
    )


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(field, f"{field} must be an object.")
    return dict(value)


def _exact(value: Any, field: str, keys: set[str]) -> dict[str, Any]:
    item = _mapping(value, field)
    if set(item) != keys:
        raise _invalid(field, f"{field} fields are not exact.")
    return item


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(field, f"{field} must be non-empty text.")
    return value.strip()


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(field, f"{field} must be a finite number.")
    number = float(value)
    if not math.isfinite(number):
        raise _invalid(field, f"{field} must be a finite number.")
    return number


def _sha_commit(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise _invalid(field, f"{field} must be a lowercase commit SHA.")
    return text


def _sha256(value: Any, field: str) -> str:
    text = _text(value, field)
    if _HASH.fullmatch(text) is None:
        raise _invalid(field, f"{field} must be a lowercase SHA-256 hash.")
    return text


def _artifact(value: Any, field: str, *, required: bool) -> dict[str, Any] | None:
    if value is None:
        if required:
            raise _invalid(field, f"{field} is required.")
        return None
    item = _exact(value, field, {"path", "sha256"})
    _text(item["path"], f"{field}.path")
    _sha256(item["sha256"], f"{field}.sha256")
    return item


def _path_owned(path: Path, root: Path) -> bool:
    try:
        candidate = path.absolute()
        root_abs = root.absolute()
        candidate.relative_to(root_abs)
        for parent in (candidate, *candidate.parents):
            if parent == root_abs:
                break
            if parent.exists() and (parent.is_symlink() or bool(getattr(parent.stat(), "st_file_attributes", 0) & 0x400)):
                return False
        candidate.resolve().relative_to(root_abs.resolve())
        return True
    except (OSError, ValueError):
        return False


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _dynamic_verdict(dynamic: Mapping[str, Any]) -> str:
    checks = dynamic.get("checks")
    if not isinstance(checks, Mapping) or not checks:
        return INCOMPLETE
    if set(checks) != {"disturbance", "failure_indication", "bounded_dc_response", "recovery"}:
        raise _invalid("dynamic.checks", "Dynamic checks must contain the four canonical checks.")
    outcomes = [item.get("outcome") for item in checks.values() if isinstance(item, Mapping)]
    if len(outcomes) != len(checks) or any(item not in _ALLOWED_VERDICTS for item in outcomes):
        raise _invalid("dynamic.checks", "Dynamic checks must contain verdict outcomes.")
    if FAIL in outcomes:
        return FAIL
    if INCOMPLETE in outcomes:
        return INCOMPLETE
    return PASS


def _validate_dynamic_checks(checks: Mapping[str, Any]) -> None:
    if not checks:
        return
    required = {"outcome", "selectors", "units", "window_s", "sample_count", "metrics"}
    for name, value in checks.items():
        item = _exact(value, f"dynamic.checks.{name}", required)
        if item["outcome"] not in _ALLOWED_VERDICTS:
            raise _invalid(f"dynamic.checks.{name}.outcome", "Invalid dynamic check outcome.")
        if not isinstance(item["selectors"], Sequence) or isinstance(item["selectors"], (str, bytes, bytearray)) or not item["selectors"] or any(not isinstance(v, str) or not v for v in item["selectors"]):
            raise _invalid(f"dynamic.checks.{name}.selectors", "Selectors must be a non-empty string array.")
        if not isinstance(item["units"], Mapping) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in item["units"].items()):
            raise _invalid(f"dynamic.checks.{name}.units", "Units must be a string mapping.")
        if not isinstance(item["window_s"], Sequence) or isinstance(item["window_s"], (str, bytes, bytearray)) or len(item["window_s"]) != 2:
            raise _invalid(f"dynamic.checks.{name}.window_s", "window_s must contain two numbers.")
        _finite(item["window_s"][0], f"dynamic.checks.{name}.window_s[0]")
        _finite(item["window_s"][1], f"dynamic.checks.{name}.window_s[1]")
        if isinstance(item["sample_count"], bool) or not isinstance(item["sample_count"], int) or item["sample_count"] < 0:
            raise _invalid(f"dynamic.checks.{name}.sample_count", "sample_count must be a non-negative integer.")
        if not isinstance(item["metrics"], Mapping):
            raise _invalid(f"dynamic.checks.{name}.metrics", "metrics must be an object.")


def _channels(value: Any, field: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _invalid(field, f"{field} must be an array.")
    result = [_text(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if not result or len(set(result)) != len(result):
        raise _invalid(field, f"{field} must contain unique channel names.")
    return result


def _required_channels_from_contract(contract: Mapping[str, Any]) -> list[str]:
    raw = contract.get("required_channels")
    if raw is not None:
        return _channels(raw, "contract.required_channels")
    golden = contract.get("golden")
    declarations = golden.get("channels", ()) if isinstance(golden, Mapping) else ()
    if not isinstance(declarations, Sequence) or isinstance(declarations, (str, bytes, bytearray)):
        raise _invalid("contract.golden.channels", "golden channels must be an array.")
    names = [
        item.get("name")
        for item in declarations
        if isinstance(item, Mapping) and item.get("required", True)
    ]
    return _channels(names, "contract.golden.channels") if names else []


@dataclass(frozen=True)
class DynamicLccAcceptanceRequest:
    repository_root: Path
    workspace_root: Path
    master_path: Path
    compiler_configuration: Path
    compiler_executable: Path
    report_path: Path
    commit: str
    branch: str
    project_name: str
    simulation_duration_s: float
    output_step_s: float
    disturbance_time_s: float
    disturbance_duration_s: float


def validate_dynamic_lcc_acceptance_report(value: Any) -> dict[str, Any]:
    """Validate the durable WP1C report envelope and layered verdicts."""
    report = _exact(value, "report", REPORT_KEYS)
    if report["schema_version"] != 1:
        raise _invalid("schema_version", "Unsupported dynamic report schema.")
    _text(report["run_id"], "run_id")
    if report["scope"] != "lcc.fixed_autonomous" or report["builder_path"] != "lcc.fixed_autonomous":
        raise _invalid("scope", "Dynamic evidence must target fixed autonomous LCC.")
    if report["kind"] != "licensed_simulation" or report["capability_state"] != "simulated":
        raise _invalid("kind", "Dynamic evidence kind/capability is invalid.")
    _sha_commit(report["commit"], "commit")
    _text(report["generated_at_utc"], "generated_at_utc")
    for field in ("engineering_verdict", "golden_verdict", "status"):
        if report[field] not in _ALLOWED_VERDICTS:
            raise _invalid(field, f"{field} is invalid.")
    repository = _exact(report["repository"], "repository", _REPOSITORY_KEYS)
    _text(repository["branch"], "repository.branch")
    _sha_commit(repository["commit"], "repository.commit")
    if repository["commit"] != report["commit"] or repository["clean"] is not True:
        raise _invalid("repository", "Repository identity is not clean and commit-bound.")

    preflight = _exact(report["preflight"], "preflight", _PREFLIGHT_KEYS)
    if preflight["status"] not in _ALLOWED_VERDICTS:
        raise _invalid("preflight.status", "Preflight status is invalid.")
    _sha256(preflight["sha256"], "preflight.sha256")
    if not isinstance(preflight["snapshot"], Mapping):
        raise _invalid("preflight.snapshot", "Preflight snapshot must be an object.")
    sources = _mapping(report["sources"], "sources")
    if set(sources) != _SOURCE_KEYS:
        raise _invalid("sources", "sources fields are not exact.")
    for name, item in sources.items():
        source = _exact(item, f"sources.{name}", {"path", "before", "after"})
        _text(source["path"], f"sources.{name}.path")
        _sha256(source["before"], f"sources.{name}.before")
        _sha256(source["after"], f"sources.{name}.after")
        if report["status"] != FAIL and source["before"] != source["after"]:
            raise _invalid(f"sources.{name}", "source changed during the run.")
    for name, item in preflight["snapshot"].items():
        if name not in _SOURCE_KEYS:
            raise _invalid("preflight.snapshot", "Unknown source snapshot key.")
        snap = _exact(item, f"preflight.snapshot.{name}", {"path", "sha256"})
        if snap["path"] != sources[name]["path"] or snap["sha256"] != sources[name]["before"]:
            raise _invalid(f"preflight.snapshot.{name}", "Snapshot is not bound to source evidence.")
    if set(preflight["snapshot"]) != _SOURCE_KEYS:
        raise _invalid("preflight.snapshot", "Snapshot must cover every source.")
    if preflight["sha256"] != _canonical_hash(preflight["snapshot"]):
        raise _invalid("preflight.sha256", "Preflight hash does not match canonical snapshot.")

    build = _exact(report["build"], "build", _BUILD_KEYS)
    for key in ("project_name", "workspace", "verification_profile", "terminal_state"):
        _text(build[key], f"build.{key}")
    if build["build_id"] is not None:
        _text(build["build_id"], "build.build_id")
    if build["plan_hash"] is not None:
        _sha256(build["plan_hash"], "build.plan_hash")
    if not isinstance(build["history"], Sequence) or isinstance(build["history"], (str, bytes, bytearray)) or any(not isinstance(v, str) for v in build["history"]):
        raise _invalid("build.history", "Build history must be an array of strings.")
    if report["status"] != FAIL and (build["terminal_state"] != "published" or "dynamic_engineering_passed" not in build["history"]):
        raise _invalid("build", "Dynamic report requires a published build with dynamic evidence.")

    artifacts = _exact(report["artifacts"], "artifacts", _ARTIFACT_KEYS)
    _artifact(artifacts["project"], "artifacts.project", required=report["status"] != FAIL)
    _artifact(artifacts["library"], "artifacts.library", required=report["status"] != FAIL)
    _artifact(artifacts["selected_output"], "artifacts.selected_output", required=report["status"] != FAIL)
    _artifact(artifacts["normalized_samples"], "artifacts.normalized_samples", required=report["status"] != FAIL)
    parts = artifacts["output_parts"]
    metadata = artifacts["output_metadata"]
    if not isinstance(parts, Sequence) or isinstance(parts, (str, bytes, bytearray)) or (report["status"] != FAIL and not parts):
        raise _invalid("artifacts.output_parts", "Output parts must be an array.")
    if not isinstance(metadata, Sequence) or isinstance(metadata, (str, bytes, bytearray)) or (report["status"] != FAIL and not metadata):
        raise _invalid("artifacts.output_metadata", "Output metadata must be an array.")
    for index, item in enumerate(parts):
        record = _artifact(item, f"artifacts.output_parts[{index}]", required=True)
        if Path(record["path"]).suffix.casefold() not in {".out", ".psout"}:
            raise _invalid("artifacts.output_parts", "OUT parts must have an OUT suffix.")
    for index, item in enumerate(metadata):
        record = _artifact(item, f"artifacts.output_metadata[{index}]", required=True)
        if Path(record["path"]).suffix.casefold() not in {".inf", ".infx"}:
            raise _invalid("artifacts.output_metadata", "Metadata must be INF or INFX.")
    workspace = Path(build["workspace"]).absolute()
    for name in ("project", "library", "selected_output", "normalized_samples"):
        artifact = artifacts[name]
        if artifact is not None and not _path_owned(Path(artifact["path"]), workspace):
            raise _invalid(f"artifacts.{name}.path", "Artifact path escaped the build workspace.")
    for group_name, group in (("output_parts", parts), ("output_metadata", metadata)):
        for index, artifact in enumerate(group):
            if not _path_owned(Path(artifact["path"]), workspace):
                raise _invalid(f"artifacts.{group_name}[{index}].path", "Artifact path escaped the build workspace.")

    dynamic = _exact(report["dynamic"], "dynamic", _DYNAMIC_KEYS)
    if dynamic["evidence_source"] != "raw_pscad_output" or dynamic["engineering_verdict"] not in _ALLOWED_VERDICTS or not isinstance(dynamic["checks"], Mapping):
        raise _invalid("dynamic", "Dynamic evidence must contain raw checks.")
    dynamic_verdict = _dynamic_verdict(dynamic)
    _validate_dynamic_checks(dynamic["checks"])
    if dynamic["engineering_verdict"] != dynamic_verdict and not (report["status"] == FAIL and not dynamic["checks"]):
        raise _invalid("dynamic.engineering_verdict", "Dynamic verdict must match its checks.")
    if report["status"] == FAIL and not dynamic["checks"]:
        dynamic_verdict = dynamic["engineering_verdict"]
    physical = _exact(report["physical"], "physical", _PHYSICAL_KEYS)
    if physical["verdict"] not in _ALLOWED_VERDICTS or not isinstance(physical["checks"], Sequence) or isinstance(physical["checks"], (str, bytes, bytearray)):
        raise _invalid("physical", "Physical evidence is invalid.")
    for index, check in enumerate(physical["checks"]):
        if not isinstance(check, Mapping):
            raise _invalid(f"physical.checks[{index}]", "Physical checks must be objects.")
        required_keys = {"name", "kind", "required", "status", "outcome"}
        allowed_keys = required_keys | {"observed", "expected", "comparison_policy"}
        if not required_keys.issubset(check) or not set(check).issubset(allowed_keys):
            raise _invalid(f"physical.checks[{index}]", "Physical check fields are not strict.")
        _text(check["name"], f"physical.checks[{index}].name")
        _text(check["kind"], f"physical.checks[{index}].kind")
        _text(check["status"], f"physical.checks[{index}].status")
        if not isinstance(check["required"], bool):
            raise _invalid(f"physical.checks[{index}].required", "required must be boolean.")
        outcome = check.get("outcome", check.get("verdict"))
        if outcome not in _ALLOWED_VERDICTS:
            raise _invalid(f"physical.checks[{index}]", "Physical check outcome is invalid.")
    physical_outcomes = [check.get("outcome", check.get("verdict")) for check in physical["checks"]]
    if physical_outcomes:
        expected_physical = FAIL if FAIL in physical_outcomes else INCOMPLETE if INCOMPLETE in physical_outcomes else PASS
        if physical["verdict"] != expected_physical:
            raise _invalid("physical.verdict", "Physical verdict must match check outcomes.")
    golden = _exact(report["golden"], "golden", _GOLDEN_KEYS)
    if not isinstance(golden["reviewed"], bool):
        raise _invalid("golden", "Golden review metadata is required.")
    _text(golden["source"], "golden.source")
    if report["golden_verdict"] == PASS and (not golden["reviewed"] or "placeholder" in golden["source"].casefold()):
        raise _invalid("golden_verdict", "PASS requires a reviewed non-placeholder golden source.")
    expected_engineering = combine_dynamic_verdicts(dynamic_verdict, physical["verdict"])
    if report["engineering_verdict"] != expected_engineering:
        raise _invalid("engineering_verdict", "Engineering verdict must combine dynamic and physical verdicts.")
    if report["status"] != combine_dynamic_verdicts(report["engineering_verdict"], report["golden_verdict"]):
        raise _invalid("status", "Status must combine engineering and golden verdicts.")
    runtime = _exact(report["runtime"], "runtime", _RUNTIME_KEYS)
    if not isinstance(runtime["remaining_processes"], Sequence) or isinstance(runtime["remaining_processes"], (str, bytes, bytearray)):
        raise _invalid("runtime.remaining_processes", "Remaining processes must be an array.")
    if runtime["managed_pid"] is not None and (isinstance(runtime["managed_pid"], bool) or not isinstance(runtime["managed_pid"], int)):
        raise _invalid("runtime.managed_pid", "managed_pid must be an integer or null.")
    for key in ("backend", "version"):
        if runtime[key] is not None and not isinstance(runtime[key], str):
            raise _invalid(f"runtime.{key}", f"{key} must be text or null.")
    for key in ("x64", "licensed"):
        if runtime[key] is not None and not isinstance(runtime[key], bool):
            raise _invalid(f"runtime.{key}", f"{key} must be boolean or null.")
    if runtime["quit_error"] is not None and not isinstance(runtime["quit_error"], str):
        raise _invalid("runtime.quit_error", "quit_error must be text or null.")
    if report["status"] != FAIL and runtime["remaining_processes"]:
        raise _invalid("runtime.remaining_processes", "Runner-owned processes remain.")
    exclusions = _channels(report["explicit_exclusions"], "explicit_exclusions")
    if (not golden["reviewed"] or "placeholder" in golden["source"].casefold()) and ("independent_golden" not in exclusions or "final_accepted" not in exclusions):
        raise _invalid("explicit_exclusions", "Independent golden and final accepted exclusions are required.")
    failure = report["failure"]
    if report["status"] == FAIL and failure is None:
        raise _invalid("failure", "FAIL reports must include failure details.")
    if failure is not None:
        failure = _exact(failure, "failure", _FAILURE_KEYS)
        for key in _FAILURE_KEYS:
            _text(failure[key], f"failure.{key}")
    if report["status"] != FAIL and failure is not None:
        raise _invalid("failure", "Non-FAIL reports must have null failure.")
    return report


def combine_dynamic_verdicts(engineering_verdict: str, golden_verdict: str) -> str:
    if "FAIL" in {engineering_verdict, golden_verdict}:
        return FAIL
    if {engineering_verdict, golden_verdict} == {PASS}:
        return PASS
    return INCOMPLETE


def _channel_names(samples: Mapping[str, Any]) -> set[str]:
    channels = samples.get("channels", samples)
    if not isinstance(channels, Mapping):
        return set()
    return {str(name) for name in channels}


def evaluate_fixed_lcc_dynamic_samples(
    samples: Mapping[str, Any],
    golden: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate event/recovery evidence plus the shared waveform contract."""

    if not isinstance(samples, Mapping) or not isinstance(contract, Mapping):
        raise _invalid("samples", "samples and contract must be objects.")
    channels = samples.get("channels", samples)
    if not isinstance(channels, Mapping):
        raise _invalid("samples.channels", "samples.channels must be an object.")
    required = _required_channels_from_contract(contract)
    missing = [name for name in required if name not in channels]
    dynamic_evidence = samples.get("dynamic", {})
    if not isinstance(dynamic_evidence, Mapping):
        raise _invalid("samples.dynamic", "samples.dynamic must be an object.")
    dynamic_result = evaluate_commutation_fault(dynamic_evidence)
    physical_contract = dict(contract)
    physical_contract["golden"] = {"channels": []}
    physical_contract["checks"] = [
        check
        for check in contract.get("checks", ())
        if isinstance(check, Mapping) and check.get("kind") == "physical"
    ]
    physical_result = evaluate_acceptance(channels, {}, physical_contract)
    waveform_result = evaluate_acceptance(channels, golden, contract)
    result = {
        "verdict": waveform_result["verdict"],
        "dynamic": dynamic_result,
        "physical": physical_result,
        "waveform": waveform_result,
        "missing_channels": missing,
        "evidence_source": "caller_supplied_diagnostic",
        "durable": False,
    }
    if (
        missing
        or dynamic_result["verdict"] == FAIL
        or physical_result["verdict"] == FAIL
        or waveform_result["verdict"] == FAIL
    ):
        result["verdict"] = FAIL
    elif (
        physical_result["verdict"] == INCOMPLETE
        or waveform_result["verdict"] == INCOMPLETE
        or not required
    ):
        result["verdict"] = INCOMPLETE
    return result


__all__ = [
    "REPORT_KEYS",
    "DynamicLccAcceptanceRequest",
    "combine_dynamic_verdicts",
    "evaluate_fixed_lcc_dynamic_samples",
    "validate_dynamic_lcc_acceptance_report",
]
