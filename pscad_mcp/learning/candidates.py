from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib

from .models import (
    CandidateKind,
    CandidateState,
    GoalFailureKind,
    ImprovementCandidate,
    InvocationOutcome,
    ReviewMarker,
    StoredGoalFailure,
    StoredInvocation,
)


_RELIABILITY_CODES = frozenset(
    {
        "TIMEOUT",
        "EXECUTOR_UNHEALTHY",
        "INTERNAL_ERROR",
        "PARTIAL_COMPLETION",
        "REPAIR_CLEANUP_FAILED",
    }
)
_GUIDANCE_CODES = frozenset(
    {
        "INVALID_ARGUMENT",
        "NOT_FOUND",
        "WORKSPACE_NOT_CONFIGURED",
        "NOT_CONNECTED",
        "EXTERNAL_PSCAD_PRESENT",
        "NOT_LICENSED",
    }
)
_IMMEDIATE_CODES = frozenset({"PARTIAL_COMPLETION", "REPAIR_CLEANUP_FAILED"})
_GOAL_KIND_MAP = {
    GoalFailureKind.UNSUPPORTED_OPERATION: CandidateKind.CAPABILITY,
    GoalFailureKind.INCORRECT_RESULT: CandidateKind.CORRECTNESS,
    GoalFailureKind.INCOMPLETE_RESULT: CandidateKind.CORRECTNESS,
    GoalFailureKind.ENVIRONMENT_BLOCKED: CandidateKind.GUIDANCE,
    GoalFailureKind.RECOVERY_FAILED: CandidateKind.RELIABILITY,
    GoalFailureKind.UNKNOWN: CandidateKind.RELIABILITY,
}


def _fingerprint(kind: CandidateKind, tool: str | None, code: str) -> str:
    source = f"{kind.value}|{tool or '-'}|{code}".encode("ascii")
    return hashlib.sha256(source).hexdigest()


def _candidate_id(fingerprint: str) -> str:
    return f"PSCAD-IMP-{fingerprint[:12].upper()}"


