# PSCAD MCP Silent Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local, privacy-bounded learning loop that records PSCAD MCP outcome metadata silently, maintains a generated Markdown failure backlog, exposes three review tools, and reminds the user only for critical or scheduled actionable findings.

**Architecture:** The existing shared FastMCP registration wrapper extracts scalar outcome metadata and sends it to a fail-open learning runtime. SQLite is the source of truth; a deterministic candidate engine and atomic Markdown renderer produce the review backlog. Normal operation stays silent, approved remediation is driven by a repository skill, and a Codex heartbeat reviews findings every Monday at 09:00 in `Asia/Shanghai`.

**Tech Stack:** Python 3.10+, FastMCP, standard-library `sqlite3`, `dataclasses`, `enum`, `hashlib`, `threading`, `pathlib`, pytest/unittest, PowerShell packaging verification, Codex skills and heartbeat automations.

---

## Source Specification

Implement `docs/superpowers/specs/2026-08-19-pscad-mcp-silent-learning-design.md` as committed alongside this plan. Commit `6bfac92` is the originally accepted design; the plan commit clarifies Codex-heartbeat scheduling and that unreproduced candidates stay untouched in the generated backlog while remediation reports them as `needs_evidence`.

The pre-change baseline is:

```text
532 passed, 18 skipped, 127 subtests passed
```

## File Map

Create these focused production modules:

- `pscad_mcp/learning/__init__.py`: stable package exports.
- `pscad_mcp/learning/config.py`: environment parsing and local state paths.
- `pscad_mcp/learning/models.py`: closed enums and immutable scalar records.
- `pscad_mcp/learning/store.py`: SQLite schema, writes, retention, and review watermarks.
- `pscad_mcp/learning/candidates.py`: deterministic candidate aggregation.
- `pscad_mcp/learning/markdown.py`: atomic generated backlog rendering.
- `pscad_mcp/learning/service.py`: orchestration, validation, and lazy runtime.
- `pscad_mcp/learning/recorder.py`: fail-open recorder used by tool wrappers.
- `pscad_mcp/tools/learning_tools.py`: three MCP-facing learning operations.
- `.agents/skills/pscad-mcp-improver/SKILL.md`: review and approved remediation workflow.
- `.agents/skills/pscad-mcp-improver/references/scheduled-review.md`: durable heartbeat prompt.

Modify these existing boundaries:

- `pscad_mcp/tools/registration.py`: collect scalar outcome metadata.
- `pscad_mcp/core/service.py`: add a non-I/O backend snapshot and learning error guidance.
- `pscad_mcp/core/connection_manager.py`: expose the snapshot to registration.
- `pscad_mcp/main.py`: add server instructions and register learning tools.
- `config.example.toml`, `mcp_installer.py`, `README.md`, `docs/zh-CN/README.md`, `CHANGELOG.md`, and `.gitignore`: configure and document the feature.
- Tool inventory checks in `tests`, `.github/workflows/ci.yml`, and `scripts/verify_package.ps1`: move the exact count from 70 to 73 while preserving 60 generic and 10 HVDC tools.

## Execution Preconditions

- [ ] **Step 1: Create an isolated implementation workspace**

Use the `using-git-worktrees` skill at execution time. Start from the commit containing this plan and use a `codex/` branch. The verification task derives that implementation base from the commit that added this plan, so no mutable tag or untracked marker file is needed. Do not run the scheduled heartbeat against an uncommitted implementation.

- [ ] **Step 2: Confirm the clean baseline**

Run:

```powershell
git status --short
& .\.venv\Scripts\python.exe -m pytest -q
```

Expected: no unrelated changes and a green baseline. If the repository moves forward, record its new green baseline before continuing.

---

### Task 1: Add Closed Learning Configuration And Data Contracts

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_learning_config.py`
- Create: `pscad_mcp/learning/__init__.py`
- Create: `pscad_mcp/learning/config.py`
- Create: `pscad_mcp/learning/models.py`

- [ ] **Step 1: Disable real learning state for the test package**

Create `tests/__init__.py` before any test imports the package:

```python
import os


os.environ.setdefault("PSCAD_MCP_LEARNING_ENABLED", "false")
```

This protects pytest and `python -m unittest discover tests` from writing synthetic events to the user's real local database. Individual learning tests construct explicit configurations and remain enabled.

- [ ] **Step 2: Write failing configuration and closed-model tests**

Create `tests/test_learning_config.py`:

```python
from pscad_mcp.learning.config import LearningConfig
from pscad_mcp.learning.models import (
    CandidateKind,
    CandidateState,
    GoalFailureKind,
    InvocationOutcome,
)


def test_learning_defaults_to_enabled_local_state(tmp_path):
    config = LearningConfig.from_environ(
        {"LOCALAPPDATA": str(tmp_path)},
        home=tmp_path,
    )
    assert config.enabled is True
    assert config.available is True
    assert config.database_path == tmp_path / "pscad-mcp" / "learning.sqlite3"
    assert config.backlog_path == tmp_path / "pscad-mcp" / "improvement-backlog.md"
    assert config.retention_days == 90
    assert config.max_events == 20_000
    assert config.issue is None


def test_explicit_disable_ignores_other_learning_settings(tmp_path):
    config = LearningConfig.from_environ(
        {
            "PSCAD_MCP_LEARNING_ENABLED": "false",
            "PSCAD_MCP_LEARNING_DB": "relative.sqlite3",
            "PSCAD_MCP_LEARNING_RETENTION_DAYS": "invalid",
        },
        home=tmp_path,
    )
    assert config.enabled is False
    assert config.available is False
    assert config.issue is None


def test_invalid_enabled_configuration_fails_closed_for_learning_only(tmp_path):
    config = LearningConfig.from_environ(
        {
            "LOCALAPPDATA": str(tmp_path),
            "PSCAD_MCP_LEARNING_ENABLED": "true",
            "PSCAD_MCP_LEARNING_DB": "relative.sqlite3",
        },
        home=tmp_path,
    )
    assert config.enabled is True
    assert config.available is False
    assert config.issue == "PSCAD_MCP_LEARNING_DB"


def test_database_and_backlog_cannot_target_the_same_file(tmp_path):
    shared = tmp_path / "shared-state"
    config = LearningConfig.from_environ(
        {
            "PSCAD_MCP_LEARNING_DB": str(shared),
            "PSCAD_MCP_LEARNING_BACKLOG": str(shared),
        },
        home=tmp_path,
    )
    assert config.available is False
    assert config.issue == "PSCAD_MCP_LEARNING_BACKLOG"


def test_absolute_database_and_backlog_overrides_are_preserved(tmp_path):
    database = tmp_path / "state" / "custom.sqlite3"
    backlog = tmp_path / "review" / "custom.md"
    config = LearningConfig.from_environ(
        {
            "PSCAD_MCP_LEARNING_DB": str(database),
            "PSCAD_MCP_LEARNING_BACKLOG": str(backlog),
        },
        home=tmp_path,
    )
    assert config.available is True
    assert config.database_path == database
    assert config.backlog_path == backlog


def test_state_directory_prefers_xdg_then_falls_back_to_home(tmp_path):
    xdg = tmp_path / "xdg"
    from_xdg = LearningConfig.from_environ(
        {"XDG_STATE_HOME": str(xdg)},
        home=tmp_path,
    )
    from_home = LearningConfig.from_environ({}, home=tmp_path)
    assert from_xdg.database_path.parent == xdg / "pscad-mcp"
    assert from_home.database_path.parent == tmp_path / ".pscad-mcp"


def test_learning_enablement_accepts_only_documented_boolean_spellings(tmp_path):
    for raw in ("1", "true", "yes", "on"):
        config = LearningConfig.from_environ(
            {"PSCAD_MCP_LEARNING_ENABLED": raw}, home=tmp_path
        )
        assert config.enabled is True and config.issue is None
    for raw in ("0", "false", "no", "off"):
        config = LearningConfig.from_environ(
            {"PSCAD_MCP_LEARNING_ENABLED": raw}, home=tmp_path
        )
        assert config.enabled is False and config.issue is None


def test_invalid_enablement_fails_closed_without_echoing_its_value(tmp_path):
    config = LearningConfig.from_environ(
        {"PSCAD_MCP_LEARNING_ENABLED": "SECRET_INVALID_BOOLEAN"},
        home=tmp_path,
    )
    assert config.enabled is True
    assert config.available is False
    assert config.issue == "PSCAD_MCP_LEARNING_ENABLED"


def test_learning_numeric_limits_are_bounded(tmp_path):
    for variable, value in (
        ("PSCAD_MCP_LEARNING_RETENTION_DAYS", "0"),
        ("PSCAD_MCP_LEARNING_RETENTION_DAYS", "3651"),
        ("PSCAD_MCP_LEARNING_MAX_EVENTS", "99"),
        ("PSCAD_MCP_LEARNING_MAX_EVENTS", "1000001"),
    ):
        config = LearningConfig.from_environ(
            {"LOCALAPPDATA": str(tmp_path), variable: value},
            home=tmp_path,
        )
        assert config.available is False
        assert config.issue == variable


