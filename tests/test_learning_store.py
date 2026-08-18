from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import sqlite3
import time

import pytest

from pscad_mcp.learning.models import (
    GoalFailureEvent,
    GoalFailureKind,
    InvocationEvent,
    InvocationOutcome,
    ReviewMarker,
)
from pscad_mcp.learning.store import LearningStore, UnsupportedLearningSchema


def test_store_round_trips_scalar_invocation_and_goal_failure(tmp_path):
    database = tmp_path / "learning.sqlite3"
    store = LearningStore(database)
    invocation_id = store.record_invocation(
        InvocationEvent(
            occurred_at="2026-08-19T01:00:00+00:00",
            session_id="session-a",
            tool_name="run_project",
            duration_ms=125,
            outcome=InvocationOutcome.ERROR,
            error_code="TIMEOUT",
            retryable=True,
            backend="legacy",
            pscad_version="4.6.2",
        )
    )
    goal_id = store.record_goal_failure(
        GoalFailureEvent(
            occurred_at="2026-08-19T01:01:00+00:00",
            session_id="session-a",
            failure_kind=GoalFailureKind.RECOVERY_FAILED,
            primary_tool="run_project",
            correlated_invocation_id=invocation_id,
        )
    )
    invocations = store.load_invocations("2026-08-01T00:00:00+00:00")
    failures = store.load_goal_failures("2026-08-01T00:00:00+00:00")
    assert invocation_id == 1
    assert goal_id == 1
    assert invocations[0].error_code == "TIMEOUT"
    assert invocations[0].retryable is True
    assert failures[0].failure_kind is GoalFailureKind.RECOVERY_FAILED
    assert failures[0].correlated_invocation_id == invocation_id
    store.close()


def test_schema_has_no_arbitrary_payload_columns(tmp_path):
    database = tmp_path / "learning.sqlite3"
    LearningStore(database).close()
    with sqlite3.connect(database) as connection:
        invocation_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(tool_invocations)")
        }
        failure_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(goal_failures)")
        }
    forbidden = {
        "args", "kwargs", "result", "message", "details",
        "traceback", "payload", "json",
    }
    assert forbidden.isdisjoint(invocation_columns)
    assert forbidden.isdisjoint(failure_columns)


def test_schema_metadata_is_versioned_and_future_schema_is_unchanged(tmp_path):
    database = tmp_path / "learning.sqlite3"
    LearningStore(database).close()
    with sqlite3.connect(database) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM schema_metadata"))
    assert metadata["schema_version"] == "1"
    assert metadata["created_at"].endswith("+00:00")

    future = tmp_path / "future.sqlite3"
    with sqlite3.connect(future) as connection:
        connection.execute(
            "CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_metadata VALUES ('schema_version', '99')"
        )
    before = future.read_bytes()
    with pytest.raises(UnsupportedLearningSchema):
        LearningStore(future)
    assert future.read_bytes() == before


def test_busy_writer_fails_within_the_configured_bound(tmp_path):
    database = tmp_path / "learning.sqlite3"
    store = LearningStore(database)
    blocker = sqlite3.connect(database, timeout=0)
    blocker.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    try:
        with pytest.raises(sqlite3.OperationalError):
            store.record_invocation(
                InvocationEvent(
                    occurred_at="2026-08-19T01:00:00+00:00",
                    session_id="session-a",
                    tool_name="run_project",
                    duration_ms=1,
                    outcome=InvocationOutcome.SUCCESS,
                    error_code=None,
                    retryable=None,
                    backend=None,
                    pscad_version=None,
                )
            )
    finally:
        blocker.rollback()
        blocker.close()
        store.close()
    assert time.monotonic() - started < 0.5


