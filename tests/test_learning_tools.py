import inspect
from unittest.mock import MagicMock, patch

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.learning.config import LearningConfig
from pscad_mcp.main import SERVER_INSTRUCTIONS, create_server
from pscad_mcp.tools.learning_tools import (
    clear_learning_history,
    record_goal_failure,
    review_improvement_backlog,
)
from pscad_mcp.learning.models import GoalFailureKind
from pscad_mcp.learning.recorder import learning_recorder
from pscad_mcp.learning.service import LearningRuntime
from pscad_mcp.tools import learning_tools
from pscad_mcp.tools import hvdc_tools
from pscad_mcp.tools.catalog import (
    COMPATIBILITY_TOOL_NAMES,
    FULL_TOOL_NAMES,
    TOOL_GROUPS,
    TOOL_SPECS,
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


@pytest.mark.asyncio
async def test_mcp_entry_rejects_an_arbitrary_kind_without_echoing_it():
    server = create_server(environ={})
    _, structured = await server._tool_manager.call_tool(
        "record_goal_failure",
        {
            "failure_kind": "SECRET_FREE_TEXT",
            "primary_tool": None,
        },
        convert_result=True,
    )
    assert structured["error"]["code"] == "INVALID_ARGUMENT"
    assert "SECRET_FREE_TEXT" not in repr(structured)


def test_server_registers_full_inventory_and_silent_instructions():
    server = create_server(environ={})
    names = {tool.name for tool in server._tool_manager.list_tools()}
    assert names == FULL_TOOL_NAMES
    assert len(COMPATIBILITY_TOOL_NAMES) == 96
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


def test_learning_eligibility_excludes_non_recorded_tools():
    server = create_server(environ={})

    assert server._pscad_registered_tool_names == set(FULL_TOOL_NAMES)
    assert server._pscad_learning_tool_names == set(
        COMPATIBILITY_TOOL_NAMES - TOOL_GROUPS["learning"]
    )


def test_learning_only_profile_has_an_explicit_empty_eligibility_set():
    server = create_server(environ={"PSCAD_MCP_TOOL_PROFILE": "learning"})

    assert server._pscad_learning_tool_names == set()


@pytest.mark.parametrize("creation_order", ["full-first", "scoped-first"])
@pytest.mark.asyncio
async def test_learning_primary_tool_is_scoped_per_server_profile(
    creation_order,
    monkeypatch,
):
    class RecordingRuntime:
        def __init__(self):
            self.calls = []

        def record_goal_failure(
            self,
            failure_kind,
            primary_tool,
            *,
            allowed_tool_names=None,
        ):
            self.calls.append(
                (failure_kind, primary_tool, allowed_tool_names)
            )
            return {
                "recorded": True,
                "learning_enabled": True,
                "immediate_attention": False,
            }

    runtime = RecordingRuntime()
    monkeypatch.setattr(learning_tools, "learning_runtime", runtime)
    factories = {
        "full": lambda: create_server(environ={}),
        "scoped": lambda: create_server(
            environ={"PSCAD_MCP_TOOL_PROFILE": "core,learning"}
        ),
    }
    order = (
        ("full", "scoped")
        if creation_order == "full-first"
        else ("scoped", "full")
    )
    servers = {name: factories[name]() for name in order}
    scoped_tool = servers["scoped"]._tool_manager.get_tool(
        "record_goal_failure"
    )
    full_tool = servers["full"]._tool_manager.get_tool("record_goal_failure")

    assert scoped_tool is not None
    assert full_tool is not None
    assert scoped_tool.name == record_goal_failure.__name__
    assert inspect.getdoc(scoped_tool.fn) == inspect.getdoc(record_goal_failure)
    assert inspect.signature(scoped_tool.fn) == inspect.signature(
        record_goal_failure
    )
    assert scoped_tool.parameters == full_tool.parameters

    _, rejected = await servers["scoped"]._tool_manager.call_tool(
        "record_goal_failure",
        {
            "failure_kind": "unknown",
            "primary_tool": "run_hvdc_scenario",
        },
        convert_result=True,
    )
    assert rejected["error"] == {
        "code": "INVALID_ARGUMENT",
        "message": "The supplied tool name is not registered.",
        "backend": "learning",
        "operation": "learning",
        "details": {},
        "retryable": False,
        "suggested_action": "Correct the argument values and retry the operation.",
    }
    assert "run_hvdc_scenario" not in repr(rejected)
    assert runtime.calls == []

    await servers["scoped"]._tool_manager.call_tool(
        "record_goal_failure",
        {"failure_kind": "unknown", "primary_tool": "list_projects"},
        convert_result=True,
    )
    await servers["full"]._tool_manager.call_tool(
        "record_goal_failure",
        {
            "failure_kind": "unknown",
            "primary_tool": "run_hvdc_scenario",
        },
        convert_result=True,
    )
    assert runtime.calls == [
        (
            GoalFailureKind.UNKNOWN,
            "list_projects",
            TOOL_GROUPS["core"],
        ),
        (
            GoalFailureKind.UNKNOWN,
            "run_hvdc_scenario",
            COMPATIBILITY_TOOL_NAMES - TOOL_GROUPS["learning"],
        ),
    ]


@pytest.mark.parametrize(
    "primary_tool",
    [
        "get_pscad_capabilities",
        "record_goal_failure",
        "review_improvement_backlog",
        "clear_learning_history",
    ],
)
@pytest.mark.asyncio
async def test_non_recorded_tool_cannot_be_an_explicit_learning_primary(
    primary_tool,
    monkeypatch,
):
    runtime = MagicMock()
    monkeypatch.setattr(learning_tools, "learning_runtime", runtime)
    server = create_server(environ={})

    _, rejected = await server._tool_manager.call_tool(
        "record_goal_failure",
        {"failure_kind": "unknown", "primary_tool": primary_tool},
        convert_result=True,
    )

    assert rejected["error"]["code"] == "INVALID_ARGUMENT"
    assert primary_tool not in repr(rejected)
    runtime.record_goal_failure.assert_not_called()


@pytest.mark.asyncio
async def test_capability_tool_cannot_be_an_automatic_learning_primary(
    monkeypatch,
    tmp_path,
):
    config = LearningConfig(
        enabled=True,
        database_path=tmp_path / "learning.sqlite3",
        backlog_path=tmp_path / "improvement-backlog.md",
        retention_days=90,
        max_events=20_000,
        issue=None,
    )
    runtime = LearningRuntime(config_loader=lambda: config)
    monkeypatch.setattr(learning_tools, "learning_runtime", runtime)
    monkeypatch.setattr(learning_recorder, "_runtime", runtime)

    async def disconnected_status():
        return {"connected": False, "backend": None, "version": None}

    from pscad_mcp.tools import capability_tools

    monkeypatch.setattr(
        capability_tools.pscad_manager,
        "get_status",
        disconnected_status,
    )
    server = create_server(environ={})
    await server._tool_manager.call_tool(
        "get_pscad_capabilities", {}, convert_result=True
    )
    await server._tool_manager.call_tool(
        "record_goal_failure",
        {"failure_kind": "unknown"},
        convert_result=True,
    )

    failures = runtime._service._store.load_goal_failures(  # type: ignore[union-attr]
        "1970-01-01T00:00:00+00:00"
    )
    invocations = runtime._service._store.load_invocations(  # type: ignore[union-attr]
        "1970-01-01T00:00:00+00:00"
    )
    assert [failure.primary_tool for failure in failures] == [None]
    assert invocations == []


@pytest.mark.parametrize("creation_order", ["full-first", "scoped-first"])
@pytest.mark.asyncio
async def test_automatic_learning_correlation_filters_peer_inactive_tools(
    creation_order,
    monkeypatch,
    tmp_path,
):
    config = LearningConfig(
        enabled=True,
        database_path=tmp_path / "learning.sqlite3",
        backlog_path=tmp_path / "improvement-backlog.md",
        retention_days=90,
        max_events=20_000,
        issue=None,
    )
    runtime = LearningRuntime(config_loader=lambda: config)
    monkeypatch.setattr(learning_tools, "learning_runtime", runtime)
    monkeypatch.setattr(learning_recorder, "_runtime", runtime)

    class PeerHvdcService:
        async def run_scenario(self, project_name, scenario, *, confirm):
            return {"status": "completed"}

    monkeypatch.setattr(hvdc_tools, "_service", PeerHvdcService)
    factories = {
        "full": lambda: create_server(environ={}),
        "scoped": lambda: create_server(
            environ={"PSCAD_MCP_TOOL_PROFILE": "core,learning"}
        ),
    }
    order = (
        ("full", "scoped")
        if creation_order == "full-first"
        else ("scoped", "full")
    )
    servers = {name: factories[name]() for name in order}

    await servers["full"]._tool_manager.call_tool(
        "run_hvdc_scenario",
        {
            "project_name": "peer-case",
            "scenario": {},
            "confirm": False,
        },
        convert_result=True,
    )
    await servers["full"]._tool_manager.call_tool(
        "record_goal_failure",
        {"failure_kind": "unknown"},
        convert_result=True,
    )
    _, scoped_result = await servers["scoped"]._tool_manager.call_tool(
        "record_goal_failure",
        {"failure_kind": "unknown"},
        convert_result=True,
    )

    failures = runtime._service._store.load_goal_failures(  # type: ignore[union-attr]
        "1970-01-01T00:00:00+00:00"
    )
    assert [failure.primary_tool for failure in failures] == [
        "run_hvdc_scenario",
        None,
    ]
    assert failures[0].correlated_invocation_id is not None
    assert failures[1].correlated_invocation_id is None
    assert "run_hvdc_scenario" not in repr(scoped_result)


def test_clear_learning_history_is_catalogued_as_destructive():
    spec = TOOL_SPECS["clear_learning_history"]

    assert spec.read_only is False
    assert spec.destructive is True
    assert spec.open_world is False
