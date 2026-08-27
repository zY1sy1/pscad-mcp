import json

import pytest

from pscad_mcp.main import create_server
from pscad_mcp.tools import capability_tools
from pscad_mcp.tools.capability_tools import build_capability_payload
from pscad_mcp.tools.catalog import (
    COMPATIBILITY_TOOL_NAMES,
    FULL_TOOL_NAMES,
    TOOL_GROUPS,
    TOOL_SPECS,
    parse_tool_profile,
)


def _names(server):
    return {tool.name for tool in server._tool_manager.list_tools()}


def _state(payload, name):
    return next(item for item in payload["capabilities"] if item["name"] == name)


def test_capability_tool_is_additive_and_always_on():
    default_names = _names(create_server(environ={}))
    core_names = _names(create_server(environ={"PSCAD_MCP_TOOL_PROFILE": "core"}))
    assert default_names == FULL_TOOL_NAMES
    assert default_names - COMPATIBILITY_TOOL_NAMES == {"get_pscad_capabilities"}
    assert core_names == TOOL_GROUPS["core"] | {"get_pscad_capabilities"}
    assert set(TOOL_SPECS) == FULL_TOOL_NAMES


def test_capability_states_are_bounded_and_backend_aware():
    disconnected = build_capability_payload(
        profile=parse_tool_profile({}),
        registered_names=FULL_TOOL_NAMES,
        connection={"connected": False, "backend": None, "version": None},
    )
    assert _state(disconnected, "list_projects")["state"] == "unknown"
    assert _state(disconnected, "review_improvement_backlog")["state"] == "supported"

    legacy = build_capability_payload(
        profile=parse_tool_profile({}),
        registered_names=FULL_TOOL_NAMES,
        connection={"connected": True, "backend": "legacy", "version": "4.6.2"},
    )
    assert _state(legacy, "build_lcc_model")["state"] == "supported"

    modern = build_capability_payload(
        profile=parse_tool_profile({}),
        registered_names=FULL_TOOL_NAMES,
        connection={"connected": True, "backend": "modern", "version": "5.0.2"},
    )
    assert _state(modern, "build_lcc_model") == {
        "name": "build_lcc_model",
        "group": "lcc",
        "state": "unavailable",
        "limitation_code": "LCC_BUILD_UNAVAILABLE",
    }


def test_capability_payload_is_exact_sorted_and_profile_local():
    profile = parse_tool_profile({"PSCAD_MCP_TOOL_PROFILE": "learning, core"})
    registered = TOOL_GROUPS["core"] | TOOL_GROUPS["learning"] | {
        "get_pscad_capabilities"
    }

    payload = build_capability_payload(
        profile=profile,
        registered_names=registered,
        connection={"connected": False, "backend": None, "version": None},
    )

    assert set(payload) == {
        "profile",
        "registered_groups",
        "registered_tools",
        "inactive_tools",
        "connection",
        "capabilities",
    }
    assert payload["profile"] == "core,learning"
    assert payload["registered_groups"] == ["core", "learning"]
    assert payload["registered_tools"] == sorted(registered)
    assert payload["inactive_tools"] == sorted(FULL_TOOL_NAMES - registered)
    names = [record["name"] for record in payload["capabilities"]]
    assert names == sorted(FULL_TOOL_NAMES)
    assert all(
        set(record) == {"name", "group", "state", "limitation_code"}
        for record in payload["capabilities"]
    )


def test_capability_payload_never_serializes_vendor_objects_or_raw_values():
    class VendorObject:
        def __repr__(self):
            return "SECRET_VENDOR_REPR"

    payload = build_capability_payload(
        profile=parse_tool_profile({}),
        registered_names=FULL_TOOL_NAMES,
        connection={
            "connected": True,
            "backend": VendorObject(),
            "version": "SECRET INVALID VERSION",
        },
    )
    encoded = json.dumps(payload)
    assert payload["connection"] == {
        "connected": False,
        "backend": None,
        "version": None,
    }
    assert "SECRET" not in encoded


def test_unknown_but_well_formed_backend_name_is_not_disclosed():
    payload = build_capability_payload(
        profile=parse_tool_profile({}),
        registered_names=FULL_TOOL_NAMES,
        connection={
            "connected": True,
            "backend": "secret_backend",
            "version": "4.6.2",
        },
    )

    assert payload["connection"] == {
        "connected": False,
        "backend": None,
        "version": None,
    }
    assert "secret_backend" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_registered_capability_tool_probes_status_without_learning(monkeypatch):
    calls = []

    async def status():
        calls.append(True)
        return {
            "connected": True,
            "backend": "legacy",
            "version": "4.6.2",
            "session": object(),
            "path": "SECRET_PATH",
        }

    monkeypatch.setattr(capability_tools.pscad_manager, "get_status", status)
    server = create_server(environ={"PSCAD_MCP_TOOL_PROFILE": "core"})
    tool = server._tool_manager.get_tool("get_pscad_capabilities")

    assert tool is not None
    assert tool.fn.__name__ == "get_pscad_capabilities"
    _, payload = await server._tool_manager.call_tool(
        "get_pscad_capabilities", {}, convert_result=True
    )
    assert calls == [True]
    assert payload["connection"] == {
        "connected": True,
        "backend": "legacy",
        "version": "4.6.2",
    }
    assert "SECRET" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_status_probe_failure_becomes_unknown_without_exception_text(monkeypatch):
    async def status():
        raise RuntimeError("SECRET_EXCEPTION_TEXT")

    monkeypatch.setattr(capability_tools.pscad_manager, "get_status", status)
    server = create_server(environ={})

    _, payload = await server._tool_manager.call_tool(
        "get_pscad_capabilities", {}, convert_result=True
    )
    assert payload["connection"] == {
        "connected": False,
        "backend": None,
        "version": None,
    }
    assert "SECRET" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_malformed_status_mapping_becomes_unknown_without_raw_error(monkeypatch):
    class ExplodingStatus(dict):
        def get(self, key, default=None):
            raise RuntimeError("SECRET_STATUS_MAPPING")

    async def status():
        return ExplodingStatus()

    monkeypatch.setattr(capability_tools.pscad_manager, "get_status", status)
    server = create_server(environ={})

    _, payload = await server._tool_manager.call_tool(
        "get_pscad_capabilities", {}, convert_result=True
    )
    assert payload["connection"] == {
        "connected": False,
        "backend": None,
        "version": None,
    }
    assert "SECRET" not in json.dumps(payload)
