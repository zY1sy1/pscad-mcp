from __future__ import annotations

import json
from unittest.mock import patch
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult

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


@pytest.mark.asyncio
async def test_unwrapped_result_with_result_key_is_preserved():
    result_object = {"result": "original", "value": "kept"}

    async def sample() -> dict[str, Any]:
        return result_object

    server = FastMCP("test")
    register_tool(server, sample, record_learning=False)
    tool = server._tool_manager._tools["sample"]
    assert tool.fn_metadata.output_schema is not None
    assert tool.fn_metadata.wrap_output is False
    _, structured = await server._tool_manager.call_tool(
        "sample", {}, convert_result=True
    )
    assert structured is result_object
    assert structured == result_object


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.asyncio
async def test_nonfinite_float_is_not_reinserted_into_structured_result(value):
    result_object = {"value": value}

    async def sample() -> dict[str, float]:
        return result_object

    server = FastMCP("test")
    register_tool(server, sample, record_learning=False)
    _, structured = await server._tool_manager.call_tool(
        "sample", {}, convert_result=True
    )
    assert structured["result"] is not result_object
    converted_value = structured["result"]["value"]
    json.dumps(structured, allow_nan=False)
    assert converted_value is None


@pytest.mark.asyncio
async def test_future_annotations_and_call_tool_result_register_cleanly():
    future_result = {"status": "ready"}
    call_result = CallToolResult(content=[], structuredContent={"ok": True})

    async def future_annotated() -> dict[str, str]:
        return future_result

    async def call_result_tool() -> CallToolResult:
        return call_result

    server = FastMCP("annotation-test")
    register_tool(server, future_annotated, record_learning=False)
    register_tool(server, call_result_tool, record_learning=False)

    _, structured = await server._tool_manager.call_tool(
        "future_annotated", {}, convert_result=True
    )
    assert structured["result"] is future_result
    returned = await server._tool_manager.call_tool(
        "call_result_tool", {}, convert_result=True
    )
    assert returned is call_result


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
