from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
import re
import tempfile
from typing import Any


_ALLOWED_STATUSES = frozenset({"PASS", "FAIL", "INCOMPLETE"})
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_CODES = frozenset(
    {
        "LABEL_CONFLICT",
        "PORT_DIMENSION_MISMATCH",
        "PORT_KIND_MISMATCH",
        "REQUIRED_PORT_UNCONNECTED",
        "WIRE_DANGLING_ENDPOINT",
    }
)
_REQUIRED_PHASES = frozenset(
    {
        "live_capture",
        "file_parse",
        "reconcile",
        "connectivity",
        "generic_rules",
    }
)


def validate_acceptance_report(value: Any) -> dict[str, Any]:
    """Return a JSON-safe report after enforcing the Phase 1 PASS gate."""
    report = _json_projection(value)
    _validate_base_report(report)
    if report["status"] == "PASS":
        _validate_pass_report(report)
    return report


def write_acceptance_report(path: str | Path, value: Any) -> Path:
    """Validate and atomically publish an acceptance report as UTF-8 JSON."""
    report = validate_acceptance_report(value)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                report,
                handle,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _json_projection(value: Any) -> dict[str, Any]:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        projected = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError("acceptance report must be JSON-safe") from exc
    if not isinstance(projected, dict):
        raise ValueError("acceptance report must be an object")
    return projected


def _validate_base_report(report: dict[str, Any]) -> None:
    if type(report.get("schema_version")) is not int:
        raise ValueError("schema_version must be integer 1")
    if report["schema_version"] != 1:
        raise ValueError("schema_version must be 1")

    status = report.get("status")
    if status not in _ALLOWED_STATUSES:
        raise ValueError("status must be PASS, FAIL, or INCOMPLETE")

    commit = report.get("commit")
    if not isinstance(commit, str) or not _COMMIT_PATTERN.fullmatch(commit):
        raise ValueError("commit must be a 40-character lowercase Git hash")

    pscad = _mapping(report.get("pscad"), "pscad")
    _nonempty_string(pscad.get("version"), "pscad.version")
    _nonempty_string(pscad.get("backend"), "pscad.backend")
    if type(pscad.get("licensed")) is not bool:
        raise ValueError("pscad.licensed must be a boolean")

    cases = report.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty list")
    for index, case in enumerate(cases):
        case_value = _mapping(case, f"cases[{index}]")
        _nonempty_string(case_value.get("name"), f"cases[{index}].name")


def _validate_pass_report(report: dict[str, Any]) -> None:
    _nonempty_string(report.get("rule_version"), "rule_version")
    pscad = report["pscad"]
    if pscad != {
        "version": "4.6.2",
        "backend": "legacy",
        "licensed": True,
    }:
        raise ValueError("PASS requires licensed Legacy PSCAD 4.6.2")

    coverage_codes = _sorted_strings(
        report.get("coverage_codes"), "coverage_codes"
    )
    if not _REQUIRED_CODES <= set(coverage_codes):
        raise ValueError("coverage_codes is missing required seeded defects")

    cases = report["cases"]
    observed_coverage: set[str] = set()
    has_healthy = False
    has_uncertainty = False
    has_scale_2000 = False
    for index, case in enumerate(cases):
        observed_errors, observed_unresolved = _validate_pass_case(case, index)
        observed_coverage.update(observed_errors)
        has_healthy |= case["healthy"]
        has_uncertainty |= bool(observed_unresolved)
        has_scale_2000 |= case["object_count"] >= 2000

    if not has_healthy:
        raise ValueError("PASS requires at least one healthy case")
    if not has_uncertainty:
        raise ValueError("PASS requires at least one uncertainty case")
    if not has_scale_2000:
        raise ValueError("PASS requires at least one 2,000-object case")
    if not _REQUIRED_CODES <= observed_coverage:
        raise ValueError("seeded cases do not observe every required defect")