def test_shared_store_serializes_concurrent_short_writes(tmp_path):
    store = LearningStore(tmp_path / "learning.sqlite3")

    def write(index):
        return store.record_invocation(
            InvocationEvent(
                occurred_at=f"2026-08-19T01:00:{index:02d}+00:00",
                session_id="session-a",
                tool_name="run_project",
                duration_ms=index,
                outcome=InvocationOutcome.SUCCESS,
                error_code=None,
                retryable=None,
                backend="legacy",
                pscad_version="4.6.2",
            )
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        identifiers = list(pool.map(write, range(20)))
    assert sorted(identifiers) == list(range(1, 21))
    assert len(store.load_invocations("2020-01-01T00:00:00+00:00")) == 20
    store.close()


def _invocation(at: str, tool: str = "run_project") -> InvocationEvent:
    return InvocationEvent(
        occurred_at=at,
        session_id="session-a",
        tool_name=tool,
        duration_ms=1,
        outcome=InvocationOutcome.ERROR,
        error_code="TIMEOUT",
        retryable=True,
        backend="legacy",
        pscad_version="4.6.2",
    )


def test_prune_applies_age_then_combined_event_limit(tmp_path):
    store = LearningStore(tmp_path / "learning.sqlite3")
    store.record_invocation(_invocation("2026-01-01T00:00:00+00:00"))
    for minute in range(5):
        store.record_invocation(_invocation(f"2026-08-19T00:0{minute}:00+00:00"))
    store.prune(
        now=datetime(2026, 8, 19, 1, 0, tzinfo=timezone.utc),
        retention_days=90,
        max_events=3,
    )
    rows = store.load_invocations("2020-01-01T00:00:00+00:00")
    assert [row.occurred_at for row in rows] == [
        "2026-08-19T00:02:00+00:00",
        "2026-08-19T00:03:00+00:00",
        "2026-08-19T00:04:00+00:00",
    ]


def test_review_markers_round_trip_and_clear(tmp_path):
    store = LearningStore(tmp_path / "learning.sqlite3")
    fingerprint = "a" * 64
    marker = ReviewMarker(
        fingerprint=fingerprint,
        first_notified_at="2026-08-19T01:00:00+00:00",
        last_notified_at="2026-08-19T01:00:00+00:00",
        notification_source="scheduled",
        evidence_watermark="b" * 64,
    )
    store.mark_notified([marker])
    assert store.load_review_markers()[fingerprint].evidence_watermark == "b" * 64
    store.clear_history()
    assert store.load_invocations("2020-01-01T00:00:00+00:00") == []
    assert store.load_goal_failures("2020-01-01T00:00:00+00:00") == []
    assert store.load_review_markers() == {}


def test_latest_session_invocation_can_be_correlated_without_content(tmp_path):
    store = LearningStore(tmp_path / "learning.sqlite3")
    first = store.record_invocation(_invocation("2026-08-19T00:00:00+00:00", "build_project"))
    latest = store.record_invocation(_invocation("2026-08-19T00:01:00+00:00", "run_project"))
    latest_row = store.latest_invocation("session-a", None)
    build_row = store.latest_invocation("session-a", "build_project")
    assert latest_row is not None and latest_row.event_id == latest
    assert build_row is not None and build_row.event_id == first
    assert store.has_failure_evidence("run_project") is True


def test_retention_runs_once_per_utc_day_and_nulls_expired_correlation(tmp_path):
    database = tmp_path / "learning.sqlite3"
    store = LearningStore(database)
    old_id = store.record_invocation(_invocation("2026-01-01T00:00:00+00:00"))
    store.record_goal_failure(
        GoalFailureEvent(
            occurred_at="2026-08-19T00:00:00+00:00",
            session_id="session-a",
            failure_kind=GoalFailureKind.RECOVERY_FAILED,
            primary_tool="run_project",
            correlated_invocation_id=old_id,
        )
    )
    now = datetime(2026, 8, 19, 1, 0, tzinfo=timezone.utc)
    assert store.prune(now=now, retention_days=90, max_events=100) is True
    assert store.load_goal_failures("2020-01-01T00:00:00+00:00")[0].correlated_invocation_id is None
    store.record_invocation(_invocation("2026-01-02T00:00:00+00:00"))
    assert store.prune(now=now, retention_days=90, max_events=100) is False
    assert len(store.load_invocations("2020-01-01T00:00:00+00:00")) == 1
    store.close()
    with sqlite3.connect(database) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM schema_metadata"))
    assert metadata["last_retention_pass"].startswith("2026-08-19T")


def test_review_markers_without_remaining_candidate_evidence_are_removed(tmp_path):
    store = LearningStore(tmp_path / "learning.sqlite3")
    keep = "a" * 64
    drop = "b" * 64
    timestamp = "2026-08-19T01:00:00+00:00"
    markers = [
        ReviewMarker(keep, timestamp, timestamp, "scheduled", "c" * 64),
        ReviewMarker(drop, timestamp, timestamp, "scheduled", "c" * 64),
    ]
    store.mark_notified(markers)
    store.delete_review_markers_except({keep})
    assert set(store.load_review_markers()) == {keep}
