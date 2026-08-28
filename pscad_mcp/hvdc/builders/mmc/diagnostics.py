"""Closed failure classification for bounded MMC candidate execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ....core.backend.base import BackendError
from ..common.records import JsonRecord, freeze
from ..common.serialization import content_hash


@dataclass(frozen=True)
class MmcFailureClassification(JsonRecord):
    code: str
    category: str
    retryable: bool
    signature: str
    suggested_action: str
    evidence: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", freeze(self.evidence))


_TABLE: dict[str, tuple[str, bool, str]] = {
    "MMC_STARTUP_SNAPSHOT_MISSING": (
        "binding_repair",
        True,
        "Use the preplanned candidate that removes the missing staging snapshot.",
    ),
    "MMC_ABSOLUTE_PATH_UNRESOLVED": (
        "binding_repair",
        False,
        "Audit and explicitly verify the line dependency before replanning.",
    ),
    "MMC_BINDING_MISSING": (
        "binding_repair",
        False,
        "Provide an unambiguous audited binding and create a new plan.",
    ),
    "MMC_BINDING_AMBIGUOUS": (
        "binding_repair",
        False,
        "Resolve the ambiguous template binding before rebuilding.",
    ),
    "MMC_NUMERICAL_UNSTABLE": (
        "numerical_stability",
        True,
        "Try the next preplanned numerical-stability candidate.",
    ),
    "MMC_TIMESTEP_TOO_LARGE": (
        "numerical_stability",
        True,
        "Try the next preplanned numerical-stability candidate.",
    ),
    "MMC_CONTROL_UNSTABLE": (
        "control_stability",
        True,
        "Try the next preplanned control-stability candidate.",
    ),
    "MMC_MODULATION_MARGIN_LOW": (
        "modulation_margin",
        True,
        "Try the next preplanned modulation-margin candidate.",
    ),
    "MMC_ENERGY_IMBALANCE": (
        "energy_balance",
        True,
        "Try the next preplanned energy-balance candidate.",
    ),
    "MMC_INITIALIZATION_FAILED": (
        "initialization",
        True,
        "Try the next preplanned initialization candidate.",
    ),
    "MMC_REQUEST_INFEASIBLE": (
        "physical_infeasible",
        False,
        "Revise the rating request and create a new plan.",
    ),
    "MMC_DESIGN_INFEASIBLE": (
        "physical_infeasible",
        False,
        "Revise the rating request and create a new plan.",
    ),
    "MMC_MODEL_UNSUPPORTED": (
        "physical_infeasible",
        False,
        "Use a supported topology and converter request.",
    ),
    "MMC_ACCEPTANCE_FAILED": (
        "acceptance",
        False,
        "Inspect the failed acceptance evidence without weakening thresholds.",
    ),
    "MMC_PROTECTION_INADEQUATE": (
        "acceptance",
        False,
        "Correct protection capability and create a new confirmed plan.",
    ),
    "LICENSE_UNAVAILABLE": (
        "environment",
        False,
        "Restore the PSCAD license before retrying the confirmed build.",
    ),
    "NOT_LICENSED": (
        "environment",
        False,
        "Restore the PSCAD license before retrying the confirmed build.",
    ),
    "EXECUTOR_UNHEALTHY": (
        "environment",
        False,
        "Repair the PSCAD executor connection before retrying.",
    ),
    "BACKEND_UNAVAILABLE": (
        "environment",
        False,
        "Restore the PSCAD backend before retrying.",
    ),
    "CONNECTION_FAILED": (
        "environment",
        False,
        "Repair the PSCAD connection before retrying.",
    ),
    "MMC_TEMPLATE_SOURCE_CHANGED": (
        "containment",
        False,
        "Re-audit the template and confirm a new plan hash.",
    ),
    "MMC_ASSET_MISMATCH": (
        "containment",
        False,
        "Restore verified repository assets and create a new plan.",
    ),
    "MMC_PLAN_STALE": (
        "containment",
        False,
        "Create and confirm a new deterministic plan.",
    ),
    "MMC_BUILD_CONFLICT": (
        "containment",
        False,
        "Wait for the active workspace lease or choose an empty target.",
    ),
    "MMC_POSTCONDITION_FAILED": (
        "containment",
        False,
        "Inspect staging evidence; do not continue the candidate loop.",
    ),
    "MMC_BUILD_TIMED_OUT": (
        "containment",
        False,
        "Confirm the PSCAD process state before any retry.",
    ),
    "MMC_BUILD_INTERRUPTED": (
        "containment",
        False,
        "Confirm containment and start a newly confirmed build.",
    ),
}

_VOLATILE_KEYS = {
    "at",
    "build_id",
    "candidate_id",
    "elapsed_s",
    "parameter_hash",
    "previous_failure_signatures",
    "timestamp",
}


def _stable(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _stable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_KEYS
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_stable(item) for item in value]
    return {"type": type(value).__name__}


def _error_parts(error: BackendError | Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if isinstance(error, BackendError):
        return error.code, error.operation, dict(error.details)
    if isinstance(error, Mapping):
        code = error.get("code")
        operation = error.get("operation", "unknown")
        details = error.get("details", {})
        if isinstance(code, str) and isinstance(operation, str) and isinstance(details, Mapping):
            return code, operation, dict(details)
    raise TypeError("MMC failure evidence must be BackendError or a stable error mapping")


def classify_mmc_failure(
    error: BackendError | Mapping[str, Any],
) -> MmcFailureClassification:
    code, operation, details = _error_parts(error)
    category, retryable, action = _TABLE.get(
        code,
        (
            "containment",
            False,
            "Inspect the unclassified failure and confirm containment before replanning.",
        ),
    )
    evidence = {"operation": operation, "details": _stable(details)}
    signature = content_hash(
        {"code": code, "operation": operation, "details": evidence["details"]}
    )
    return MmcFailureClassification(
        code=code,
        category=category,
        retryable=retryable,
        signature=signature,
        suggested_action=action,
        evidence=evidence,
    )


__all__ = ["MmcFailureClassification", "classify_mmc_failure"]
