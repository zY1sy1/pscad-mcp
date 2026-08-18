from concurrent.futures import ThreadPoolExecutor
import sqlite3
import time

import pytest

from pscad_mcp.learning.models import (
    GoalFailureEvent,
    GoalFailureKind,
    InvocationEvent,
    InvocationOutcome,
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
