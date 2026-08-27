from __future__ import annotations

import json
from unittest.mock import patch
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.service import PscadService
from pscad_mcp.tools import registration as tool_registration
from pscad_mcp.tools.catalog import TOOL_SPECS, ToolSpec
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


@pytest.fixture
def catalog_test_tool(monkeypatch):
    test_specs = dict(TOOL_SPECS)
    monkeypatch.setattr(tool_registration, "TOOL_SPECS", test_specs)

    def catalog(function):
        test_specs[function.__name__] = ToolSpec(
            name=function.__name__,
            group="learning",
            description="Temporary catalogued tool for learning wrapper tests.",
            read_only=False,
            destructive=False,
            idempotent=False,
            open_world=False,
            backend_support=frozenset(),
        )

    return catalog


@pytest.fixture
def register_catalogued_test_tool(catalog_test_tool):
    def register(server, function, **kwargs):
        catalog_test_tool(function)
        register_tool(server, function, **kwargs)

    return register


def test_unresolved_annotations_fail_before_registration_side_effects(
    catalog_test_tool,
):
    async def invalid_annotations(value: str) -> str:
        return value

    invalid_annotations.__annotations__ = {
        "value": "MissingParameter",
        "return": "MissingReturn",
    }
    catalog_test_tool(invalid_annotations)
    recorder = ScalarRecorder()
    server = FastMCP("invalid-annotations")

    with pytest.raises(NameError, match="MissingParameter"):
        register_tool(server, invalid_annotations, recorder=recorder)

    assert server._tool_manager.get_tool("invalid_annotations") is None
    assert getattr(server, "_pscad_registered_tool_names", set()) == set()
    assert recorder.names == []
    assert recorder.events == []

    async def valid_annotations(value: str) -> str:
        return value

    valid_annotations.__name__ = "invalid_annotations"
    register_tool(server, valid_annotations, recorder=recorder)
    assert server._tool_manager.get_tool("invalid_annotations") is not None
    assert recorder.names == ["invalid_annotations"]


def test_native_same_name_tool_is_not_replaced_or_recorded(catalog_test_tool):
    async def native_tool() -> str:
        return "native"

    async def replacement_tool() -> str:
        return "replacement"

    native_tool.__name__ = "native_conflict"
    replacement_tool.__name__ = "native_conflict"
    catalog_test_tool(replacement_tool)
    recorder = ScalarRecorder()
    server = FastMCP("native-conflict")
    server.add_tool(native_tool)
    original = server._tool_manager.get_tool("native_conflict")

    with pytest.raises(ValueError, match="^native_conflict$"):
        register_tool(server, replacement_tool, recorder=recorder)

    assert server._tool_manager.get_tool("native_conflict") is original
    assert getattr(server, "_pscad_registered_tool_names", set()) == set()
    assert recorder.names == []
    assert recorder.events == []


def test_postprocessing_failure_rolls_back_and_allows_same_name_retry(
    catalog_test_tool,
    monkeypatch,
):
    async def partial_registration() -> str:
        return "registered"

    catalog_test_tool(partial_registration)
    recorder = ScalarRecorder()
    server = FastMCP("postprocessing-rollback")
    original_get_tool = server._tool_manager.get_tool
    original_remove_tool = server.remove_tool
    lookup_count = 0

    def fail_after_add(name):
        nonlocal lookup_count
        lookup_count += 1
        if lookup_count == 2:
            monkeypatch.setattr(
                server._tool_manager,
                "get_tool",
                original_get_tool,
            )
            raise RuntimeError("postprocessing failed")
        return original_get_tool(name)

    def remove_then_report_missing(name):
        original_remove_tool(name)
        raise ToolError(f"Unknown tool: {name}")

    monkeypatch.setattr(server._tool_manager, "get_tool", fail_after_add)
    monkeypatch.setattr(server, "remove_tool", remove_then_report_missing)

    with pytest.raises(RuntimeError, match="^postprocessing failed$"):
        register_tool(server, partial_registration, recorder=recorder)

    assert original_get_tool("partial_registration") is None
    assert getattr(server, "_pscad_registered_tool_names", set()) == set()
    assert recorder.names == []
    assert recorder.events == []

    register_tool(server, partial_registration, recorder=recorder)
    assert original_get_tool("partial_registration") is not None
    assert recorder.names == ["partial_registration"]