def _validate_pass_case(
    case: dict[str, Any], index: int
) -> tuple[list[str], list[str]]:
    prefix = f"cases[{index}]"
    if type(case.get("healthy")) is not bool:
        raise ValueError(f"{prefix}.healthy must be a boolean")

    source_hash = _digest(case.get("source_sha256"), f"{prefix}.source_sha256")
    before_hash = _digest(case.get("before_sha256"), f"{prefix}.before_sha256")
    after_hash = _digest(case.get("after_sha256"), f"{prefix}.after_sha256")
    if len({source_hash, before_hash, after_hash}) != 1:
        raise ValueError(f"{prefix} project hashes changed")

    topology_hashes = _digest_pair(
        case.get("topology_hashes"), f"{prefix}.topology_hashes"
    )
    if topology_hashes[0] != topology_hashes[1]:
        raise ValueError(f"{prefix} topology hashes are nondeterministic")

    inventory_hashes = _digest_pair(
        case.get("inventory_hashes"), f"{prefix}.inventory_hashes"
    )
    if inventory_hashes[0] != inventory_hashes[1]:
        raise ValueError(f"{prefix} object inventory changed")

    dirty_state = _mapping(case.get("dirty_state"), f"{prefix}.dirty_state")
    if type(dirty_state.get("available")) is not bool:
        raise ValueError(f"{prefix}.dirty_state.available must be a boolean")
    if dirty_state["available"]:
        if type(dirty_state.get("before")) is not bool or type(
            dirty_state.get("after")
        ) is not bool:
            raise ValueError(f"{prefix}.dirty_state values must be booleans")
        if dirty_state["before"] != dirty_state["after"]:
            raise ValueError(f"{prefix} dirty state changed")

    expected_edges = _sorted_strings(
        case.get("expected_confirmed_edges"),
        f"{prefix}.expected_confirmed_edges",
    )
    observed_edges = _sorted_strings(
        case.get("observed_confirmed_edges"),
        f"{prefix}.observed_confirmed_edges",
    )
    _require_equal(expected_edges, observed_edges, f"{prefix} confirmed edges")

    expected_errors = _sorted_strings(
        case.get("expected_error_codes"), f"{prefix}.expected_error_codes"
    )
    observed_errors = _sorted_strings(
        case.get("observed_error_codes"), f"{prefix}.observed_error_codes"
    )
    _require_equal(expected_errors, observed_errors, f"{prefix} error codes")

    expected_unresolved = _sorted_strings(
        case.get("expected_unresolved_codes"),
        f"{prefix}.expected_unresolved_codes",
    )
    observed_unresolved = _sorted_strings(
        case.get("observed_unresolved_codes"),
        f"{prefix}.observed_unresolved_codes",
    )
    _require_equal(
        expected_unresolved,
        observed_unresolved,
        f"{prefix} unresolved codes",
    )

    if case.get("candidate_edges_confirmed") is not False:
        raise ValueError(f"{prefix} promoted an inference candidate")

    capabilities = _mapping(
        case.get("source_capabilities"), f"{prefix}.source_capabilities"
    )
    if not capabilities or any(type(value) is not bool for value in capabilities.values()):
        raise ValueError(f"{prefix}.source_capabilities must contain booleans")

    timings = _mapping(
        case.get("phase_timings_ms"), f"{prefix}.phase_timings_ms"
    )
    if not _REQUIRED_PHASES <= timings.keys():
        raise ValueError(f"{prefix}.phase_timings_ms is incomplete")
    for phase in _REQUIRED_PHASES:
        _nonnegative_number(timings[phase], f"{prefix}.phase_timings_ms.{phase}")

    counts = _mapping(case.get("finding_counts"), f"{prefix}.finding_counts")
    if set(counts) != {"error", "info", "warning"}:
        raise ValueError(f"{prefix}.finding_counts must contain stable severities")
    for severity, count in counts.items():
        if type(count) is not int or count < 0:
            raise ValueError(f"{prefix}.finding_counts.{severity} is invalid")
    if counts["error"] != len(observed_errors):
        raise ValueError(f"{prefix}.finding_counts.error is inconsistent")
    if counts["warning"] != len(observed_unresolved):
        raise ValueError(f"{prefix}.finding_counts.warning is inconsistent")

    if case["healthy"] and (observed_errors or observed_unresolved):
        raise ValueError(f"{prefix} healthy case contains findings")

    object_count = case.get("object_count")
    if type(object_count) is not int or object_count < 0:
        raise ValueError(f"{prefix}.object_count must be a non-negative integer")
    elapsed_ms = _nonnegative_number(
        case.get("elapsed_ms"), f"{prefix}.elapsed_ms"
    )
    if object_count <= 500 and elapsed_ms > 3000.0:
        raise ValueError(f"{prefix} exceeds the 500-object performance limit")
    if 500 < object_count <= 2000 and elapsed_ms > 10000.0:
        raise ValueError(f"{prefix} exceeds the 2,000-object performance limit")

    return observed_errors, observed_unresolved


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return dict(value)


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


def _digest_pair(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{field} must contain exactly two hashes")
    return [_digest(item, field) for item in value]


def _sorted_strings(value: Any, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) for item in value)
        or value != sorted(value)
    ):
        raise ValueError(f"{field} must be a sorted string list")
    return value


def _nonnegative_number(value: Any, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{field} must be a finite non-negative number")
    return float(value)


def _require_equal(expected: Sequence[str], observed: Sequence[str], field: str) -> None:
    if expected != observed:
        raise ValueError(f"{field} do not match")