def test_learning_enums_have_only_approved_values():
    assert {item.value for item in InvocationOutcome} == {"success", "error"}
    assert {item.value for item in GoalFailureKind} == {
        "unsupported_operation",
        "incorrect_result",
        "incomplete_result",
        "environment_blocked",
        "recovery_failed",
        "unknown",
    }
    assert {item.value for item in CandidateKind} == {
        "reliability", "correctness", "capability", "guidance", "efficiency"
    }
    assert {item.value for item in CandidateState} == {
        "open", "reopened", "notified", "resolved_by_later_evidence"
    }
```

- [ ] **Step 3: Run the tests and verify the missing package failure**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_config.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'pscad_mcp.learning'`.

- [ ] **Step 4: Implement the immutable model surface**

Create `pscad_mcp/learning/models.py`:

```python
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
```

Create `pscad_mcp/learning/__init__.py`:

```python
from .config import LearningConfig
from .models import CandidateKind, CandidateState, GoalFailureKind


__all__ = [
    "CandidateKind",
    "CandidateState",
    "GoalFailureKind",
    "LearningConfig",
]
```

- [ ] **Step 5: Implement fail-closed ancillary configuration**

Create `pscad_mcp/learning/config.py` with a frozen `LearningConfig` containing `enabled`, `database_path`, `backlog_path`, `retention_days`, `max_events`, and `issue`. `available` is a property equal to `enabled and issue is None`.

Use these parsing rules:

```python
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_RETENTION_MIN = 1
_RETENTION_MAX = 3650
_EVENT_LIMIT_MIN = 100
_EVENT_LIMIT_MAX = 1_000_000


def _state_directory(values: Mapping[str, str], home: Path) -> Path:
    local = values.get("LOCALAPPDATA", "").strip()
    if local and Path(local).is_absolute():
        return Path(local) / "pscad-mcp"
    xdg = values.get("XDG_STATE_HOME", "").strip()
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / "pscad-mcp"
    return home / ".pscad-mcp"


def _absolute_override(
    values: Mapping[str, str],
    variable: str,
    default: Path,
) -> tuple[Path, str | None]:
    raw = values.get(variable, "").strip()
    if not raw:
        return default, None
    candidate = Path(raw)
    if not candidate.is_absolute():
        return default, variable
    return candidate, None
```

Parse enablement first. Explicit disablement returns before validating other learning settings. An unrecognized enablement value keeps `enabled=True` to distinguish it from intentional disablement but fails closed with `issue="PSCAD_MCP_LEARNING_ENABLED"`. Any other invalid enabled configuration records only the first environment variable name in `issue`, never its value. Reject identical normalized database and backlog paths with `issue="PSCAD_MCP_LEARNING_BACKLOG"`; this prevents Markdown replacement from corrupting SQLite. Parsing constructs paths but creates no directory or file.

- [ ] **Step 6: Run the focused tests**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_config.py -q
```

Expected: all tests pass and no real learning file is created.

- [ ] **Step 7: Commit the contracts**

```powershell
git add tests\__init__.py tests\test_learning_config.py pscad_mcp\learning
git commit -m "feat: add learning configuration contracts"
```

---

### Task 2: Persist Typed Events In SQLite

**Files:**
- Create: `tests/test_learning_store.py`
- Create: `pscad_mcp/learning/store.py`

- [ ] **Step 1: Write failing schema and round-trip tests**

Create `tests/test_learning_store.py`:

```python
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
```

- [ ] **Step 2: Verify the missing store failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_store.py -q
```

Expected: collection fails because `pscad_mcp.learning.store` does not exist.

- [ ] **Step 3: Create the schema and connection discipline**

Create `pscad_mcp/learning/store.py` with this schema:

```sql
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
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
);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_time
    ON tool_invocations(occurred_at, id);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_group
    ON tool_invocations(tool_name, error_code, occurred_at);
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
);
CREATE INDEX IF NOT EXISTS idx_goal_failures_time
    ON goal_failures(occurred_at, id);
CREATE TABLE IF NOT EXISTS candidate_reviews (
    fingerprint TEXT PRIMARY KEY CHECK(length(fingerprint) = 64),
    first_notified_at TEXT NOT NULL CHECK(length(first_notified_at) BETWEEN 20 AND 40),
    last_notified_at TEXT NOT NULL CHECK(length(last_notified_at) BETWEEN 20 AND 40),
    notification_source TEXT NOT NULL CHECK(notification_source IN ('foreground', 'scheduled')),
    evidence_watermark TEXT NOT NULL CHECK(length(evidence_watermark) = 64)
);
```

Open SQLite with `timeout=0.05`, `check_same_thread=False`, `sqlite3.Row`, foreign keys, a 50 ms busy timeout, and WAL mode where supported. Guard connection use with one `threading.RLock`.

Before setting WAL mode or applying schema version 1, inspect an existing `schema_metadata` table using read-only SQL. Raise `UnsupportedLearningSchema`, close the connection, and leave the database bytes unchanged when its version is not `1`. On a new database, create all objects and insert `schema_version=1` plus an ISO-8601 UTC `created_at` transactionally. `last_retention_pass` is added only after a successful retention transaction.

- [ ] **Step 4: Implement typed writes and reads**

Implement:

```python
def record_invocation(self, event: InvocationEvent) -> int
def record_goal_failure(self, event: GoalFailureEvent) -> int
def load_invocations(self, since: str) -> list[StoredInvocation]
def load_goal_failures(self, since: str) -> list[StoredGoalFailure]
def close(self) -> None
```

Convert enums to values on insert and reconstruct them on read. Convert SQLite booleans to `bool | None`. Order reads by `occurred_at, id`.

- [ ] **Step 5: Run the store tests**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_store.py -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit SQLite persistence**

```powershell
git add tests\test_learning_store.py pscad_mcp\learning\store.py
git commit -m "feat: persist local learning events"
```

---

### Task 3: Add Retention, Correlation, Review Watermarks, And Clearing

**Files:**
- Modify: `tests/test_learning_store.py`
- Modify: `pscad_mcp/learning/store.py`

- [ ] **Step 1: Add failing lifecycle tests**

Append:

```python
from datetime import datetime, timezone

from pscad_mcp.learning.models import ReviewMarker


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
```

- [ ] **Step 2: Run and verify missing-method failures**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_store.py -q
```

Expected: existing tests pass and new tests fail on missing lifecycle methods.

- [ ] **Step 3: Implement lifecycle methods**

Add:

```python
from collections.abc import Collection, Sequence


def prune(self, *, now: datetime, retention_days: int, max_events: int) -> bool
def mark_notified(self, markers: Sequence[ReviewMarker]) -> None
def load_review_markers(self) -> dict[str, ReviewMarker]
def delete_review_markers_except(self, fingerprints: Collection[str]) -> None
def latest_invocation(
    self,
    session_id: str,
    tool_name: str | None,
) -> StoredInvocation | None
def has_failure_evidence(self, tool_name: str) -> bool
def counts(self) -> dict[str, int]
def clear_history(self) -> None
```

`prune()` starts `BEGIN IMMEDIATE`, compares the stored `last_retention_pass` UTC date, and returns `False` without deleting when that date is today. Otherwise, delete by age; for the combined cap, select event type, ID, and time from a `UNION ALL`, order oldest first, and delete exactly the excess rows. Update `last_retention_pass` only in the successful transaction and return `True`. `ON DELETE SET NULL` preserves goal failures whose correlated invocation expires.

`mark_notified` uses an upsert, preserves `first_notified_at`, and updates the remaining fields. `delete_review_markers_except` uses a parameterized temporary table or individual parameterized deletes, and handles an empty set by deleting all markers; it never interpolates fingerprints into SQL. `counts()` returns exactly `invocations`, `goal_failures`, and `review_markers`. Clearing transactionally deletes all three data tables, preserves schema metadata, then runs `PRAGMA wal_checkpoint(TRUNCATE)` and `VACUUM` outside the transaction.

- [ ] **Step 4: Re-run tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_store.py -q
git add tests\test_learning_store.py pscad_mcp\learning\store.py
git commit -m "feat: manage learning retention and reviews"
```

Expected: all store tests pass before the commit.

---

### Task 4: Aggregate Deterministic Improvement Candidates

**Files:**
- Create: `tests/test_learning_candidates.py`
- Create: `pscad_mcp/learning/candidates.py`

- [ ] **Step 1: Write failing candidate tests**

Create `tests/test_learning_candidates.py`:

```python
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
```

