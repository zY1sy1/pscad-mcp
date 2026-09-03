"""Dynamic disturbance and recovery evidence for the fixed LCC builder."""

from __future__ import annotations

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
    if report["kind"] != "licensed_simulation":
        raise _invalid("kind", "Dynamic evidence must be licensed simulation.")
    if report["capability_state"] != "simulated":
        raise _invalid("capability_state", "Capability state is invalid.")
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

    preflight = _mapping(report["preflight"], "preflight")
    if not isinstance(preflight.get("snapshot"), Mapping):
        raise _invalid("preflight", "Preflight snapshot must be an object.")
    if report["status"] != FAIL and preflight.get("status") != PASS:
        raise _invalid("preflight", "Dynamic report requires PASS preflight evidence.")
    _text(preflight.get("sha256"), "preflight.sha256")

    sources = _mapping(report["sources"], "sources")
    if set(sources) != _SOURCE_KEYS:
        raise _invalid("sources", "sources fields are not exact.")
    for name, item in sources.items():
        source = _exact(item, f"sources.{name}", {"path", "before", "after"})
        _text(source["path"], f"sources.{name}.path")
        _text(source["before"], f"sources.{name}.before")
        _text(source["after"], f"sources.{name}.after")
        if not all(_HASH.fullmatch(source[key]) for key in ("before", "after")):
            raise _invalid(f"sources.{name}", "source hashes must be SHA-256 values.")
        if report["status"] != FAIL and source["before"] != source["after"]:
            raise _invalid(f"sources.{name}", "source changed during the run.")

    build = _mapping(report["build"], "build")
    if report["status"] != FAIL and build.get("terminal_state") != "published":
        raise _invalid("build.terminal_state", "Dynamic report requires a published build.")
    history = build.get("history")
    if report["status"] != FAIL and (not isinstance(history, Sequence) or isinstance(history, (str, bytes)) or "dynamic_engineering_passed" not in history):
        raise _invalid("build.history", "Build history lacks dynamic engineering pass.")

    artifacts = _mapping(report["artifacts"], "artifacts")
    normalized = artifacts.get("normalized_samples")
    if report["status"] != FAIL and (not isinstance(normalized, Mapping) or not isinstance(normalized.get("sha256"), str)):
        raise _invalid("artifacts.normalized_samples", "Normalized samples must be hashed.")
    parts = artifacts.get("output_parts")
    metadata = artifacts.get("output_metadata")
    if report["status"] != FAIL and (not isinstance(parts, Sequence) or isinstance(parts, (str, bytes)) or not parts):
        raise _invalid("artifacts.output_parts", "At least one OUT part is required.")
    if report["status"] != FAIL and (not isinstance(metadata, Sequence) or isinstance(metadata, (str, bytes)) or not metadata):
        raise _invalid("artifacts.output_metadata", "At least one INF/INFX metadata part is required.")
    artifact_items = [*parts, *metadata] + ([normalized] if normalized is not None else [])
    for index, item in enumerate(artifact_items):
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
            raise _invalid(f"artifacts[{index}]", "Artifact path and hash are required.")
        if _HASH.fullmatch(item["sha256"]) is None:
            raise _invalid(f"artifacts[{index}].sha256", "Artifact hash must be SHA-256.")
        suffix = Path(item["path"]).suffix.casefold()
        if item in parts and suffix not in {".out", ".psout"}:
            raise _invalid("artifacts.output_parts", "OUT parts must have an OUT suffix.")
        if item in metadata and suffix not in {".inf", ".infx"}:
            raise _invalid("artifacts.output_metadata", "Metadata must be INF or INFX.")

    dynamic = _mapping(report["dynamic"], "dynamic")
    if dynamic.get("evidence_source") != "raw_pscad_output":
        raise _invalid("dynamic.evidence_source", "Runner reports require raw PSCAD output evidence.")
    physical = _mapping(report["physical"], "physical")
    if physical.get("verdict") not in _ALLOWED_VERDICTS:
        raise _invalid("physical.verdict", "Physical verdict is invalid.")
    golden = _mapping(report["golden"], "golden")
    if not isinstance(golden.get("reviewed"), bool) or not isinstance(golden.get("source"), str):
        raise _invalid("golden", "Golden review metadata is required.")
    expected_engineering = combine_dynamic_verdicts(dynamic.get("engineering_verdict", report["engineering_verdict"]), physical["verdict"])
    if report["engineering_verdict"] != expected_engineering:
        raise _invalid("engineering_verdict", "Engineering verdict must combine dynamic and physical verdicts.")
    if report["status"] != combine_dynamic_verdicts(report["engineering_verdict"], report["golden_verdict"]):
        raise _invalid("status", "Status must combine engineering and golden verdicts.")
    runtime = _mapping(report["runtime"], "runtime")
    remaining = runtime.get("remaining_processes")
    if not isinstance(remaining, Sequence) or isinstance(remaining, (str, bytes, bytearray)):
        raise _invalid("runtime.remaining_processes", "Remaining processes must be an array.")
    if report["status"] != FAIL and remaining:
        raise _invalid("runtime.remaining_processes", "Runner-owned processes remain.")
    exclusions = _channels(report["explicit_exclusions"], "explicit_exclusions")
    if (
        (not golden["reviewed"] or "placeholder" in golden["source"].casefold())
        and ("independent_golden" not in exclusions or "final_accepted" not in exclusions)
    ):
        raise _invalid("explicit_exclusions", "Independent golden and final accepted exclusions are required.")
    if report["status"] == FAIL and report["failure"] is None:
        raise _invalid("failure", "FAIL reports must include failure details.")
    if report["failure"] is not None and not isinstance(report["failure"], Mapping):
        raise _invalid("failure", "failure must be null or an object.")
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
