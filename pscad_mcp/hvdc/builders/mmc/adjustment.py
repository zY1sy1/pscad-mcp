"""Selection of bounded, immutable MMC adjustment candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ....core.backend.base import BackendError
from ..common.records import JsonRecord
from .diagnostics import MmcFailureClassification, classify_mmc_failure
from .parametric_models import MmcAdjustment, MmcCandidate, MmcParentPlan


@dataclass(frozen=True)
class MmcAdjustmentDecision(JsonRecord):
    engine: str
    candidate_id: str
    candidate: MmcCandidate
    adjustment: MmcAdjustment
    failure: MmcFailureClassification
    failure_signature: str


def _error(code: str, message: str, **details: object) -> BackendError:
    return BackendError(code, message, "hvdc", "choose_mmc_candidate", details)


def _child(plan: MmcParentPlan, engine: str):
    children = [item for item in plan.engine_plans if item.engine == engine]
    if len(children) != 1:
        raise _error(
            "MMC_PLAN_INVALID",
            "The parent plan must contain exactly one requested engine child.",
            engine=engine,
            count=len(children),
        )
    child = children[0]
    if not 1 <= len(child.candidates) <= 8:
        raise _error(
            "MMC_CANDIDATE_INVALID",
            "An MMC child plan requires 1-8 candidates.",
            engine=engine,
            count=len(child.candidates),
        )
    ids = [item.candidate_id for item in child.candidates]
    hashes = [item.parameter_hash for item in child.candidates]
    if (
        any(item.engine != engine for item in child.candidates)
        or any(not value for value in ids)
        or len(set(ids)) != len(ids)
        or any(not value for value in hashes)
        or len(set(hashes)) != len(hashes)
    ):
        raise _error(
            "MMC_CANDIDATE_INVALID",
            "MMC candidates require matching engines and unique identities and hashes.",
            engine=engine,
        )
    return child


def _changes(previous: MmcCandidate, selected: MmcCandidate) -> dict[str, Any]:
    def changed(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: {"from": left.get(key), "to": right.get(key)}
            for key in sorted(set(left) | set(right))
            if left.get(key) != right.get(key)
        }

    return {
        "parameters": changed(previous.parameters, selected.parameters),
        "settings": changed(previous.settings, selected.settings),
    }


def _repeat_detected(
    failure: BackendError | Mapping[str, Any],
    classification: MmcFailureClassification,
    attempted: tuple[str, ...],
) -> bool:
    details: Mapping[str, Any]
    if isinstance(failure, BackendError):
        details = failure.details
    else:
        raw = failure.get("details", {})
        details = raw if isinstance(raw, Mapping) else {}
    previous = details.get("previous_failure_signatures", ())
    failed_candidate = details.get("candidate_id", attempted[-1] if attempted else None)
    return (
        isinstance(previous, Sequence)
        and not isinstance(previous, (str, bytes, bytearray))
        and classification.signature in previous
        and failed_candidate in attempted
    )


def choose_next_candidate(
    plan: MmcParentPlan,
    engine: str,
    *,
    attempted: tuple[str, ...],
    failure: BackendError | Mapping[str, Any],
) -> MmcAdjustmentDecision:
    if not isinstance(plan, MmcParentPlan):
        raise _error("MMC_PLAN_INVALID", "candidate selection requires MmcParentPlan.")
    child = _child(plan, engine)
    by_id = {item.candidate_id: item for item in child.candidates}
    if len(set(attempted)) != len(attempted) or any(item not in by_id for item in attempted):
        raise _error(
            "MMC_CANDIDATE_INVALID",
            "Attempted candidates must be unique identities from the child plan.",
            attempted=list(attempted),
        )
    classification = classify_mmc_failure(failure)
    if _repeat_detected(failure, classification, attempted):
        raise _error(
            "MMC_CANDIDATES_EXHAUSTED",
            "The same MMC failure signature repeated at the same candidate state.",
            engine=engine,
            failure_signature=classification.signature,
            attempted=list(attempted),
        )
    if not classification.retryable:
        raise _error(
            "MMC_ADJUSTMENT_NOT_ALLOWED",
            "This MMC failure category cannot advance the candidate loop.",
            engine=engine,
            category=classification.category,
            failure_signature=classification.signature,
            suggested_action=classification.suggested_action,
        )
    attempted_set = set(attempted)
    selected = next(
        (
            item
            for item in child.candidates
            if item.candidate_id not in attempted_set
            and item.purpose == classification.category
        ),
        None,
    )
    if selected is None:
        raise _error(
            "MMC_CANDIDATES_EXHAUSTED",
            "No unattempted preplanned candidate matches the failure category.",
            engine=engine,
            category=classification.category,
            attempted=list(attempted),
        )
    previous = by_id[attempted[-1]] if attempted else child.candidates[0]
    adjustment = MmcAdjustment(
        category=classification.category,
        changes=_changes(previous, selected),
        rationale=(
            f"Selected immutable candidate {selected.candidate_id} for "
            f"{classification.category}; requested ratings and thresholds are unchanged."
        ),
    )
    return MmcAdjustmentDecision(
        engine=engine,
        candidate_id=selected.candidate_id,
        candidate=selected,
        adjustment=adjustment,
        failure=classification,
        failure_signature=classification.signature,
    )


__all__ = ["MmcAdjustmentDecision", "choose_next_candidate"]