- [ ] **Step 2: Verify the missing engine failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_candidates.py -q
```

Expected: collection fails because `pscad_mcp.learning.candidates` is absent.

- [ ] **Step 3: Implement grouping, identity, scoring, and state**

Create `pscad_mcp/learning/candidates.py` with these constants and identity functions:

```python
_RELIABILITY_CODES = frozenset({
    "TIMEOUT",
    "EXECUTOR_UNHEALTHY",
    "INTERNAL_ERROR",
    "PARTIAL_COMPLETION",
    "REPAIR_CLEANUP_FAILED",
})
_GUIDANCE_CODES = frozenset({
    "INVALID_ARGUMENT",
    "NOT_FOUND",
    "WORKSPACE_NOT_CONFIGURED",
    "NOT_CONNECTED",
    "EXTERNAL_PSCAD_PRESENT",
    "NOT_LICENSED",
})
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
```

`build_candidates()` filters to the previous 30 days. Group invocation errors by `(tool_name, error_code)` and goal failures by `(mapped_kind, effective_tool, failure_kind.value)`. Resolve `effective_tool` from `primary_tool`, or from the correlated invocation ID when the explicit field is null. Omit ordinary groups below `min_evidence`; never threshold explicit goal failures or a technical group whose code is in `_IMMEDIATE_CODES`.

Classify a retryable ordinary group with a later success as `efficiency`. Otherwise use `reliability` for reliability codes, `guidance` for guidance codes, and `reliability` for unknown stable codes. Compute priority as invocation count plus three times goal-failure count, then add five per `incorrect_result` or `recovery_failed` goal event. Set `immediate_attention` only for `_IMMEDIATE_CODES`, `incorrect_result`, and `recovery_failed`; a service may additionally foreground a reopened candidate when a new explicit goal failure proves it is blocking again.

For each group, watermark the newest failure evidence using its table kind, integer event ID, and UTC timestamp. Do not include evidence counts, so retention of older rows cannot look like new evidence. Three successes for the same tool after the last ordinary failure produce `resolved_by_later_evidence` unless a newer explicit goal failure exists. Matching review watermarks produce `notified`; only a newer failure-evidence token produces `reopened`. Sort by descending priority, descending last-seen time, then fingerprint.

- [ ] **Step 4: Run tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_candidates.py -q
git add tests\test_learning_candidates.py pscad_mcp\learning\candidates.py
git commit -m "feat: aggregate learning candidates"
```

Expected: all candidate tests pass before the commit.

---

### Task 5: Render The Generated Markdown Backlog Atomically

**Files:**
- Create: `tests/test_learning_markdown.py`
- Create: `pscad_mcp/learning/markdown.py`

- [ ] **Step 1: Write failing renderer tests**

Create `tests/test_learning_markdown.py`:

```python
from pscad_mcp.learning.markdown import render_backlog
from pscad_mcp.learning.models import (
    CandidateKind,
    CandidateState,
    ImprovementCandidate,
)


def _candidate(state=CandidateState.OPEN):
    return ImprovementCandidate(
        candidate_id="PSCAD-IMP-ABC123",
        fingerprint="abc123",
        kind=CandidateKind.RELIABILITY,
        state=state,
        primary_tool="run_project",
        code="TIMEOUT",
        priority=4,
        invocation_count=4,
        goal_failure_count=0,
        first_seen="2026-08-18T01:00:00+00:00",
        last_seen="2026-08-19T01:00:00+00:00",
        retryable=True,
        evidence_watermark="watermark",
        immediate_attention=False,
    )


def test_renderer_writes_only_bounded_candidate_fields(tmp_path):
    backlog = tmp_path / "improvement-backlog.md"
    render_backlog(
        backlog,
        [_candidate()],
        generated_at="2026-08-19T02:00:00+00:00",
    )
    text = backlog.read_text(encoding="utf-8")
    assert "# PSCAD MCP Improvement Backlog" in text
    assert "## Open" in text
    assert "PSCAD-IMP-ABC123" in text
    assert "run_project" in text
    assert "TIMEOUT" in text
    assert "watermark" not in text
    assert "abc123" not in text


def test_empty_render_replaces_old_content_with_header_only(tmp_path):
    backlog = tmp_path / "improvement-backlog.md"
    backlog.write_text("SECRET_OLD_CONTENT", encoding="utf-8")
    render_backlog(
        backlog,
        [],
        generated_at="2026-08-19T02:00:00+00:00",
    )
    text = backlog.read_text(encoding="utf-8")
    assert "SECRET_OLD_CONTENT" not in text
    assert "No retained improvement candidates." in text
    assert list(tmp_path.glob("improvement-backlog.md.*.tmp")) == []
```

- [ ] **Step 2: Verify the missing renderer failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_markdown.py -q
```

Expected: collection fails because the renderer module is absent.

- [ ] **Step 3: Implement fixed-field atomic rendering**

Use these fixed mappings:

```python
_SECTIONS = (
    (CandidateState.OPEN, "Open"),
    (CandidateState.REOPENED, "Reopened"),
    (CandidateState.NOTIFIED, "Notified"),
    (
        CandidateState.RESOLVED_BY_LATER_EVIDENCE,
        "Resolved by later evidence",
    ),
)
_NEXT_ACTION = {
    CandidateKind.RELIABILITY: "Reproduce the failure and inspect recovery.",
    CandidateKind.CORRECTNESS: "Reproduce against an explicit expected result.",
    CandidateKind.CAPABILITY: "Confirm and specify the missing capability.",
    CandidateKind.GUIDANCE: "Inspect tool schema and recovery guidance.",
    CandidateKind.EFFICIENCY: "Reduce retries while preserving recovery.",
}
```

`render_backlog(path, candidates, *, generated_at)` renders only public candidate fields and the fixed action. Create the parent directory and use `tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", prefix=path.name + ".", suffix=".tmp", dir=path.parent, delete=False)`. Flush, call `os.fsync`, close the handle, and use `os.replace` so concurrent server processes never share a temporary filename. Remove the unique surviving temporary file in `finally`.

- [ ] **Step 4: Run tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_markdown.py -q
git add tests\test_learning_markdown.py pscad_mcp\learning\markdown.py
git commit -m "feat: render local improvement backlog"
```

Expected: renderer tests pass before the commit.

---

### Task 6: Coordinate The Lazy, Fail-Open Learning Runtime

**Files:**
- Create: `tests/test_learning_service.py`
- Create: `pscad_mcp/learning/service.py`
- Create: `pscad_mcp/learning/recorder.py`
- Modify: `pscad_mcp/learning/__init__.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/test_learning_service.py`:

```python
import logging

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.learning.config import LearningConfig
from pscad_mcp.learning.models import GoalFailureKind, InvocationOutcome
from pscad_mcp.learning.service import LearningRuntime


def _config(tmp_path, enabled=True):
    return LearningConfig(
        enabled=enabled,
        database_path=tmp_path / "learning.sqlite3",
        backlog_path=tmp_path / "improvement-backlog.md",
        retention_days=90,
        max_events=20_000,
        issue=None,
    )


def test_disabled_runtime_never_creates_files(tmp_path):
    runtime = LearningRuntime(
        config_loader=lambda: _config(tmp_path, enabled=False)
    )
    runtime.register_tool_name("run_project")
    runtime.record_invocation(
        tool_name="run_project",
        duration_ms=1,
        outcome=InvocationOutcome.SUCCESS,
        error_code=None,
        retryable=None,
        backend="legacy",
        pscad_version="4.6.2",
    )
    result = runtime.record_goal_failure(GoalFailureKind.UNKNOWN, "run_project")
    assert result == {"recorded": False, "learning_enabled": False}
    assert list(tmp_path.iterdir()) == []

    review = runtime.review(limit=10, min_evidence=3, mark_notified=True)
    assert review == {
        "learning_enabled": False,
        "learning_available": False,
        "counts": {"invocations": 0, "goal_failures": 0, "review_markers": 0},
        "attention_required": False,
        "candidates": [],
    }
    with pytest.raises(BackendError) as raised:
        runtime.clear(confirm=False)
    assert raised.value.code == "CONFIRMATION_REQUIRED"
    assert runtime.clear(confirm=True) == {
        "cleared": False,
        "learning_enabled": False,
    }


def test_goal_failure_rejects_unregistered_tool_without_storing_value(tmp_path):
    runtime = LearningRuntime(config_loader=lambda: _config(tmp_path))
    runtime.register_tool_name("run_project")
    with pytest.raises(BackendError) as raised:
        runtime.record_goal_failure(
            GoalFailureKind.UNKNOWN,
            "secret-project-name",
        )
    assert raised.value.code == "INVALID_ARGUMENT"
    assert b"secret-project-name" not in (
        tmp_path / "learning.sqlite3"
    ).read_bytes()


def test_incorrect_result_returns_one_immediate_candidate(tmp_path):
    runtime = LearningRuntime(config_loader=lambda: _config(tmp_path))
    runtime.register_tool_name("analyze_hvdc_results")
    result = runtime.record_goal_failure(
        GoalFailureKind.INCORRECT_RESULT,
        "analyze_hvdc_results",
    )
    assert result["recorded"] is True
    assert result["immediate_attention"] is True
    assert result["candidate_id"].startswith("PSCAD-IMP-")
    assert result["category"] == "correctness"
    assert result["state"] == "open"
    assert "PSCAD-IMP-" in (
        tmp_path / "improvement-backlog.md"
    ).read_text(encoding="utf-8")
    unchanged = runtime.review(limit=10, min_evidence=3, mark_notified=False)
    assert unchanged["attention_required"] is False


