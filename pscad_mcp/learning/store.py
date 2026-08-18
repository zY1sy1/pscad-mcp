from __future__ import annotations

from datetime import datetime, timezone
from os import PathLike
from pathlib import Path
import sqlite3
import threading
from typing import Any

from .models import (
    GoalFailureEvent,
    GoalFailureKind,
    InvocationEvent,
    InvocationOutcome,
    StoredGoalFailure,
    StoredInvocation,
)


class UnsupportedLearningSchema(RuntimeError):
    """Raised when a database uses a schema newer than this implementation."""


_SCHEMA_VERSION = "1"
_BUSY_TIMEOUT_MS = 50

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS schema_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_invocations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        occurred_at TEXT NOT NULL CHECK(length(occurred_at) BETWEEN 20 AND 40),
        session_id TEXT NOT NULL CHECK(length(session_id) BETWEEN 1 AND 64),
        tool_name TEXT NOT NULL CHECK(length(tool_name) BETWEEN 1 AND 128),
        duration_ms INTEGER NOT NULL CHECK(duration_ms >= 0),
        outcome TEXT NOT NULL CHECK(outcome IN ('success', 'error')),
        error_code TEXT CHECK(error_code IS NULL OR length(error_code) BETWEEN 1 AND 64),
        retryable INTEGER CHECK(retryable IN (0, 1) OR retryable IS NULL),
        backend TEXT CHECK(backend IS NULL OR length(backend) BETWEEN 1 AND 32),
        pscad_version TEXT CHECK(
            pscad_version IS NULL OR length(pscad_version) BETWEEN 1 AND 32
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tool_invocations_time
        ON tool_invocations(occurred_at, id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tool_invocations_group
        ON tool_invocations(tool_name, error_code, occurred_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS goal_failures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        occurred_at TEXT NOT NULL CHECK(length(occurred_at) BETWEEN 20 AND 40),
        session_id TEXT NOT NULL CHECK(length(session_id) BETWEEN 1 AND 64),
        failure_kind TEXT NOT NULL CHECK(failure_kind IN (
            'unsupported_operation', 'incorrect_result', 'incomplete_result',
            'environment_blocked', 'recovery_failed', 'unknown'
        )),
        primary_tool TEXT CHECK(
            primary_tool IS NULL OR length(primary_tool) BETWEEN 1 AND 128
        ),
        correlated_invocation_id INTEGER REFERENCES tool_invocations(id)
            ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_goal_failures_time
        ON goal_failures(occurred_at, id)
    """,
    """
    CREATE TABLE IF NOT EXISTS candidate_reviews (
        fingerprint TEXT PRIMARY KEY CHECK(length(fingerprint) = 64),
        first_notified_at TEXT NOT NULL CHECK(length(first_notified_at) BETWEEN 20 AND 40),
        last_notified_at TEXT NOT NULL CHECK(length(last_notified_at) BETWEEN 20 AND 40),
        notification_source TEXT NOT NULL CHECK(notification_source IN ('foreground', 'scheduled')),
        evidence_watermark TEXT NOT NULL CHECK(length(evidence_watermark) = 64)
    )
    """,
)


class LearningStore:
    def __init__(self, database: str | PathLike[str]) -> None:
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        database_name = str(database)
        if database_name != ":memory:":
            Path(database_name).parent.mkdir(parents=True, exist_ok=True)

        connection = sqlite3.connect(
            database_name,
            timeout=0.05,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        try:
            with self._lock:
                schema_version = self._inspect_schema_version(connection)
                self._configure_connection(connection)
                self._initialize_schema(connection, schema_version is None)
        except Exception:
            connection.close()
            raise
        self._connection = connection

    @staticmethod
    def _inspect_schema_version(connection: sqlite3.Connection) -> str | None:
        metadata_table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_metadata'
            """
        ).fetchone()
        if metadata_table is None:
            existing_object = connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type IN ('table', 'index', 'trigger', 'view')
                  AND name NOT LIKE 'sqlite_%'
                LIMIT 1
                """
            ).fetchone()
            if existing_object is not None:
                raise UnsupportedLearningSchema("schema metadata is missing")
            return None

        version_row = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = ?",
            ("schema_version",),
        ).fetchone()
        schema_version = None if version_row is None else version_row[0]
        if schema_version != _SCHEMA_VERSION:
            raise UnsupportedLearningSchema(
                f"unsupported learning schema version: {schema_version!r}"
            )
        return schema_version

    @staticmethod
    def _configure_connection(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        try:
            connection.execute("PRAGMA journal_mode = WAL").fetchone()
        except sqlite3.OperationalError:
            # SQLite builds or filesystems that cannot use WAL still work in rollback mode.
            pass

    @staticmethod
    def _initialize_schema(
        connection: sqlite3.Connection,
        is_new_database: bool,
    ) -> None:
        connection.execute("BEGIN")
        try:
            for statement in _SCHEMA_STATEMENTS:
                connection.execute(statement)
            if is_new_database:
                connection.executemany(
                    "INSERT INTO schema_metadata (key, value) VALUES (?, ?)",
                    (
                        ("schema_version", _SCHEMA_VERSION),
                        ("created_at", datetime.now(timezone.utc).isoformat()),
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise sqlite3.ProgrammingError("LearningStore is closed")
        return self._connection

    @staticmethod
    def _sqlite_bool(value: Any) -> bool | None:
        return None if value is None else bool(value)

    def record_invocation(self, event: InvocationEvent) -> int:
        with self._lock:
            connection = self._require_connection()
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO tool_invocations (
                        occurred_at,
                        session_id,
                        tool_name,
                        duration_ms,
                        outcome,
                        error_code,
                        retryable,
                        backend,
                        pscad_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.occurred_at,
                        event.session_id,
                        event.tool_name,
                        event.duration_ms,
                        event.outcome.value,
                        event.error_code,
                        None if event.retryable is None else int(event.retryable),
                        event.backend,
                        event.pscad_version,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            return int(cursor.lastrowid)

    def record_goal_failure(self, event: GoalFailureEvent) -> int:
        with self._lock:
            connection = self._require_connection()
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO goal_failures (
                        occurred_at,
                        session_id,
                        failure_kind,
                        primary_tool,
                        correlated_invocation_id
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        event.occurred_at,
                        event.session_id,
                        event.failure_kind.value,
                        event.primary_tool,
                        event.correlated_invocation_id,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            return int(cursor.lastrowid)

    def load_invocations(self, since: str) -> list[StoredInvocation]:
        with self._lock:
            connection = self._require_connection()
            rows = connection.execute(
                """
                SELECT id, occurred_at, session_id, tool_name, duration_ms,
                       outcome, error_code, retryable, backend, pscad_version
                FROM tool_invocations
                WHERE occurred_at >= ?
                ORDER BY occurred_at, id
                """,
                (since,),
            ).fetchall()
            return [
                StoredInvocation(
                    event_id=row["id"],
                    occurred_at=row["occurred_at"],
                    session_id=row["session_id"],
                    tool_name=row["tool_name"],
                    duration_ms=row["duration_ms"],
                    outcome=InvocationOutcome(row["outcome"]),
                    error_code=row["error_code"],
                    retryable=self._sqlite_bool(row["retryable"]),
                    backend=row["backend"],
                    pscad_version=row["pscad_version"],
                )
                for row in rows
            ]

    def load_goal_failures(self, since: str) -> list[StoredGoalFailure]:
        with self._lock:
            connection = self._require_connection()
            rows = connection.execute(
                """
                SELECT id, occurred_at, session_id, failure_kind,
                       primary_tool, correlated_invocation_id
                FROM goal_failures
                WHERE occurred_at >= ?
                ORDER BY occurred_at, id
                """,
                (since,),
            ).fetchall()
            return [
                StoredGoalFailure(
                    event_id=row["id"],
                    occurred_at=row["occurred_at"],
                    session_id=row["session_id"],
                    failure_kind=GoalFailureKind(row["failure_kind"]),
                    primary_tool=row["primary_tool"],
                    correlated_invocation_id=row["correlated_invocation_id"],
                )
                for row in rows
            ]

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
