"""Dynamic disturbance and recovery evidence for the fixed LCC builder."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from .acceptance import evaluate_acceptance, evaluate_commutation_fault

PASS = "PASS"
FAIL = "FAIL"
INCOMPLETE = "INCOMPLETE_ANALYSIS"
_REPORT_KEYS = {
    "schema_version",
    "run_id",
    "scope",
    "builder_path",
    "kind",
    "capability_state",
    "commit",
    "generated_at_utc",
    "status",
    "repository",
    "dynamic",
    "golden",
    "explicit_exclusions",
    "failure",
}
_DYNAMIC_KEYS = {"event", "recovery", "required_channels", "physical"}
_EVENT_KEYS = {"kind", "time_s", "duration_s"}
_RECOVERY_KEYS = {"observed", "window_s"}
_REPOSITORY_KEYS = {"branch", "commit", "clean"}
_ALLOWED_STATUS = {PASS, FAIL, INCOMPLETE}
_ALLOWED_CAPABILITIES = {"simulated", "accepted"}


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
    """Validate the durable WP1C report envelope and dynamic evidence."""

    report = _exact(value, "report", _REPORT_KEYS)
    if report["schema_version"] != 1:
        raise _invalid("schema_version", "Unsupported dynamic report schema.")
    _text(report["run_id"], "run_id")
    if report["scope"] != "lcc.fixed_autonomous" or report["builder_path"] != "lcc.fixed_autonomous":
        raise _invalid("scope", "Dynamic evidence must target fixed autonomous LCC.")
    if report["kind"] != "licensed_acceptance":
        raise _invalid("kind", "Dynamic evidence must be licensed acceptance.")
    if report["capability_state"] not in _ALLOWED_CAPABILITIES:
        raise _invalid("capability_state", "Capability state is invalid.")
    _sha_commit(report["commit"], "commit")
    _text(report["generated_at_utc"], "generated_at_utc")
    if report["status"] not in _ALLOWED_STATUS:
        raise _invalid("status", "Dynamic report status is invalid.")

    repository = _exact(report["repository"], "repository", _REPOSITORY_KEYS)
    _text(repository["branch"], "repository.branch")
    _sha_commit(repository["commit"], "repository.commit")
    if repository["commit"] != report["commit"] or repository["clean"] is not True:
        raise _invalid("repository", "Repository identity is not clean and commit-bound.")

    dynamic = _exact(report["dynamic"], "dynamic", _DYNAMIC_KEYS)
    event = _exact(dynamic["event"], "dynamic.event", _EVENT_KEYS)
    _text(event["kind"], "dynamic.event.kind")
    event_time = _finite(event["time_s"], "dynamic.event.time_s")
    event_duration = _finite(event["duration_s"], "dynamic.event.duration_s")
    if event_time < 0 or event_duration <= 0:
        raise _invalid("dynamic.event", "Event time must be non-negative and duration positive.")
    recovery = _exact(dynamic["recovery"], "dynamic.recovery", _RECOVERY_KEYS)
    if not isinstance(recovery["observed"], bool):
        raise _invalid("dynamic.recovery.observed", "Recovery observed must be boolean.")
    if _finite(recovery["window_s"], "dynamic.recovery.window_s") <= 0:
        raise _invalid("dynamic.recovery.window_s", "Recovery window must be positive.")
    _channels(dynamic["required_channels"], "dynamic.required_channels")
    physical = _mapping(dynamic["physical"], "dynamic.physical")
    if physical.get("verdict") not in {PASS, FAIL, INCOMPLETE}:
        raise _invalid("dynamic.physical.verdict", "Physical verdict is invalid.")
    golden = _mapping(report["golden"], "golden")
    if report["status"] == PASS:
        source = golden.get("source")
        if (
            not isinstance(source, str)
            or "placeholder" in source.casefold()
            or golden.get("reviewed") is not True
        ):
            raise _invalid("golden", "PASS requires an independently reviewed golden source.")
        if physical["verdict"] != PASS:
            raise _invalid("dynamic.physical.verdict", "PASS requires physical evidence to pass.")
    exclusions = _channels(report["explicit_exclusions"], "explicit_exclusions")
    if "final_accepted" not in exclusions:
        raise _invalid("explicit_exclusions", "Final accepted exclusion is required before WP6.")
    if report["status"] == FAIL and report["failure"] is None:
        raise _invalid("failure", "FAIL reports must include failure details.")
    if report["failure"] is not None and not isinstance(report["failure"], Mapping):
        raise _invalid("failure", "failure must be null or an object.")
    return report


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
    "DynamicLccAcceptanceRequest",
    "evaluate_fixed_lcc_dynamic_samples",
    "validate_dynamic_lcc_acceptance_report",
]