def test_correlated_partial_completion_returns_the_technical_candidate(tmp_path):
    runtime = LearningRuntime(config_loader=lambda: _config(tmp_path))
    runtime.register_tool_name("add_components")
    runtime.record_invocation(
        tool_name="add_components",
        duration_ms=4,
        outcome=InvocationOutcome.ERROR,
        error_code="PARTIAL_COMPLETION",
        retryable=False,
        backend="legacy",
        pscad_version="4.6.2",
    )
    result = runtime.record_goal_failure(
        GoalFailureKind.INCOMPLETE_RESULT,
        "add_components",
    )
    assert result["immediate_attention"] is True
    assert result["category"] == "reliability"


def test_invalid_enabled_configuration_is_bounded_and_goal_hook_does_not_raise(
    tmp_path,
    caplog,
):
    invalid = LearningConfig(
        enabled=True,
        database_path=tmp_path / "SECRET_PATH" / "learning.sqlite3",
        backlog_path=tmp_path / "SECRET_PATH" / "backlog.md",
        retention_days=90,
        max_events=20_000,
        issue="PSCAD_MCP_LEARNING_DB",
    )
    runtime = LearningRuntime(config_loader=lambda: invalid)
    result = runtime.record_goal_failure(GoalFailureKind.UNKNOWN, None)
    assert result == {
        "recorded": False,
        "learning_enabled": True,
        "learning_available": False,
        "immediate_attention": False,
    }
    with pytest.raises(BackendError) as raised:
        runtime.review(limit=10, min_evidence=3, mark_notified=False)
    assert raised.value.code == "LEARNING_UNAVAILABLE"
    assert raised.value.details == {"setting": "PSCAD_MCP_LEARNING_DB"}
    assert "SECRET_PATH" not in str(raised.value)
    assert caplog.messages.count(
        "Local learning is unavailable because PSCAD_MCP_LEARNING_DB is invalid."
    ) == 1
    assert "SECRET_PATH" not in "\n".join(caplog.messages)
    assert list(tmp_path.iterdir()) == []


def test_review_bounds_fail_before_creating_local_state(tmp_path):
    runtime = LearningRuntime(config_loader=lambda: _config(tmp_path))
    for limit, min_evidence in ((0, 3), (101, 3), (10, 0), (10, 101)):
        with pytest.raises(BackendError) as raised:
            runtime.review(
                limit=limit,
                min_evidence=min_evidence,
                mark_notified=False,
            )
        assert raised.value.code == "INVALID_ARGUMENT"
    assert list(tmp_path.iterdir()) == []


def test_automatic_recorder_fault_is_swallowed_and_logged_once(tmp_path, caplog):
    class FailingService:
        def record_invocation(self, **metadata):
            raise OSError("SECRET_DATABASE_PATH")

    runtime = LearningRuntime(config_loader=lambda: _config(tmp_path))
    runtime._service = FailingService()
    caplog.set_level(logging.WARNING, logger="pscad-mcp.learning")
    for _ in range(2):
        runtime.record_invocation(
            tool_name="run_project",
            duration_ms=1,
            outcome=InvocationOutcome.ERROR,
            error_code="TIMEOUT",
            retryable=True,
            backend="legacy",
            pscad_version="4.6.2",
        )
    assert len(caplog.messages) == 1
    assert "OSError" in caplog.messages[0]
    assert "SECRET_DATABASE_PATH" not in caplog.messages[0]


def test_review_marks_returned_candidates_and_clear_requires_confirmation(tmp_path):
    runtime = LearningRuntime(config_loader=lambda: _config(tmp_path))
    runtime.register_tool_name("run_project")
    for _ in range(3):
        runtime.record_invocation(
            tool_name="run_project",
            duration_ms=1,
            outcome=InvocationOutcome.ERROR,
            error_code="TIMEOUT",
            retryable=True,
            backend="legacy",
            pscad_version="4.6.2",
        )
    review = runtime.review(limit=10, min_evidence=3, mark_notified=True)
    assert review["learning_enabled"] is True
    assert review["learning_available"] is True
    assert review["counts"] == {
        "invocations": 3,
        "goal_failures": 0,
        "review_markers": 0,
    }
    assert review["attention_required"] is True
    assert len(review["candidates"]) == 1
    assert set(review["candidates"][0]).isdisjoint(
        {"fingerprint", "evidence_watermark"}
    )
    repeated = runtime.review(limit=10, min_evidence=3, mark_notified=False)
    assert repeated["attention_required"] is False
    assert repeated["candidates"] == []
    backlog = (tmp_path / "improvement-backlog.md").read_text(encoding="utf-8")
    assert "## Notified" in backlog
    with pytest.raises(BackendError) as raised:
        runtime.clear(confirm=False)
    assert raised.value.code == "CONFIRMATION_REQUIRED"
    assert runtime.clear(confirm=True) == {
        "cleared": True,
        "learning_enabled": True,
    }
```

- [ ] **Step 2: Verify missing runtime failures**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_service.py -q
```

Expected: collection fails because `LearningRuntime` is absent.

- [ ] **Step 3: Implement `LearningService`**

`LearningService` owns one store, a generated process session ID, a UTC clock, registered tool names, and one `RLock`. Validate scalar strings before persistence: tool names must be registered; error codes must match `[A-Z][A-Z0-9_]{0,63}`; backend names must match `[a-z][a-z0-9_-]{0,31}`; versions must match `[0-9A-Za-z][0-9A-Za-z._+-]{0,31}`; and duration is clamped to `0..86_400_000`. Invalid optional metadata becomes null, while an invalid error code becomes `INTERNAL_ERROR`; raw rejected values are neither logged nor returned. Implement:

```python
def register_tool_name(self, name: str) -> None
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
) -> None
def record_goal_failure(
    self,
    failure_kind: GoalFailureKind,
    primary_tool: str | None,
) -> dict[str, object]
def review(
    self,
    *,
    limit: int,
    min_evidence: int,
    mark_notified: bool,
) -> dict[str, object]
def clear(self, *, confirm: bool) -> dict[str, object]
```

At construction, call the once-per-day prune, load the retained 30-day evidence with `min_evidence=1`, delete review markers whose fingerprints have no remaining evidence, and refresh the generated backlog. Render again after an invocation error, explicit goal failure, or a success for a tool with retained failure evidence. Reject unregistered primary tools with a fixed `INVALID_ARGUMENT` message that never echoes the supplied value. When the caller omits one, use `latest_invocation()` to derive a registered effective tool and correlation ID, and persist both; this keeps candidate identity stable if retention later nulls the foreign key. If no session invocation exists, persist both as null.

After recording a goal failure, select a correlated technical candidate whose `immediate_attention` field is true first, otherwise select the matching explicit goal candidate. Return only `recorded`, `learning_enabled`, `candidate_id`, `category`, `state`, and `immediate_attention`. The returned attention flag is true for the candidate engine's critical classes or when that matching candidate is `reopened` by the new goal failure. For an immediate candidate, construct the provisional `foreground` marker in memory, atomically render the resulting Notified projection, then persist that exact marker before returning. This ordering may repeat after a crash but cannot lose an undelivered reminder. A routine first-time explicit failure remains open and returns `immediate_attention=false`.

`review()` validates `limit` and `min_evidence` in `1..100` before lazy initialization, returns only open or reopened candidates, and truncates before marking. Its exact result keys are `learning_enabled`, `learning_available`, `counts`, `attention_required`, and `candidates`; candidates come from `public_dict()`. Capture counts before notification marking so the response describes the evidence reviewed. With `mark_notified=true`, construct provisional `scheduled` markers for exactly the returned set, atomically render the resulting Notified projection, persist those exact markers, and then return the same bounded set. If rendering or marker persistence fails, do not return a successful review; the ordering favors a possible repeat over a lost notification. `clear()` checks confirmation before lazy initialization with `ConfirmationRequired("clear_learning_history")`, clears all data, and renders a header-only backlog.

- [ ] **Step 4: Implement `LearningRuntime` and `InvocationRecorder`**

`LearningRuntime` accepts a zero-argument `config_loader`, stores tool names before lazy service creation, and exposes the service operations. Explicit disablement never creates files and returns the exact disabled dictionaries asserted above. A configuration with `issue is not None` is unavailable: emit the asserted fixed warning at most once, the semantic goal hook returns the bounded non-throwing unavailable dictionary, and review and confirmed clear raise `BackendError("LEARNING_UNAVAILABLE", ...)` with only `details={"setting": config.issue}`. A runtime storage fault behaves the same but omits details. Automatic recording catches every exception, disables future writes for the process, and logs one message containing only the exception class.

