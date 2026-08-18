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
