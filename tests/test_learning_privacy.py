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