Create `pscad_mcp/learning/recorder.py`:

```python
from .models import InvocationOutcome
from .service import LearningRuntime, learning_runtime


class InvocationRecorder:
    def __init__(self, runtime: LearningRuntime) -> None:
        self._runtime = runtime

    def register_tool_name(self, name: str) -> None:
        self._runtime.register_tool_name(name)

    def record(
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
        self._runtime.record_invocation(
            tool_name=tool_name,
            duration_ms=duration_ms,
            outcome=outcome,
            error_code=error_code,
            retryable=retryable,
            backend=backend,
            pscad_version=pscad_version,
        )


learning_recorder = InvocationRecorder(learning_runtime)
```

- [ ] **Step 5: Run all learning-unit tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_config.py tests\test_learning_store.py tests\test_learning_candidates.py tests\test_learning_markdown.py tests\test_learning_service.py -q
git add tests\test_learning_service.py pscad_mcp\learning
git commit -m "feat: coordinate silent learning runtime"
```

Expected: all focused tests pass before the commit, with no secret sentinel in warnings or persisted files.

---

### Task 7: Instrument The Shared MCP Registration Boundary

**Files:**
- Create: `tests/test_learning_registration.py`
- Create: `tests/test_learning_privacy.py`
- Modify: `pscad_mcp/tools/registration.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/core/connection_manager.py`

- [ ] **Step 1: Write failing wrapper and snapshot tests**

Create `tests/test_learning_registration.py`:

```python
from unittest.mock import patch

import pytest
from mcp.server.fastmcp import FastMCP

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.service import PscadService
from pscad_mcp.tools.registration import register_tool
from tests.backend_fakes import ImmediateExecutor


class ScalarRecorder:
    def __init__(self, fail=False):
        self.names = []
        self.events = []
        self.fail = fail

    def register_tool_name(self, name):
        self.names.append(name)

    def record(self, **metadata):
        if self.fail:
            raise OSError("SECRET_RECORDER_PATH")
        self.events.append(metadata)


@pytest.mark.asyncio
async def test_wrapper_preserves_success_and_records_only_scalars():
    result_object = {"secret_result": "DO_NOT_STORE"}
    calls = 0

    async def sample(project_name: str):
        nonlocal calls
        calls += 1
        assert project_name == "SECRET_PROJECT"
        return result_object

    recorder = ScalarRecorder()
    server = FastMCP("test")
    with patch(
        "pscad_mcp.tools.registration.pscad_manager.learning_snapshot",
        return_value={"backend": "legacy", "pscad_version": "4.6.2"},
    ):
        register_tool(server, sample, recorder=recorder)
        _, structured = await server._tool_manager.call_tool(
            "sample",
            {"project_name": "SECRET_PROJECT"},
            convert_result=True,
        )
    assert structured["result"] is result_object
    assert calls == 1
    assert recorder.names == ["sample"]
    assert set(recorder.events[0]) == {
        "tool_name",
        "duration_ms",
        "outcome",
        "error_code",
        "retryable",
        "backend",
        "pscad_version",
    }
    assert "SECRET_PROJECT" not in repr(recorder.events)
    assert "DO_NOT_STORE" not in repr(recorder.events)


@pytest.mark.asyncio
async def test_wrapper_classifies_returned_and_raised_stable_errors():
    async def returned_error():
        return {
            "error": {
                "code": "TIMEOUT",
                "retryable": True,
                "backend": "executor",
                "message": "SECRET_MESSAGE",
                "details": {"path": "SECRET_DETAIL_PATH"},
                "suggested_action": "SECRET_ACTION",
            }
        }

    async def raised_error():
        raise BackendError("NOT_FOUND", "SECRET", "legacy", "raised_error")

    recorder = ScalarRecorder()
    server = FastMCP("test")
    register_tool(server, returned_error, recorder=recorder)
    register_tool(server, raised_error, recorder=recorder)
    await server._tool_manager.call_tool(
        "returned_error", {}, convert_result=True
    )
    await server._tool_manager.call_tool("raised_error", {}, convert_result=True)
    assert [event["error_code"] for event in recorder.events] == [
        "TIMEOUT",
        "NOT_FOUND",
    ]
    assert [event["backend"] for event in recorder.events] == [
        "executor",
        "legacy",
    ]
    assert "SECRET" not in repr(recorder.events)


@pytest.mark.asyncio
async def test_wrapper_discards_malformed_error_metadata_without_echoing_it():
    async def malformed_error():
        return {
            "error": {
                "code": {"secret": "SECRET_CODE"},
                "retryable": "SECRET_RETRYABLE",
                "backend": "SECRET/BACKEND/PATH",
            }
        }

    recorder = ScalarRecorder()
    server = FastMCP("test")
    with patch(
        "pscad_mcp.tools.registration.pscad_manager.learning_snapshot",
        return_value={"backend": "legacy", "pscad_version": "4.6.2"},
    ):
        register_tool(server, malformed_error, recorder=recorder)
        await server._tool_manager.call_tool(
            "malformed_error", {}, convert_result=True
        )
    assert recorder.events[0]["error_code"] == "INTERNAL_ERROR"
    assert recorder.events[0]["retryable"] is None
    assert recorder.events[0]["backend"] == "legacy"
    assert "SECRET" not in repr(recorder.events)


@pytest.mark.asyncio
async def test_recorder_failure_never_replaces_original_result():
    async def sample():
        return "original"

    server = FastMCP("test")
    register_tool(server, sample, recorder=ScalarRecorder(fail=True))
    _, structured = await server._tool_manager.call_tool(
        "sample", {}, convert_result=True
    )
    assert structured["result"] == "original"


@pytest.mark.asyncio
async def test_record_learning_false_skips_names_snapshots_and_events():
    async def maintenance():
        return {"reviewed": True}

    recorder = ScalarRecorder()
    server = FastMCP("test")
    with patch(
        "pscad_mcp.tools.registration.pscad_manager.learning_snapshot"
    ) as snapshot:
        register_tool(
            server,
            maintenance,
            recorder=recorder,
            record_learning=False,
        )
        await server._tool_manager.call_tool(
            "maintenance", {}, convert_result=True
        )
    assert recorder.names == []
    assert recorder.events == []
    snapshot.assert_not_called()


def test_learning_snapshot_never_creates_or_heartbeats_backend():
    class SelectedBackend:
        name = "legacy"
        version = "4.6.2"

        async def heartbeat(self):
            raise AssertionError("snapshot must not heartbeat")

    created = []
    service = PscadService(
        lambda: created.append(object()),
        executor=ImmediateExecutor(),
    )
    assert service.learning_snapshot() == {
        "backend": None,
        "pscad_version": None,
    }
    assert created == []
    service._backend = SelectedBackend()
    assert service.learning_snapshot() == {
        "backend": "legacy",
        "pscad_version": "4.6.2",
    }
    assert created == []
```

Create `tests/test_learning_privacy.py` as the end-to-end persistence gate:

```python
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp.server.fastmcp import FastMCP

from pscad_mcp.learning.config import LearningConfig
from pscad_mcp.learning.recorder import InvocationRecorder
from pscad_mcp.learning.service import LearningRuntime
from pscad_mcp.tools.registration import register_tool


SENTINELS = (
    "SECRET_PROJECT_PATH",
    "SECRET_PARAMETER",
    "SECRET_USER_PROMPT",
    "SECRET_SUCCESS_RESULT",
    "SECRET_ERROR_MESSAGE",
    "SECRET_ERROR_DETAIL",
    "SECRET_SUGGESTED_ACTION",
    "SECRET_TRACEBACK_TEXT",
)


def _config(tmp_path):
    return LearningConfig(
        enabled=True,
        database_path=tmp_path / "learning.sqlite3",
        backlog_path=tmp_path / "improvement-backlog.md",
        retention_days=90,
        max_events=20_000,
        issue=None,
    )


@pytest.mark.asyncio
async def test_sensitive_content_never_reaches_learning_artifacts_or_results(
    tmp_path,
    caplog,
):
    async def successful(project_path: str, prompt: str):
        assert project_path == "SECRET_PROJECT_PATH"
        assert prompt == "SECRET_USER_PROMPT"
        return {"value": "SECRET_SUCCESS_RESULT"}

    async def returned_error(parameter: str):
        assert parameter == "SECRET_PARAMETER"
        return {
            "error": {
                "code": "TIMEOUT",
                "retryable": True,
                "backend": "executor",
                "message": "SECRET_ERROR_MESSAGE",
                "details": {"value": "SECRET_ERROR_DETAIL"},
                "suggested_action": "SECRET_SUGGESTED_ACTION",
            }
        }

    async def raised_error():
        raise RuntimeError("SECRET_TRACEBACK_TEXT")

    runtime = LearningRuntime(config_loader=lambda: _config(tmp_path))
    recorder = InvocationRecorder(runtime)
    server = FastMCP("privacy-test")
    for function in (successful, returned_error, raised_error):
        register_tool(server, function, recorder=recorder)

    await server._tool_manager.call_tool(
        "successful",
        {
            "project_path": "SECRET_PROJECT_PATH",
            "prompt": "SECRET_USER_PROMPT",
        },
        convert_result=True,
    )
    for _ in range(3):
        await server._tool_manager.call_tool(
            "returned_error",
            {"parameter": "SECRET_PARAMETER"},
            convert_result=True,
        )
    await server._tool_manager.call_tool(
        "raised_error", {}, convert_result=True
    )
    review = runtime.review(limit=10, min_evidence=3, mark_notified=False)

    inspected = b"\n".join(
        (
            (tmp_path / "learning.sqlite3").read_bytes(),
            (tmp_path / "improvement-backlog.md").read_bytes(),
            repr(review).encode("utf-8"),
            "\n".join(caplog.messages).encode("utf-8"),
        )
    )
    for sentinel in SENTINELS:
        assert sentinel.encode("ascii") not in inspected


