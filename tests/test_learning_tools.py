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


@pytest.mark.asyncio
async def test_mcp_entry_rejects_an_arbitrary_kind_without_echoing_it():
    server = create_server()
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


def test_server_registers_87_unique_tools_and_silent_instructions():
    server = create_server()
    names = {tool.name for tool in server._tool_manager.list_tools()}
    assert len(names) == 87
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
