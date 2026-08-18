from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
import logging
import re
import threading
import uuid

from ..core.backend.base import BackendError
from ..core.service import ConfirmationRequired
from .candidates import build_candidates
from .config import LearningConfig
from .markdown import render_backlog
from .models import (
    CandidateState,
    GoalFailureEvent,
    GoalFailureKind,
    ImprovementCandidate,
    InvocationEvent,
    InvocationOutcome,
    ReviewMarker,
    StoredInvocation,
)
from .store import LearningStore


_LOGGER = logging.getLogger("pscad-mcp.learning")
_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_BACKEND_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_PSCAD_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,31}\Z")
_MAX_DURATION_MS = 86_400_000
_UNKNOWN_ERROR_CODE = "UNKNOWN_ERROR"
_INVALID_TOOL_MESSAGE = "The supplied tool name is not registered."


def _invalid_argument(operation: str, message: str) -> BackendError:
    return BackendError(
        "INVALID_ARGUMENT",
        message,
        "learning",
        operation,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class LearningService:
    """Coordinate the durable learning store and generated review projection."""

    def __init__(
        self,
        config: LearningConfig,
        *,
        clock: Callable[[], datetime] | None = None,
        session_id: str | None = None,
        store_factory: Callable[[str], LearningStore] | None = None,
    ) -> None:
        self._config = config
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._session_id = session_id or uuid.uuid4().hex
        self._registered_tool_names: set[str] = set()
        self._lock = threading.RLock()
        factory = store_factory or LearningStore
        self._store = factory(str(config.database_path))

        try:
            now = self._now()
            self._store.prune(
                now=now,
                retention_days=config.retention_days,
                max_events=config.max_events,
            )
            invocations, goal_failures = self._load_evidence(now)
            review_markers = self._store.load_review_markers()
            retained = build_candidates(
                invocations,
                goal_failures,
                review_markers,
                now=now,
                min_evidence=1,
            )
            self._store.delete_review_markers_except(
                {candidate.fingerprint for candidate in retained}
            )
            self._render_candidates(now)
        except BaseException:
            self._store.close()
            raise

    @property
    def session_id(self) -> str:
        return self._session_id

    def _now(self) -> datetime:
        return _as_utc(self._clock())

    def _load_evidence(
        self,
        now: datetime,
    ) -> tuple[list, list]:
        since = (now - timedelta(days=30)).isoformat()
        return (
            self._store.load_invocations(since),
            self._store.load_goal_failures(since),
        )

    def _candidates(
        self,
        now: datetime,
        *,
        min_evidence: int,
        review_markers: Mapping[str, ReviewMarker] | None = None,
    ) -> tuple[list[ImprovementCandidate], Mapping[str, ReviewMarker]]:
        invocations, goal_failures = self._load_evidence(now)
        markers = (
            self._store.load_review_markers()
            if review_markers is None
            else review_markers
        )
        return (
            build_candidates(
                invocations,
                goal_failures,
                markers,
                now=now,
                min_evidence=min_evidence,
            ),
            markers,
        )

    def _render_candidates(
        self,
        now: datetime,
        *,
        candidates: list[ImprovementCandidate] | None = None,
    ) -> None:
        if candidates is None:
            candidates, _ = self._candidates(now, min_evidence=1)
        render_backlog(
            self._config.backlog_path,
            candidates,
            generated_at=now.isoformat(),
        )

    @staticmethod
    def _normalize_duration(value: int) -> int:
        try:
            duration = int(value)
        except (TypeError, ValueError, OverflowError):
            return 0
        return max(0, min(_MAX_DURATION_MS, duration))

    @staticmethod
    def _normalize_error_code(value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or _ERROR_CODE.fullmatch(value) is None:
            return "INTERNAL_ERROR"
        return value

    @staticmethod
    def _normalize_optional(value: str | None, pattern: re.Pattern[str]) -> str | None:
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            return None
        return value

    @staticmethod
    def _normalize_retryable(value: bool | None) -> bool | None:
        return value if isinstance(value, bool) else None

    @staticmethod
    def _normalize_outcome(value: InvocationOutcome) -> InvocationOutcome:
        try:
            return value if isinstance(value, InvocationOutcome) else InvocationOutcome(value)
        except (TypeError, ValueError):
            raise _invalid_argument(
                "record_invocation",
                "The invocation outcome is invalid.",
            ) from None

    @staticmethod
    def _normalize_failure_kind(value: GoalFailureKind) -> GoalFailureKind:
        try:
            return (
                value
                if isinstance(value, GoalFailureKind)
                else GoalFailureKind(value)
            )
        except (TypeError, ValueError):
            raise _invalid_argument(
                "record_goal_failure",
                "The goal failure kind is invalid.",
            ) from None

    def register_tool_name(self, name: str) -> None:
        with self._lock:
            if not isinstance(name, str):
                raise _invalid_argument(
                    "register_tool_name",
                    "The tool name is invalid.",
                )
            self._registered_tool_names.add(name)

    def _require_registered_tool(self, name: str) -> None:
        if not isinstance(name, str) or name not in self._registered_tool_names:
            raise _invalid_argument("learning", _INVALID_TOOL_MESSAGE)

    def record_invocation(
        self,
        *,
        tool_name: str,
        duration_ms: int,
        outcome: InvocationOutcome,
        error_code: str | None,
        retryable: bool | None,
        backend: str | None,
        pscad_version: str | None,
    ) -> None:
        with self._lock:
            self._require_registered_tool(tool_name)
            normalized_outcome = self._normalize_outcome(outcome)
            now = self._now()
            self._store.record_invocation(
                InvocationEvent(
                    occurred_at=now.isoformat(),
                    session_id=self._session_id,
                    tool_name=tool_name,
                    duration_ms=self._normalize_duration(duration_ms),
                    outcome=normalized_outcome,
                    error_code=self._normalize_error_code(error_code),
                    retryable=self._normalize_retryable(retryable),
                    backend=self._normalize_optional(backend, _BACKEND_NAME),
                    pscad_version=self._normalize_optional(
                        pscad_version,
                        _PSCAD_VERSION,
                    ),
                )
            )
            if normalized_outcome is InvocationOutcome.ERROR:
                self._render_candidates(now)
            elif self._store.has_failure_evidence(tool_name):
                self._render_candidates(now)

    def _latest_registered_invocation(
        self,
        primary_tool: str | None,
    ) -> tuple[str | None, StoredInvocation | None]:
        latest = self._store.latest_invocation(self._session_id, primary_tool)
        if latest is None or latest.tool_name not in self._registered_tool_names:
            if primary_tool is None:
                return None, None
            return primary_tool, None
        return latest.tool_name, latest

    @staticmethod
    def _marker(
        candidate: ImprovementCandidate,
        *,
        now: datetime,
        source: str,
        existing: Mapping[str, ReviewMarker],
    ) -> ReviewMarker:
        timestamp = now.isoformat()
        previous = existing.get(candidate.fingerprint)
        return ReviewMarker(
            fingerprint=candidate.fingerprint,
            first_notified_at=(
                previous.first_notified_at if previous is not None else timestamp
            ),
            last_notified_at=timestamp,
            notification_source=source,
            evidence_watermark=candidate.evidence_watermark,
        )

    def _select_goal_candidate(
        self,
        candidates: list[ImprovementCandidate],
        *,
        failure_kind: GoalFailureKind,
        effective_tool: str | None,
        correlated_invocation: StoredInvocation | None,
    ) -> ImprovementCandidate | None:
        if correlated_invocation is not None:
            error_code = correlated_invocation.error_code or _UNKNOWN_ERROR_CODE
            for candidate in candidates:
                if (
                    candidate.primary_tool == effective_tool
                    and candidate.code == error_code
                    and candidate.invocation_count > 0
                    and candidate.goal_failure_count == 0
                    and candidate.immediate_attention
                ):
                    return candidate

        expected_code = failure_kind.value
        for candidate in candidates:
            if (
                candidate.primary_tool == effective_tool
                and candidate.code == expected_code
                and candidate.goal_failure_count > 0
            ):
                return candidate
        return candidates[0] if candidates else None

    @staticmethod
    def _goal_result(
        candidate: ImprovementCandidate | None,
        *,
        attention: bool,
    ) -> dict[str, object]:
        if candidate is None:
            return {
                "recorded": True,
                "learning_enabled": True,
                "candidate_id": None,
                "category": None,
                "state": None,
                "immediate_attention": attention,
            }
        return {
            "recorded": True,
            "learning_enabled": True,
            "candidate_id": candidate.candidate_id,
            "category": candidate.kind.value,
            "state": candidate.state.value,
            "immediate_attention": attention,
        }

    def record_goal_failure(
        self,
        failure_kind: GoalFailureKind,
        primary_tool: str | None,
    ) -> dict[str, object]:
        with self._lock:
            normalized_kind = self._normalize_failure_kind(failure_kind)
            if primary_tool is not None:
                self._require_registered_tool(primary_tool)

            now = self._now()
            effective_tool, correlated_invocation = self._latest_registered_invocation(
                primary_tool
            )
            self._store.record_goal_failure(
                GoalFailureEvent(
                    occurred_at=now.isoformat(),
                    session_id=self._session_id,
                    failure_kind=normalized_kind,
                    primary_tool=effective_tool,
                    correlated_invocation_id=(
                        None
                        if correlated_invocation is None
                        else correlated_invocation.event_id
                    ),
                )
            )

            candidates, review_markers = self._candidates(
                now,
                min_evidence=1,
            )
            selected = self._select_goal_candidate(
                candidates,
                failure_kind=normalized_kind,
                effective_tool=effective_tool,
                correlated_invocation=correlated_invocation,
            )
            attention = bool(
                selected is not None
                and (
                    selected.immediate_attention
                    or selected.state is CandidateState.REOPENED
                )
            )
            if attention and selected is not None:
                marker = self._marker(
                    selected,
                    now=now,
                    source="foreground",
                    existing=review_markers,
                )
                projected_markers = dict(review_markers)
                projected_markers[selected.fingerprint] = marker
                projected_candidates, _ = self._candidates(
                    now,
                    min_evidence=1,
                    review_markers=projected_markers,
                )
                self._render_candidates(now, candidates=projected_candidates)
                self._store.mark_notified([marker])
            else:
                self._render_candidates(now, candidates=candidates)

            return self._goal_result(selected, attention=attention)

    @staticmethod
    def _validate_review_bounds(limit: int, min_evidence: int) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
            or isinstance(min_evidence, bool)
            or not isinstance(min_evidence, int)
            or not 1 <= min_evidence <= 100
        ):
            raise _invalid_argument(
                "review",
                "limit and min_evidence must be between 1 and 100.",
            )

    def review(
        self,
        *,
        limit: int,
        min_evidence: int,
        mark_notified: bool,
    ) -> dict[str, object]:
        with self._lock:
            self._validate_review_bounds(limit, min_evidence)
            now = self._now()
            candidates, review_markers = self._candidates(
                now,
                min_evidence=min_evidence,
            )
            candidates = [
                candidate
                for candidate in candidates
                if candidate.state in {
                    CandidateState.OPEN,
                    CandidateState.REOPENED,
                }
            ]
            bounded = candidates[:limit]
            counts = self._store.counts()

            if mark_notified and bounded:
                markers = [
                    self._marker(
                        candidate,
                        now=now,
                        source="scheduled",
                        existing=review_markers,
                    )
                    for candidate in bounded
                ]
                projected_markers = dict(review_markers)
                projected_markers.update(
                    {
                        marker.fingerprint: marker
                        for marker in markers
                    }
                )
                projected_candidates, _ = self._candidates(
                    now,
                    min_evidence=1,
                    review_markers=projected_markers,
                )
                self._render_candidates(now, candidates=projected_candidates)
                self._store.mark_notified(markers)

            return {
                "learning_enabled": True,
                "learning_available": True,
                "counts": counts,
                "attention_required": bool(bounded),
                "candidates": [candidate.public_dict() for candidate in bounded],
            }

    def clear(self, *, confirm: bool) -> bool:
        with self._lock:
            if not confirm:
                raise ConfirmationRequired("clear_learning_history")
            self._store.clear_history()
            self._render_candidates(self._now(), candidates=[])
            return True


class LearningRuntime:
    """Lazy, fail-open facade for learning operations used by the runtime."""

    def __init__(
        self,
        config_loader: Callable[[], LearningConfig] | None = None,
    ) -> None:
        self._config_loader = config_loader or LearningConfig.from_environ
        self._config: LearningConfig | None = None
        self._config_loaded = False
        self._config_issue: str | None = None
        self._service: LearningService | object | None = None
        self._registered_tool_names: set[str] = set()
        self._lock = threading.RLock()
        self._unavailable = False
        self._availability_warning_emitted = False
        self._automatic_recording_disabled = False
        self._automatic_warning_emitted = False

    def register_tool_name(self, name: str) -> None:
        with self._lock:
            if not isinstance(name, str):
                raise _invalid_argument(
                    "register_tool_name",
                    "The tool name is invalid.",
                )
            self._registered_tool_names.add(name)
            if self._service is not None and hasattr(
                self._service,
                "register_tool_name",
            ):
                self._service.register_tool_name(name)

    def _log_config_issue(self, issue: str) -> None:
        if not self._availability_warning_emitted:
            _LOGGER.warning(
                "Local learning is unavailable because %s is invalid.",
                issue,
            )
            self._availability_warning_emitted = True

    def _log_runtime_fault(self, error: BaseException) -> None:
        if not self._availability_warning_emitted:
            _LOGGER.warning(
                "Local learning is unavailable after %s.",
                type(error).__name__,
            )
            self._availability_warning_emitted = True

    def _log_automatic_fault(self, error: BaseException) -> None:
        if not self._automatic_warning_emitted:
            _LOGGER.warning(
                "Automatic learning recording disabled after %s.",
                type(error).__name__,
            )
            self._automatic_warning_emitted = True

    def _ensure_service(self) -> LearningService | None:
        with self._lock:
            if self._service is not None:
                return self._service  # type: ignore[return-value]
            if self._unavailable:
                return None
            if not self._config_loaded:
                self._config_loaded = True
                try:
                    config = self._config_loader()
                    enabled = bool(config.enabled)
                    issue = config.issue
                except Exception as error:
                    self._unavailable = True
                    self._log_runtime_fault(error)
                    return None
                self._config = config
                if not enabled:
                    return None
                if issue is not None:
                    self._config_issue = issue
                    self._log_config_issue(issue)
                    return None

            if self._config is None:
                return None
            if not self._config.enabled or self._config_issue is not None:
                return None
            try:
                service = LearningService(self._config)
                for name in self._registered_tool_names:
                    service.register_tool_name(name)
            except Exception as error:
                self._unavailable = True
                self._log_runtime_fault(error)
                return None
            self._service = service
            return service

    def _learning_enabled(self) -> bool:
        return True if self._config is None else bool(self._config.enabled)

    def _unavailable_result(self) -> dict[str, object]:
        return {
            "recorded": False,
            "learning_enabled": self._learning_enabled(),
            "learning_available": False,
            "immediate_attention": False,
        }

    def _disabled_review(self) -> dict[str, object]:
        return {
            "learning_enabled": False,
            "learning_available": False,
            "counts": {
                "invocations": 0,
                "goal_failures": 0,
                "review_markers": 0,
            },
            "attention_required": False,
            "candidates": [],
        }

    def _unavailable_error(self, operation: str) -> BackendError:
        details = (
            {"setting": self._config_issue}
            if self._config_issue is not None
            else {}
        )
        return BackendError(
            "LEARNING_UNAVAILABLE",
            "Local learning is unavailable.",
            "learning",
            operation,
            details=details,
        )

    def record_invocation(
        self,
        *,
        tool_name: str,
        duration_ms: int,
        outcome: InvocationOutcome,
        error_code: str | None,
        retryable: bool | None,
        backend: str | None,
        pscad_version: str | None,
    ) -> None:
        with self._lock:
            if self._automatic_recording_disabled:
                return
        try:
            service = self._ensure_service()
            if service is None:
                return
            service.record_invocation(
                tool_name=tool_name,
                duration_ms=duration_ms,
                outcome=outcome,
                error_code=error_code,
                retryable=retryable,
                backend=backend,
                pscad_version=pscad_version,
            )
        except Exception as error:
            with self._lock:
                self._automatic_recording_disabled = True
                self._log_automatic_fault(error)

    def record_goal_failure(
        self,
        failure_kind: GoalFailureKind,
        primary_tool: str | None,
    ) -> dict[str, object]:
        service = self._ensure_service()
        if service is None:
            if self._config is not None and not self._config.enabled:
                return {
                    "recorded": False,
                    "learning_enabled": False,
                }
            return self._unavailable_result()
        try:
            return service.record_goal_failure(failure_kind, primary_tool)
        except BackendError:
            raise
        except Exception as error:
            with self._lock:
                self._unavailable = True
                self._log_runtime_fault(error)
            return self._unavailable_result()

    def review(
        self,
        *,
        limit: int,
        min_evidence: int,
        mark_notified: bool,
    ) -> dict[str, object]:
        LearningService._validate_review_bounds(limit, min_evidence)
        service = self._ensure_service()
        if service is None:
            if self._config is not None and not self._config.enabled:
                return self._disabled_review()
            raise self._unavailable_error("review")
        try:
            return service.review(
                limit=limit,
                min_evidence=min_evidence,
                mark_notified=mark_notified,
            )
        except BackendError:
            raise
        except Exception as error:
            with self._lock:
                self._unavailable = True
                self._log_runtime_fault(error)
            raise self._unavailable_error("review") from None

    def clear(self, *, confirm: bool) -> dict[str, object]:
        if not confirm:
            raise ConfirmationRequired("clear_learning_history")
        service = self._ensure_service()
        if service is None:
            if self._config is not None and not self._config.enabled:
                return {
                    "cleared": False,
                    "learning_enabled": False,
                }
            raise self._unavailable_error("clear_learning_history")
        try:
            cleared = service.clear(confirm=True)
        except BackendError:
            raise
        except Exception as error:
            with self._lock:
                self._unavailable = True
                self._log_runtime_fault(error)
            raise self._unavailable_error("clear_learning_history") from None
        return {
            "cleared": bool(cleared),
            "learning_enabled": True,
        }


learning_runtime = LearningRuntime()