@pytest.mark.asyncio
async def test_renderer_fault_cannot_replace_a_tool_result_or_leak_its_message(
    tmp_path,
    caplog,
):
    async def successful():
        return {"value": "original"}

    runtime = LearningRuntime(config_loader=lambda: _config(tmp_path))
    server = FastMCP("renderer-fault-test")
    register_tool(server, successful, recorder=InvocationRecorder(runtime))
    with patch(
        "pscad_mcp.learning.service.render_backlog",
        side_effect=OSError("SECRET_RENDERER_PATH"),
    ):
        _, structured = await server._tool_manager.call_tool(
            "successful", {}, convert_result=True
        )
    assert structured["result"] == {"value": "original"}
    messages = "\n".join(caplog.messages)
    assert "OSError" in messages
    assert "SECRET_RENDERER_PATH" not in messages


def test_learning_package_has_no_network_client_imports():
    learning_root = Path(__file__).parents[1] / "pscad_mcp" / "learning"
    forbidden = ("import requests", "import httpx", "import socket", "import urllib")
    for path in learning_root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for value in forbidden:
            assert value not in source
```

- [ ] **Step 2: Run and verify interface failures**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_registration.py -q
```

Expected: failures show `register_tool` lacks `recorder` and `PscadService` lacks `learning_snapshot`.

- [ ] **Step 3: Add the non-I/O backend snapshot**

Add to `PscadService`:

```python
def learning_snapshot(self) -> dict[str, str | None]:
    backend = self._backend
    if backend is None:
        return {"backend": None, "pscad_version": None}
    return {
        "backend": getattr(backend, "name", None),
        "pscad_version": getattr(backend, "version", None),
    }
```

Add `PSCADConnectionManager.learning_snapshot()` that delegates directly. Do not call status, heartbeat, the public `backend` property, or the backend factory.

- [ ] **Step 4: Instrument `register_tool` without changing contracts**

Extend its signature:

```python
def register_tool(
    mcp: FastMCP,
    function: Callable[P, Awaitable[R]],
    *,
    recorder: InvocationRecorder = learning_recorder,
    record_learning: bool = True,
) -> None:
```

When enabled, register `function.__name__`. Read the snapshot first, then start `time.perf_counter()` immediately before calling the original function and stop it immediately after the return or exception; recording time is excluded. Snapshot failure uses null metadata and is handled by the same class-only, once-per-process warning policy. After the original result or stable error payload is known, extract only `code`, `retryable`, and `backend` from a mapping-shaped top-level `error`. Accept `retryable` only when it is a real `bool`, otherwise use null. Accept code and backend only when they are strings satisfying the service's bounded identifier rules; otherwise use `INTERNAL_ERROR` and the snapshot backend. A valid error-envelope backend overrides the snapshot backend. Pass no other result field to the recorder.

Use `_record_safely()` plus a module-level lock and boolean to catch recorder or snapshot exceptions and emit at most one warning per process containing only the exception class. When `record_learning=False`, skip tool-name registration, snapshotting, timing, and recording entirely while retaining error serialization. Preserve existing signature and annotation rewriting, call the original function exactly once, preserve the exact original success object, and preserve the existing serialized error payload.

- [ ] **Step 5: Run regression tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_registration.py tests\test_learning_privacy.py tests\test_protocol.py tests\test_service_contract.py -q
git add tests\test_learning_registration.py tests\test_learning_privacy.py pscad_mcp\tools\registration.py pscad_mcp\core\service.py pscad_mcp\core\connection_manager.py
git commit -m "feat: record MCP outcome metadata"
```

Expected: all tests pass before the commit. Direct Python tools still raise original exceptions; FastMCP calls retain stable errors.

---

### Task 8: Expose Three Learning Tools And Server Instructions

**Files:**
- Create: `tests/test_learning_tools.py`
- Create: `pscad_mcp/tools/learning_tools.py`
- Modify: `pscad_mcp/main.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `tests/test_tool_inventory.py`
- Modify: `tests/test_tool_backend_matrix.py`
- Modify: `tests/test_hvdc_tools.py`
- Modify: `tests/test_install_smoke.py`
- Modify: `tests/test_delivery_hardening.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/verify_package.ps1`

- [ ] **Step 1: Write failing public-tool tests**

Create `tests/test_learning_tools.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.main import SERVER_INSTRUCTIONS, create_server
from pscad_mcp.tools.learning_tools import (
    clear_learning_history,
    record_goal_failure,
    review_improvement_backlog,
)


@pytest.mark.asyncio
async def test_learning_tools_delegate_enum_only_inputs():
    runtime = MagicMock()
    runtime.record_goal_failure.return_value = {
        "recorded": True,
        "learning_enabled": True,
        "candidate_id": "PSCAD-IMP-ABC",
        "category": "correctness",
        "state": "open",
        "immediate_attention": True,
    }
    runtime.review.return_value = {
        "attention_required": False,
        "candidates": [],
    }
    runtime.clear.return_value = {
        "cleared": True,
        "learning_enabled": True,
    }
    with patch("pscad_mcp.tools.learning_tools.learning_runtime", runtime):
        recorded = await record_goal_failure(
            "incorrect_result",
            "run_project",
        )
        reviewed = await review_improvement_backlog(10, 3, True)
        cleared = await clear_learning_history(True)
    assert recorded["candidate_id"] == "PSCAD-IMP-ABC"
    assert reviewed["attention_required"] is False
    assert cleared["cleared"] is True
    runtime.review.assert_called_once_with(
        limit=10,
        min_evidence=3,
        mark_notified=True,
    )
    runtime.clear.assert_called_once_with(confirm=True)


@pytest.mark.asyncio
async def test_record_goal_failure_rejects_an_arbitrary_kind_without_echoing_it():
    with pytest.raises(BackendError) as raised:
        await record_goal_failure("SECRET_FREE_TEXT", None)  # type: ignore[arg-type]
    assert getattr(raised.value, "code", None) == "INVALID_ARGUMENT"
    assert "SECRET_FREE_TEXT" not in str(raised.value)


def test_server_registers_73_unique_tools_and_silent_instructions():
    server = create_server()
    names = {tool.name for tool in server._tool_manager.list_tools()}
    assert len(names) == 73
    assert {
        "record_goal_failure",
        "review_improvement_backlog",
        "clear_learning_history",
    } <= names
    assert server.instructions == SERVER_INSTRUCTIONS
    assert (
        "Do not mention learning, telemetry, or backlog maintenance"
        in SERVER_INSTRUCTIONS
    )
    assert "record_goal_failure" in SERVER_INSTRUCTIONS
    assert "inspect it now or leave it for the weekly review" in SERVER_INSTRUCTIONS
    assert "Do not start remediation automatically" in SERVER_INSTRUCTIONS
```

- [ ] **Step 2: Run and verify missing-tool failures**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_tools.py -q
```

Expected: collection fails because `learning_tools` and `SERVER_INSTRUCTIONS` do not exist.

- [ ] **Step 3: Implement the three tools**

Create `pscad_mcp/tools/learning_tools.py`:

```python
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from ..core.backend.base import BackendError
from ..learning.models import GoalFailureKind
from ..learning.service import learning_runtime
from .registration import register_tool


FailureKindValue = Literal[
    "unsupported_operation",
    "incorrect_result",
    "incomplete_result",
    "environment_blocked",
    "recovery_failed",
    "unknown",
]


async def record_goal_failure(
    failure_kind: FailureKindValue,
    primary_tool: str | None = None,
) -> dict[str, Any]:
    try:
        kind = GoalFailureKind(failure_kind)
    except ValueError as error:
        raise BackendError(
            "INVALID_ARGUMENT",
            "failure_kind must be one of the documented enum values.",
            "learning",
            "record_goal_failure",
        ) from error
    return learning_runtime.record_goal_failure(
        kind,
        primary_tool,
    )


