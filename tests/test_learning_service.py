import logging

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.service import ConfirmationRequired
from pscad_mcp.learning.config import LearningConfig
from pscad_mcp.learning.models import GoalFailureKind, InvocationOutcome
from pscad_mcp.learning.service import LearningRuntime, LearningService


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


def test_learning_service_clear_requires_confirmation(tmp_path):
    service = LearningService(_config(tmp_path))
    with pytest.raises(ConfirmationRequired) as raised:
        service.clear(confirm=False)
    assert raised.value.code == "CONFIRMATION_REQUIRED"


def test_learning_service_clear_returns_bounded_result(tmp_path):
    service = LearningService(_config(tmp_path))
    assert service.clear(confirm=True) == {
        "cleared": True,
        "learning_enabled": True,
    }


def test_unavailable_runtime_clear_keeps_bounded_error(tmp_path):
    invalid = LearningConfig(
        enabled=True,
        database_path=tmp_path / "SECRET_PATH" / "learning.sqlite3",
        backlog_path=tmp_path / "SECRET_PATH" / "backlog.md",
        retention_days=90,
        max_events=20_000,
        issue="PSCAD_MCP_LEARNING_DB",
    )
    runtime = LearningRuntime(config_loader=lambda: invalid)
    with pytest.raises(BackendError) as raised:
        runtime.clear(confirm=True)
    assert raised.value.code == "LEARNING_UNAVAILABLE"
    assert raised.value.details == {"setting": "PSCAD_MCP_LEARNING_DB"}
    assert "SECRET_PATH" not in str(raised.value)
