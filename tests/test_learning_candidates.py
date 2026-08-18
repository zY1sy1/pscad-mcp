from datetime import datetime, timezone

from pscad_mcp.learning.candidates import build_candidates
from pscad_mcp.learning.models import (
    CandidateKind,
    CandidateState,
    GoalFailureKind,
    InvocationOutcome,
    ReviewMarker,
    StoredGoalFailure,
    StoredInvocation,
)


NOW = datetime(2026, 8, 19, 2, 0, tzinfo=timezone.utc)


def _stored_invocation(
    event_id,
    outcome,
    at,
    *,
    tool="run_project",
    error_code=None,
    retryable=True,
):
    return StoredInvocation(
        event_id=event_id,
        occurred_at=at,
        session_id="session-a",
        tool_name=tool,
        duration_ms=10,
        outcome=outcome,
        error_code=(error_code or "TIMEOUT")
        if outcome is InvocationOutcome.ERROR
        else None,
        retryable=retryable if outcome is InvocationOutcome.ERROR else None,
        backend="legacy",
        pscad_version="4.6.2",
    )


def test_ordinary_error_requires_three_items_and_is_deterministic():
    failures = [
        _stored_invocation(
            index,
            InvocationOutcome.ERROR,
            f"2026-08-19T01:0{index}:00+00:00",
        )
        for index in range(1, 4)
    ]
    assert build_candidates(failures[:2], [], {}, now=NOW, min_evidence=3) == []
    candidate = build_candidates(failures, [], {}, now=NOW, min_evidence=3)[0]
    assert candidate.kind is CandidateKind.RELIABILITY
    assert candidate.state is CandidateState.OPEN
    assert candidate.priority == 3
    assert candidate.candidate_id.startswith("PSCAD-IMP-")
    assert candidate.immediate_attention is False


def test_explicit_incorrect_result_is_immediate_and_weighted():
    failure = StoredGoalFailure(
        event_id=1,
        occurred_at="2026-08-19T01:30:00+00:00",
        session_id="session-a",
        failure_kind=GoalFailureKind.INCORRECT_RESULT,
        primary_tool="analyze_hvdc_results",
        correlated_invocation_id=None,
    )
    candidate = build_candidates([], [failure], {}, now=NOW, min_evidence=3)[0]
    assert candidate.kind is CandidateKind.CORRECTNESS
    assert candidate.priority == 8
    assert candidate.immediate_attention is True


def test_only_critical_goal_kinds_are_immediate_on_first_evidence():
    immediate_kinds = {
        GoalFailureKind.INCORRECT_RESULT,
        GoalFailureKind.RECOVERY_FAILED,
    }
    for event_id, kind in enumerate(GoalFailureKind, start=1):
        failure = StoredGoalFailure(
            event_id=event_id,
            occurred_at="2026-08-19T01:30:00+00:00",
            session_id="session-a",
            failure_kind=kind,
            primary_tool="run_project",
            correlated_invocation_id=None,
        )
        candidate = build_candidates([], [failure], {}, now=NOW, min_evidence=3)[0]
        assert candidate.immediate_attention is (kind in immediate_kinds)


def test_single_critical_technical_error_bypasses_ordinary_threshold():
    event = _stored_invocation(
        1,
        InvocationOutcome.ERROR,
        "2026-08-19T01:30:00+00:00",
        error_code="PARTIAL_COMPLETION",
        retryable=False,
    )
    candidate = build_candidates([event], [], {}, now=NOW, min_evidence=3)[0]
    assert candidate.code == "PARTIAL_COMPLETION"
    assert candidate.immediate_attention is True


def test_correlated_goal_uses_the_invocation_tool_without_copying_content():
    invocation = _stored_invocation(
        7,
        InvocationOutcome.SUCCESS,
        "2026-08-19T01:20:00+00:00",
        tool="analyze_hvdc_results",
    )
    failure = StoredGoalFailure(
        event_id=1,
        occurred_at="2026-08-19T01:30:00+00:00",
        session_id="session-a",
        failure_kind=GoalFailureKind.INCORRECT_RESULT,
        primary_tool=None,
        correlated_invocation_id=7,
    )
    candidate = build_candidates(
        [invocation], [failure], {}, now=NOW, min_evidence=3
    )[0]
    assert candidate.primary_tool == "analyze_hvdc_results"