async def review_improvement_backlog(
    limit: int = 10,
    min_evidence: int = 3,
    mark_notified: bool = False,
) -> dict[str, Any]:
    return learning_runtime.review(
        limit=limit,
        min_evidence=min_evidence,
        mark_notified=mark_notified,
    )


async def clear_learning_history(
    confirm: bool = False,
) -> dict[str, Any]:
    return learning_runtime.clear(confirm=confirm)


def register_learning_tools(mcp: FastMCP) -> None:
    for function in (
        record_goal_failure,
        review_improvement_backlog,
        clear_learning_history,
    ):
        register_tool(mcp, function, record_learning=False)
```

Add fixed `LEARNING_UNAVAILABLE` guidance to `_ERROR_GUIDANCE`. Its stable message says only that local learning state is unavailable; details may contain the environment variable name, never a path or raw exception.

- [ ] **Step 4: Register tools and server instructions**

In `pscad_mcp/main.py`, define:

```python
SERVER_INSTRUCTIONS = (
    "Use PSCAD tools normally. Do not mention learning, telemetry, or backlog "
    "maintenance during successful PSCAD work. "
    "When and only when the requested PSCAD goal cannot be completed or the result "
    "is incorrect or incomplete, call record_goal_failure once with an enum reason "
    "and an affected registered tool name when known. If immediate_attention is true, "
    "give at most one concise reminder with the returned candidate ID and category, "
    "then ask whether to inspect it now or leave it for the weekly review. Otherwise "
    "do not mention learning. Do not start remediation automatically. Never include "
    "project names, paths, parameters, outputs, prompts, or exception text in "
    "learning calls or reminders."
)
```

Construct `FastMCP("PSCAD-Modular", instructions=SERVER_INSTRUCTIONS)` and register learning tools last.

- [ ] **Step 5: Update every exact inventory gate in the same change**

Add `LEARNING_TOOLS` in `tests/test_tool_inventory.py` and assert:

```python
assert len(set(names)) == 73
assert len(set(names) - HVDC_TOOLS - LEARNING_TOOLS) == 60
```

Add the names to `EXPECTED_TOOLS` in `tests/test_tool_backend_matrix.py`, change its total and the HVDC superset check to 73, and update installed-wheel probes, package verification, and CI from 70 to 73. Preserve the 60 generic and 10 HVDC boundaries. Update the CI comment and `tests/test_delivery_hardening.py` expected output to `73 73`.

- [ ] **Step 6: Run focused contract tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_tools.py tests\test_tool_inventory.py tests\test_tool_backend_matrix.py tests\test_hvdc_tools.py tests\test_protocol.py tests\test_delivery_hardening.py -q
git add pscad_mcp\main.py pscad_mcp\tools\learning_tools.py pscad_mcp\core\service.py tests\test_learning_tools.py tests\test_tool_inventory.py tests\test_tool_backend_matrix.py tests\test_hvdc_tools.py tests\test_install_smoke.py tests\test_delivery_hardening.py .github\workflows\ci.yml scripts\verify_package.ps1
git commit -m "feat: expose silent learning tools"
```

Expected: tests pass and the server exposes exactly 73 tools before the commit.

---

### Task 9: Add The Review And Approved-Remediation Skill

**Files:**
- Create: `tests/test_learning_skill.py`
- Create: `.agents/skills/pscad-mcp-improver/SKILL.md`
- Create: `.agents/skills/pscad-mcp-improver/references/scheduled-review.md`

- [ ] **Step 1: Read skill-authoring instructions at execution time**

Invoke `writing-skills` or `skill-creator` before editing. Keep the skill repository-scoped because it modifies this repository; do not install it globally.

- [ ] **Step 2: Write a failing skill contract test**

Create `tests/test_learning_skill.py`:

```python
from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILL = ROOT / ".agents" / "skills" / "pscad-mcp-improver" / "SKILL.md"
PROMPT = SKILL.parent / "references" / "scheduled-review.md"


def test_improver_skill_is_review_only_until_user_approval():
    text = SKILL.read_text(encoding="utf-8")
    assert "name: pscad-mcp-improver" in text
    assert "review_improvement_backlog" in text
    assert "explicit user approval" in text
    assert "failing regression test" in text
    assert "isolated" in text and "worktree" in text
    assert "Never merge, push, publish, or deploy" in text
    assert "Never edit improvement-backlog.md" in text
    assert "needs_evidence" in text
    assert "AGENTS.md" in text
    assert "repeated workflow mistake" in text


def test_scheduled_prompt_is_quiet_without_findings():
    text = PROMPT.read_text(encoding="utf-8")
    assert "$pscad-mcp-improver" in text
    assert "review-only mode" in text
    assert "mark_notified=true" in text
    assert "attention_required=false" in text
    assert "Do not modify repository files" in text
    assert "Monday" not in text
```

- [ ] **Step 3: Run and verify missing skill files**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_skill.py -q
```

Expected: both tests fail with `FileNotFoundError`.

- [ ] **Step 4: Write the repository skill**

Use this frontmatter:

```markdown
---
name: pscad-mcp-improver
description: Review PSCAD MCP improvement evidence and, only after explicit user approval, reproduce and remediate approved candidates with regression tests. Use for scheduled backlog review or user-requested MCP improvement.
---
```

Define review-only and remediation modes. Review-only calls `review_improvement_backlog(limit=10, min_evidence=3, mark_notified=true)`, changes no file, and reports only bounded candidate fields when attention is required. Remediation requires explicit user approval and an approved candidate list; it uses an isolated `codex/` branch or worktree, writes and observes a failing regression test before source changes, and commits one root cause at a time. Include the exact safety sentences `Never merge, push, publish, or deploy.` and `Never edit improvement-backlog.md; it is a generated projection.` It must also never weaken safety or run licensed acceptance without the existing opt-in. An unreproduced candidate stays unchanged in the generated backlog and is listed in the remediation summary with the fixed action `needs_evidence`; do not create a speculative patch. The skill may propose or edit `AGENTS.md` or its own instructions only in an approved remediation when a repeated workflow mistake has been reproduced; a backlog candidate alone is not sufficient evidence.

- [ ] **Step 5: Write the durable heartbeat prompt**

Create `references/scheduled-review.md`:

```markdown
Use $pscad-mcp-improver in review-only mode.

Call review_improvement_backlog with limit=10, min_evidence=3, and mark_notified=true.
Do not modify repository files, create a branch, run tests, or start remediation.

When attention_required=false, finish quietly with no user-facing attention request.
When attention_required=true, report only the returned candidate IDs, categories,
tools, stable codes, evidence counts, and priorities. Ask whether to start one
consolidated remediation batch. Do not include local paths or raw stored data.

If learning_enabled=false, remain quiet. If enabled learning is unavailable,
use this heartbeat's prior run context and report monitoring unavailable only
after two consecutive unavailable runs.
```

Keep cadence and notification policy in Codex automation, not this prompt.

- [ ] **Step 6: Run tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_skill.py -q
git add tests\test_learning_skill.py .agents\skills\pscad-mcp-improver
git commit -m "docs: add PSCAD MCP improvement skill"
```

Expected: skill tests pass before the commit.

---

### Task 10: Document Configuration, Installation, Privacy, And Local State

**Files:**
- Modify: `tests/test_config_example.py`
- Modify: `tests/test_delivery_hardening.py`
- Modify: `tests/test_installer_setup.py`
- Modify: `tests/test_changelog.py`
- Modify: `config.example.toml`
- Modify: `mcp_installer.py`
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `CHANGELOG.md`
- Modify: `.gitignore`

- [ ] **Step 1: Add failing documentation and installer assertions**

Require portable config and generated installer JSON to contain `PSCAD_MCP_LEARNING_ENABLED=true`, while database and backlog paths remain optional. Add README assertions for all five learning variables, local-only privacy, `improvement-backlog.md`, and the three learning tool names. Add a changelog assertion for `silent learning`.

Append this cross-language contract to `tests/test_config_example.py`:

```python
def test_learning_controls_and_inventory_are_documented_in_both_languages():
    root = Path(__file__).parents[1]
    required = (
        "PSCAD_MCP_LEARNING_ENABLED",
        "PSCAD_MCP_LEARNING_DB",
        "PSCAD_MCP_LEARNING_BACKLOG",
        "PSCAD_MCP_LEARNING_RETENTION_DAYS",
        "PSCAD_MCP_LEARNING_MAX_EVENTS",
        "improvement-backlog.md",
        "record_goal_failure",
        "review_improvement_backlog",
        "clear_learning_history",
        "73",
    )
    for relative in ("README.md", "docs/zh-CN/README.md"):
        text = (root / relative).read_text(encoding="utf-8")
        for value in required:
            assert value in text
```

Update the configured-workspace installer expectation to:

```python
assert server["env"] == {
    "PSCAD_MCP_WORKSPACE": workspace,
    "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "false",
    "PSCAD_MCP_LEARNING_ENABLED": "true",
}
```

