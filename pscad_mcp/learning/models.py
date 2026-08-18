from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class InvocationOutcome(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class GoalFailureKind(str, Enum):
    UNSUPPORTED_OPERATION = "unsupported_operation"
    INCORRECT_RESULT = "incorrect_result"
    INCOMPLETE_RESULT = "incomplete_result"
    ENVIRONMENT_BLOCKED = "environment_blocked"
    RECOVERY_FAILED = "recovery_failed"
    UNKNOWN = "unknown"


class CandidateKind(str, Enum):
    RELIABILITY = "reliability"
    CORRECTNESS = "correctness"
    CAPABILITY = "capability"
    GUIDANCE = "guidance"
    EFFICIENCY = "efficiency"


class CandidateState(str, Enum):
    OPEN = "open"
    REOPENED = "reopened"
    NOTIFIED = "notified"
    RESOLVED_BY_LATER_EVIDENCE = "resolved_by_later_evidence"


@dataclass(frozen=True)
class InvocationEvent:
    occurred_at: str
    session_id: str
    tool_name: str
    duration_ms: int
    outcome: InvocationOutcome
    error_code: str | None
    retryable: bool | None
    backend: str | None
    pscad_version: str | None


@dataclass(frozen=True)
class StoredInvocation:
    event_id: int
    occurred_at: str
    session_id: str
    tool_name: str
    duration_ms: int
    outcome: InvocationOutcome
    error_code: str | None
    retryable: bool | None
    backend: str | None
    pscad_version: str | None


@dataclass(frozen=True)
class GoalFailureEvent:
    occurred_at: str
    session_id: str
    failure_kind: GoalFailureKind
    primary_tool: str | None
    correlated_invocation_id: int | None


@dataclass(frozen=True)
class StoredGoalFailure:
    event_id: int
    occurred_at: str
    session_id: str
    failure_kind: GoalFailureKind
    primary_tool: str | None
    correlated_invocation_id: int | None


@dataclass(frozen=True)
class ReviewMarker:
    fingerprint: str
    first_notified_at: str
    last_notified_at: str
    notification_source: str
    evidence_watermark: str


@dataclass(frozen=True)
class ImprovementCandidate:
    candidate_id: str
    fingerprint: str
    kind: CandidateKind
    state: CandidateState
    primary_tool: str | None
    code: str
    priority: int
    invocation_count: int
    goal_failure_count: int
    first_seen: str
    last_seen: str
    retryable: bool | None
    evidence_watermark: str
    immediate_attention: bool

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("fingerprint")
        value.pop("evidence_watermark")
        value["kind"] = self.kind.value
        value["state"] = self.state.value
        return value