def _watermark(
    fingerprint: str,
    latest_evidence_kind: str,
    latest_evidence_id: int,
    latest_evidence_at: str,
) -> str:
    source = (
        f"{fingerprint}|{latest_evidence_kind}|"
        f"{latest_evidence_id}|{latest_evidence_at}"
    )
    return hashlib.sha256(source.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class _CandidateSpec:
    kind: CandidateKind
    primary_tool: str | None
    code: str
    invocation_count: int
    goal_failure_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    retryable: bool | None
    latest_evidence_kind: str
    latest_evidence_id: int
    immediate_attention: bool
    resolved_by_later_evidence: bool
    priority: int


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_utc(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return _as_utc(datetime.fromisoformat(normalized))


def _timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _event_key(event_id: int, occurred_at: datetime) -> tuple[datetime, int]:
    return occurred_at, int(event_id)


def _within_window(
    occurred_at: datetime,
    *,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    return window_start <= occurred_at <= window_end


def _group_retryable(
    failures: Sequence[tuple[StoredInvocation, datetime]],
) -> bool | None:
    values = [event.retryable for event, _ in failures]
    if values and all(value is True for value in values):
        return True
    if values and all(value is False for value in values):
        return False
    return None


def _has_later_success(
    successes: Sequence[tuple[StoredInvocation, datetime]],
    latest_failure_key: tuple[datetime, int],
) -> bool:
    return any(
        _event_key(event.event_id, occurred_at) > latest_failure_key
        for event, occurred_at in successes
    )


def _success_count_after(
    successes: Sequence[tuple[StoredInvocation, datetime]],
    latest_failure_key: tuple[datetime, int],
) -> int:
    return sum(
        _event_key(event.event_id, occurred_at) > latest_failure_key
        for event, occurred_at in successes
    )


def _has_newer_goal_failure(
    failures: Sequence[tuple[StoredGoalFailure, datetime]],
    latest_failure_key: tuple[datetime, int],
) -> bool:
    return any(
        _event_key(event.event_id, occurred_at) > latest_failure_key
        for event, occurred_at in failures
    )


def _ordinary_kind(
    code: str,
    *,
    retryable: bool | None,
    has_later_success: bool,
) -> CandidateKind:
    if retryable is True and has_later_success:
        return CandidateKind.EFFICIENCY
    if code in _GUIDANCE_CODES:
        return CandidateKind.GUIDANCE
    return CandidateKind.RELIABILITY


def _make_candidate(
    spec: _CandidateSpec,
    review_markers: Mapping[str, ReviewMarker],
) -> ImprovementCandidate:
    first_seen = _timestamp(spec.first_seen_at)
    last_seen = _timestamp(spec.last_seen_at)
    fingerprint = _fingerprint(spec.kind, spec.primary_tool, spec.code)
    candidate_id = _candidate_id(fingerprint)
    evidence_watermark = _watermark(
        fingerprint,
        spec.latest_evidence_kind,
        spec.latest_evidence_id,
        last_seen,
    )

    if spec.resolved_by_later_evidence:
        state = CandidateState.RESOLVED_BY_LATER_EVIDENCE
    else:
        marker = review_markers.get(fingerprint)
        if marker is None:
            state = CandidateState.OPEN
        elif marker.evidence_watermark == evidence_watermark:
            state = CandidateState.NOTIFIED
        else:
            state = CandidateState.REOPENED

    immediate_attention = spec.immediate_attention and state not in {
        CandidateState.NOTIFIED,
        CandidateState.RESOLVED_BY_LATER_EVIDENCE,
    }
    return ImprovementCandidate(
        candidate_id=candidate_id,
        fingerprint=fingerprint,
        kind=spec.kind,
        state=state,
        primary_tool=spec.primary_tool,
        code=spec.code,
        priority=spec.priority,
        invocation_count=spec.invocation_count,
        goal_failure_count=spec.goal_failure_count,
        first_seen=first_seen,
        last_seen=last_seen,
        retryable=spec.retryable,
        evidence_watermark=evidence_watermark,
        immediate_attention=immediate_attention,
    )


def build_candidates(
    invocations: Sequence[StoredInvocation],
    goal_failures: Sequence[StoredGoalFailure],
    review_markers: Mapping[str, ReviewMarker],
    *,
    now: datetime,
    min_evidence: int = 3,
) -> list[ImprovementCandidate]:
    """Aggregate recent learning evidence into deterministic improvement candidates."""
    now_utc = _as_utc(now)
    window_start = now_utc - timedelta(days=30)

    invocation_by_id = {event.event_id: event for event in invocations}
    recent_invocations: list[tuple[StoredInvocation, datetime]] = []
    for event in invocations:
        occurred_at = _parse_utc(event.occurred_at)
        if _within_window(
            occurred_at,
            window_start=window_start,
            window_end=now_utc,
        ):
            recent_invocations.append((event, occurred_at))

    recent_goals: list[tuple[StoredGoalFailure, datetime, str | None]] = []
    goals_by_tool: dict[
        str | None, list[tuple[StoredGoalFailure, datetime]]
    ] = defaultdict(list)
    for event in goal_failures:
        occurred_at = _parse_utc(event.occurred_at)
        if not _within_window(
            occurred_at,
            window_start=window_start,
            window_end=now_utc,
        ):
            continue
        effective_tool = event.primary_tool
        if effective_tool is None and event.correlated_invocation_id is not None:
            correlated = invocation_by_id.get(event.correlated_invocation_id)
            if correlated is not None:
                effective_tool = correlated.tool_name
        recent_goals.append((event, occurred_at, effective_tool))
        goals_by_tool[effective_tool].append((event, occurred_at))

    failures_by_key: dict[
        tuple[str, str | None], list[tuple[StoredInvocation, datetime]]
    ] = defaultdict(list)
    successes_by_tool: dict[
        str, list[tuple[StoredInvocation, datetime]]
    ] = defaultdict(list)
    for event, occurred_at in recent_invocations:
        if event.outcome == InvocationOutcome.SUCCESS:
            successes_by_tool[event.tool_name].append((event, occurred_at))
        elif event.outcome == InvocationOutcome.ERROR:
            failures_by_key[(event.tool_name, event.error_code)].append(
                (event, occurred_at)
            )

    specs: list[_CandidateSpec] = []
    for (tool, raw_code), failures in failures_by_key.items():
        if len(failures) < min_evidence and raw_code not in _IMMEDIATE_CODES:
            continue
        failures.sort(key=lambda item: _event_key(item[0].event_id, item[1]))
        first_event, first_at = failures[0]
        latest_event, latest_at = failures[-1]
        code = raw_code or "UNKNOWN_ERROR"
        retryable = _group_retryable(failures)
        latest_key = _event_key(latest_event.event_id, latest_at)
        later_success = _has_later_success(
            successes_by_tool.get(tool, ()), latest_key
        )
        resolved = (
            _success_count_after(successes_by_tool.get(tool, ()), latest_key) >= 3
            and not _has_newer_goal_failure(
                goals_by_tool.get(tool, ()),
                latest_key,
            )
        )
        kind = _ordinary_kind(
            code,
            retryable=retryable,
            has_later_success=later_success,
        )
        specs.append(
            _CandidateSpec(
                kind=kind,
                primary_tool=tool,
                code=code,
                invocation_count=len(failures),
                goal_failure_count=0,
                first_seen_at=first_at,
                last_seen_at=latest_at,
                retryable=retryable,
                latest_evidence_kind="invocation",
                latest_evidence_id=latest_event.event_id,
                immediate_attention=raw_code in _IMMEDIATE_CODES,
                resolved_by_later_evidence=resolved,
                priority=len(failures),
            )
        )

    goal_groups: dict[
        tuple[CandidateKind, str | None, str],
        list[tuple[StoredGoalFailure, datetime]],
    ] = defaultdict(list)
    for event, occurred_at, effective_tool in recent_goals:
        goal_groups[
            (
                _GOAL_KIND_MAP[event.failure_kind],
                effective_tool,
                event.failure_kind.value,
            )
        ].append((event, occurred_at))

    for (kind, tool, code), failures in goal_groups.items():
        failures.sort(key=lambda item: _event_key(item[0].event_id, item[1]))
        first_event, first_at = failures[0]
        latest_event, latest_at = failures[-1]
        critical_count = sum(
            event.failure_kind
            in {
                GoalFailureKind.INCORRECT_RESULT,
                GoalFailureKind.RECOVERY_FAILED,
            }
            for event, _ in failures
        )
        specs.append(
            _CandidateSpec(
                kind=kind,
                primary_tool=tool,
                code=code,
                invocation_count=0,
                goal_failure_count=len(failures),
                first_seen_at=first_at,
                last_seen_at=latest_at,
                retryable=None,
                latest_evidence_kind="goal_failure",
                latest_evidence_id=latest_event.event_id,
                immediate_attention=code
                in {
                    GoalFailureKind.INCORRECT_RESULT.value,
                    GoalFailureKind.RECOVERY_FAILED.value,
                },
                resolved_by_later_evidence=False,
                priority=3 * len(failures) + 5 * critical_count,
            )
        )

    candidates = [
        _make_candidate(spec, review_markers)
        for spec in specs
    ]
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    candidates.sort(
        key=lambda candidate: (
            -candidate.priority,
            epoch - _parse_utc(candidate.last_seen),
            candidate.fingerprint,
        )
    )
    return candidates