For missing-workspace and explicit-unscoped cases, preserve workspace safety fields and also require learning enabled. Add one test proving `PSCAD_MCP_LEARNING_ENABLED=no` normalizes to `false`.

```python
def test_installer_normalizes_explicit_learning_disable(caplog):
    caplog.set_level(logging.INFO, logger="mcp-installer")
    with patch("mcp_installer.platform.system", return_value="Windows"), patch.object(
        mcp_installer.sys, "executable", r"C:\Python312\python.exe"
    ), patch.dict(
        os.environ,
        {"PSCAD_MCP_LEARNING_ENABLED": "no"},
        clear=True,
    ):
        mcp_installer.print_copilot_cli_setup()
    server = _logged_config(caplog)["mcpServers"]["pscad"]
    assert server["env"]["PSCAD_MCP_LEARNING_ENABLED"] == "false"
```

- [ ] **Step 2: Run and verify documentation failures**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_config_example.py tests\test_delivery_hardening.py tests\test_installer_setup.py tests\test_changelog.py -q
```

Expected: new assertions fail because configuration and documentation do not yet mention learning.

- [ ] **Step 3: Update portable and generated configuration**

Add to `[mcp_servers.pscad.env]` in `config.example.toml`:

```toml
PSCAD_MCP_LEARNING_ENABLED = 'true'
PSCAD_MCP_LEARNING_RETENTION_DAYS = '90'
PSCAD_MCP_LEARNING_MAX_EVENTS = '20000'
```

Rename installer `_workspace_environment()` to `_server_environment()` and always include normalized `PSCAD_MCP_LEARNING_ENABLED`. Accept `1`, `true`, `yes`, and `on` as true and `0`, `false`, `no`, and `off` as false; default to true when unset. For any other value, emit one fixed warning that names only `PSCAD_MCP_LEARNING_ENABLED` and generate `false` without echoing the raw value. Continue copying workspace and unscoped settings exactly. Print the normalized flag without printing database or backlog paths.

- [ ] **Step 4: Add concise English and Chinese learning sections**

Document all of these facts in both READMEs:

- default enabled, local-only metadata collection;
- forbidden persistence of parameters, results, paths, prompts, exception text, details, and tracebacks;
- default `%LOCALAPPDATA%\pscad-mcp` state location;
- five environment variables and numeric bounds;
- generated `improvement-backlog.md` and overwrite of manual edits;
- silent successful operation and narrowly defined critical reminders;
- the host may still show a collapsed `record_goal_failure` audit entry after
  a failed goal even though routine user-facing prose remains silent;
- separately created Codex desktop heartbeat for Monday 09:00
  `Asia/Shanghai` (the MCP server and installer do not create it implicitly);
- three learning tools and confirmed clearing; and
- local scheduled work needs the machine and desktop app running.

Correct inventory wording without globally replacing `60`: the total is 73,
made up of 60 generic tools, 10 HVDC tools, and 3 learning tools. Change the
Chinese verification example from `60 60` to `73 73`; preserve statements that
specifically describe the stable 60-tool generic contract. Apply the same
total/breakdown wording to the English tool overview.

Add `.pscad-mcp/learning/` to `.gitignore` for repository-local overrides.

- [ ] **Step 5: Update unreleased notes**

Under `CHANGELOG.md` `Unreleased`, add one `silent learning` bullet covering scalar local evidence, generated Markdown, three tools, critical reminders, privacy exclusions, and total inventory 73. Do not change release `0.2.0` or the package version.

- [ ] **Step 6: Run tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_config_example.py tests\test_delivery_hardening.py tests\test_installer_setup.py tests\test_changelog.py -q
git add tests\test_config_example.py tests\test_delivery_hardening.py tests\test_installer_setup.py tests\test_changelog.py config.example.toml mcp_installer.py README.md docs\zh-CN\README.md CHANGELOG.md .gitignore
git commit -m "docs: document silent learning controls"
```

Expected: documentation and installer tests pass before the commit.

---

### Task 11: Run Privacy, Package, And Full Regression Gates

**Files:**
- Modify only a file required by a newly reproduced failure.

- [ ] **Step 1: Run every focused learning test together**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_learning_config.py tests\test_learning_store.py tests\test_learning_candidates.py tests\test_learning_markdown.py tests\test_learning_service.py tests\test_learning_registration.py tests\test_learning_privacy.py tests\test_learning_tools.py tests\test_learning_skill.py -q
```

Expected: zero failures, no warning containing a sentinel, and no write to the real local learning directory.

- [ ] **Step 2: Run the full Python suite**

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

Expected: zero failures. Existing licensed/environment skips remain acceptable. Reproduce any new failure with its smallest test before changing production code.

- [ ] **Step 3: Verify exact inventory and installed wheel**

```powershell
& .\.venv\Scripts\python.exe -c "from pscad_mcp.main import create_server; tools=create_server()._tool_manager.list_tools(); print(len(tools), len({tool.name for tool in tools})); assert len(tools) == len({tool.name for tool in tools}) == 73"
$env:PSCAD_MCP_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
.\scripts\verify_package.ps1
Remove-Item Env:PSCAD_MCP_PYTHON
```

Expected: inventory prints `73 73`; package verification builds and installs a wheel and prints version `0.2.0` with 73 tools.

- [ ] **Step 4: Run source and dependency gates**

```powershell
& .\.venv\Scripts\python.exe -m compileall -q pscad_mcp tests
& .\.venv\Scripts\python.exe -m pip check
git diff --check
git status --short
```

Expected: compilation and diff checks have no output, `pip check` reports no broken requirements, and status is clean after intended commits.

- [ ] **Step 5: Review the branch against the specification**

```powershell
$implementationBase = git log --diff-filter=A --format=%H -- 'docs/superpowers/plans/2026-08-19-pscad-mcp-silent-learning.md' | Select-Object -Last 1
if (-not $implementationBase) { throw "Cannot locate the implementation-plan commit." }
git diff --stat "${implementationBase}...HEAD"
git log --oneline "${implementationBase}..HEAD"
```

Map every completion criterion to a test or the automation task below. Verify no fixture or probe created `%LOCALAPPDATA%\pscad-mcp\learning.sqlite3` with synthetic events.

---

### Task 12: Manually Validate And Create The Weekly Codex Heartbeat

**Files:**
- No repository files are modified.

- [ ] **Step 1: Confirm the implementation is in the durable workspace**

Run this task only after the user has reviewed the verified implementation
branch and approved its integration into the durable `D:\pscad-mcp` workspace.
Confirm that the MCP configuration resolves to that durable workspace, not a
temporary implementation worktree. If integration is still pending, stop here,
report the heartbeat as pending, and do not create an automation that points at
an expendable path.

- [ ] **Step 2: Reload the MCP server context**

Restart or open a Codex task rooted at the durable workspace so the installed PSCAD MCP server advertises 73 tools and the new server instructions. Confirm `review_improvement_backlog` is available before creating the heartbeat.

- [ ] **Step 3: Manually test the durable review prompt**

Run `.agents/skills/pscad-mcp-improver/references/scheduled-review.md` once in the current task. With no actionable evidence, expect no repository write, branch, or test run and `attention_required=false`. With real evidence, verify output contains only bounded candidate fields and asks for approval without editing code.

- [ ] **Step 4: Create the heartbeat through Codex automation tooling**

Before creating anything, inspect `%CODEX_HOME%\automations\*\automation.toml` (or `%USERPROFILE%\.codex\automations\*\automation.toml` when `CODEX_HOME` is unset) for an existing automation whose name is `PSCAD MCP improvement review`. If one exists, read its complete current definition and update that automation ID while preserving fields not changed below; do not create a duplicate. Then use `codex_app__automation_update`. Do not create a Windows scheduled task, cron file, standalone cron automation, or hand-written automation directive. Create or update a heartbeat attached to the current task with:

```text
Name: PSCAD MCP improvement review
Cadence: every Monday at 09:00
Timezone: Asia/Shanghai
Prompt source: .agents/skills/pscad-mcp-improver/references/scheduled-review.md
Notification policy: default (null); keep notification preferences out of the prompt
```

Keep default model and reasoning settings. Do not grant network access. The heartbeat needs only the local project and configured PSCAD MCP connection. Its review-only prompt decides whether the run has a finding; completed empty runs may remain visible under Scheduled without requesting user attention.

- [ ] **Step 5: Verify the heartbeat**

Read the automation result and confirm name, enabled status, timezone, Monday 09:00 cadence, current-task attachment, and saved prompt. Report its automation ID. Note that the machine and desktop app must be running for local scheduled work. Review the first few runs and pause it if an empty run creates an attention notification or a review-only run modifies the repository.

---

## Execution Handoff

Plan implementation starts only from the committed specification and this plan. Use one mode:

1. **Subagent-Driven (recommended):** dispatch one fresh subagent per task, review specification compliance and code quality after each task, and preserve the commit boundaries above.
2. **Inline Execution:** use `executing-plans`, work in small batches with review checkpoints, and preserve the same red-green and commit sequence.