def test_reviewed_candidate_reopens_only_for_new_evidence():
    failures = [
        _stored_invocation(
            index,
            InvocationOutcome.ERROR,
            f"2026-08-19T01:0{index}:00+00:00",
        )
        for index in range(1, 4)
    ]
    original = build_candidates(failures, [], {}, now=NOW, min_evidence=3)[0]
    marker = ReviewMarker(
        fingerprint=original.fingerprint,
        first_notified_at=NOW.isoformat(),
        last_notified_at=NOW.isoformat(),
        notification_source="scheduled",
        evidence_watermark=original.evidence_watermark,
    )
    unchanged = build_candidates(
        failures,
        [],
        {original.fingerprint: marker},
        now=NOW,
        min_evidence=3,
    )[0]
    changed = build_candidates(
        failures + [
            _stored_invocation(
                4,
                InvocationOutcome.ERROR,
                "2026-08-19T01:40:00+00:00",
            )
        ],
        [],
        {original.fingerprint: marker},
        now=NOW,
        min_evidence=3,
    )[0]
    assert unchanged.state is CandidateState.NOTIFIED
    assert changed.state is CandidateState.REOPENED


def test_retention_count_change_does_not_look_like_new_evidence():
    failures = [
        _stored_invocation(
            index,
            InvocationOutcome.ERROR,
            f"2026-08-19T01:0{index}:00+00:00",
        )
        for index in range(1, 5)
    ]
    original = build_candidates(failures, [], {}, now=NOW, min_evidence=3)[0]
    marker = ReviewMarker(
        fingerprint=original.fingerprint,
        first_notified_at=NOW.isoformat(),
        last_notified_at=NOW.isoformat(),
        notification_source="scheduled",
        evidence_watermark=original.evidence_watermark,
    )
    after_retention = build_candidates(
        failures[1:],
        [],
        {original.fingerprint: marker},
        now=NOW,
        min_evidence=3,
    )[0]
    assert after_retention.invocation_count == 3
    assert after_retention.state is CandidateState.NOTIFIED


def test_three_later_successes_resolve_invocation_candidate():
    events = [
        _stored_invocation(
            index,
            InvocationOutcome.ERROR,
            f"2026-08-19T00:0{index}:00+00:00",
        )
        for index in range(1, 4)
    ] + [
        _stored_invocation(
            index,
            InvocationOutcome.SUCCESS,
            f"2026-08-19T01:0{index}:00+00:00",
        )
        for index in range(4, 7)
    ]
    candidate = build_candidates(events, [], {}, now=NOW, min_evidence=3)[0]
    assert candidate.state is CandidateState.RESOLVED_BY_LATER_EVIDENCE
    assert candidate.immediate_attention is False


def test_newer_explicit_goal_failure_prevents_success_suppression():
    events = [
        _stored_invocation(
            index,
            InvocationOutcome.ERROR,
            f"2026-08-19T00:0{index}:00+00:00",
        )
        for index in range(1, 4)
    ] + [
        _stored_invocation(
            index,
            InvocationOutcome.SUCCESS,
            f"2026-08-19T01:0{index}:00+00:00",
        )
        for index in range(4, 7)
    ]
    explicit = StoredGoalFailure(
        event_id=1,
        occurred_at="2026-08-19T01:07:00+00:00",
        session_id="session-a",
        failure_kind=GoalFailureKind.INCORRECT_RESULT,
        primary_tool="run_project",
        correlated_invocation_id=None,
    )
    candidates = build_candidates(
        events, [explicit], {}, now=NOW, min_evidence=3
    )
    technical = next(item for item in candidates if item.code == "TIMEOUT")
    assert technical.state is CandidateState.OPEN


def test_retryable_failures_with_one_later_success_are_efficiency_evidence():
    events = [
        _stored_invocation(
            index,
            InvocationOutcome.ERROR,
            f"2026-08-19T00:0{index}:00+00:00",
        )
        for index in range(1, 4)
    ] + [
        _stored_invocation(
            4,
            InvocationOutcome.SUCCESS,
            "2026-08-19T01:04:00+00:00",
        )
    ]
    candidate = build_candidates(events, [], {}, now=NOW, min_evidence=3)[0]
    assert candidate.kind is CandidateKind.EFFICIENCY
    assert candidate.state is CandidateState.OPEN


def test_candidates_sort_by_priority_and_repeat_deterministically():
    invocations = [
        _stored_invocation(
            index,
            InvocationOutcome.ERROR,
            f"2026-08-19T01:0{index}:00+00:00",
        )
        for index in range(1, 4)
    ]
    explicit = StoredGoalFailure(
        event_id=1,
        occurred_at="2026-08-19T01:30:00+00:00",
        session_id="session-a",
        failure_kind=GoalFailureKind.RECOVERY_FAILED,
        primary_tool="repair_connection",
        correlated_invocation_id=None,
    )
    first = build_candidates(
        invocations, [explicit], {}, now=NOW, min_evidence=3
    )
    second = build_candidates(
        invocations, [explicit], {}, now=NOW, min_evidence=3
    )
    assert first == second
    assert [candidate.priority for candidate in first] == [8, 3]