def test_missing_post_add_tool_is_a_bounded_registration_failure(
    catalog_test_tool,
    monkeypatch,
):
    async def missing_post_add() -> str:
        return "registered"

    catalog_test_tool(missing_post_add)
    recorder = ScalarRecorder()
    server = FastMCP("missing-post-add")
    original_get_tool = server._tool_manager.get_tool
    lookup_count = 0

    def hide_after_add(name):
        nonlocal lookup_count
        lookup_count += 1
        if lookup_count == 2:
            monkeypatch.setattr(
                server._tool_manager,
                "get_tool",
                original_get_tool,
            )
            return None
        return original_get_tool(name)

    monkeypatch.setattr(server._tool_manager, "get_tool", hide_after_add)

    with pytest.raises(RuntimeError, match="^missing_post_add$"):
        register_tool(server, missing_post_add, recorder=recorder)

    assert original_get_tool("missing_post_add") is None
    assert getattr(server, "_pscad_registered_tool_names", set()) == set()
    assert recorder.names == []
    assert recorder.events == []


@pytest.mark.asyncio
async def test_wrapper_preserves_success_and_records_only_scalars(
    register_catalogued_test_tool,
):
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
        register_catalogued_test_tool(server, sample, recorder=recorder)
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
async def test_wrapper_classifies_returned_and_raised_stable_errors(
    register_catalogued_test_tool,
):
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
    register_catalogued_test_tool(server, returned_error, recorder=recorder)
    register_catalogued_test_tool(server, raised_error, recorder=recorder)
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
async def test_wrapper_discards_malformed_error_metadata_without_echoing_it(
    register_catalogued_test_tool,
):
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
        register_catalogued_test_tool(server, malformed_error, recorder=recorder)
        await server._tool_manager.call_tool(
            "malformed_error", {}, convert_result=True
        )
    assert recorder.events[0]["error_code"] == "INTERNAL_ERROR"
    assert recorder.events[0]["retryable"] is None
    assert recorder.events[0]["backend"] == "legacy"
    assert "SECRET" not in repr(recorder.events)


@pytest.mark.asyncio
async def test_recorder_failure_never_replaces_original_result(
    register_catalogued_test_tool,
):
    async def sample():
        return "original"

    server = FastMCP("test")
    register_catalogued_test_tool(
        server,
        sample,
        recorder=ScalarRecorder(fail=True),
    )
    _, structured = await server._tool_manager.call_tool(
        "sample", {}, convert_result=True
    )
    assert structured["result"] == "original"


@pytest.mark.asyncio
async def test_record_learning_false_skips_names_snapshots_and_events(
    register_catalogued_test_tool,
):
    async def maintenance():
        return {"reviewed": True}

    recorder = ScalarRecorder()
    server = FastMCP("test")
    with patch(
        "pscad_mcp.tools.registration.pscad_manager.learning_snapshot"
    ) as snapshot:
        register_catalogued_test_tool(
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
async def test_unwrapped_result_with_result_key_is_preserved(
    register_catalogued_test_tool,
):
    result_object = {"result": "original", "value": "kept"}

    async def sample() -> dict[str, Any]:
        return result_object

    server = FastMCP("test")
    register_catalogued_test_tool(server, sample, record_learning=False)
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
async def test_nonfinite_float_is_not_reinserted_into_structured_result(
    value,
    register_catalogued_test_tool,
):
    result_object = {"value": value}

    async def sample() -> dict[str, float]:
        return result_object

    server = FastMCP("test")
    register_catalogued_test_tool(server, sample, record_learning=False)
    _, structured = await server._tool_manager.call_tool(
        "sample", {}, convert_result=True
    )
    assert structured["result"] is not result_object
    converted_value = structured["result"]["value"]
    json.dumps(structured, allow_nan=False)
    assert converted_value is None


@pytest.mark.asyncio
async def test_future_annotations_and_call_tool_result_register_cleanly(
    register_catalogued_test_tool,
):
    future_result = {"status": "ready"}
    call_result = CallToolResult(content=[], structuredContent={"ok": True})

    async def future_annotated() -> dict[str, str]:
        return future_result

    async def call_result_tool() -> CallToolResult:
        return call_result

    server = FastMCP("annotation-test")
    register_catalogued_test_tool(
        server,
        future_annotated,
        record_learning=False,
    )
    register_catalogued_test_tool(
        server,
        call_result_tool,
        record_learning=False,
    )

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
