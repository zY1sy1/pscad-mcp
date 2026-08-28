from dataclasses import FrozenInstanceError

import pytest

from pscad_mcp.main import create_server
from pscad_mcp.tools.catalog import (
    COMPATIBILITY_TOOL_NAMES,
    FULL_TOOL_NAMES,
    TOOL_GROUPS,
    parse_tool_profile,
)
from pscad_mcp.tools.learning_tools import record_goal_failure
from pscad_mcp.tools.registration import register_tool


def _names(server):
    return {tool.name for tool in server._tool_manager.list_tools()}


def test_unset_profile_preserves_the_compatibility_inventory(monkeypatch):
    monkeypatch.setenv("PSCAD_MCP_TOOL_PROFILE", "core")
    names = _names(create_server(environ={}))

    assert len(names) == 84
    assert names == FULL_TOOL_NAMES
    assert names - COMPATIBILITY_TOOL_NAMES == {"get_pscad_capabilities"}


def test_default_factory_reads_the_process_environment(monkeypatch):
    monkeypatch.setenv("PSCAD_MCP_TOOL_PROFILE", "core")

    assert _names(create_server()) == TOOL_GROUPS["core"] | {
        "get_pscad_capabilities"
    }


def test_full_profile_preserves_the_compatibility_inventory():
    names = _names(
        create_server(environ={"PSCAD_MCP_TOOL_PROFILE": " FuLl "})
    )

    assert len(names) == 84
    assert names == FULL_TOOL_NAMES
    assert names - COMPATIBILITY_TOOL_NAMES == {"get_pscad_capabilities"}


def test_core_profile_is_explicitly_smaller():
    names = _names(create_server(environ={"PSCAD_MCP_TOOL_PROFILE": "core"}))

    assert names == TOOL_GROUPS["core"] | {"get_pscad_capabilities"}


@pytest.mark.parametrize(
    "environ",
    [{}, {"PSCAD_MCP_TOOL_PROFILE": "core"}],
    ids=["full", "core"],
)
def test_factory_profile_rejects_uncatalogued_primary_tools(environ):
    server = create_server(environ=environ)

    async def uncatalogued_primary_tool() -> str:
        return "never registered"

    with pytest.raises(ValueError, match=r"^uncatalogued_primary_tool$"):
        register_tool(
            server,
            uncatalogued_primary_tool,
            record_learning=False,
        )


def test_forced_registration_bypasses_only_profile_filtering():
    server = create_server(environ={"PSCAD_MCP_TOOL_PROFILE": "core"})

    register_tool(
        server,
        record_goal_failure,
        record_learning=False,
        force=True,
    )
    assert server._tool_manager.get_tool("record_goal_failure") is not None

    with pytest.raises(ValueError, match=r"^record_goal_failure$"):
        register_tool(
            server,
            record_goal_failure,
            record_learning=False,
            force=True,
        )

    async def uncatalogued_forced_tool() -> str:
        return "never registered"

    with pytest.raises(ValueError, match=r"^uncatalogued_forced_tool$"):
        register_tool(
            server,
            uncatalogued_forced_tool,
            record_learning=False,
            force=True,
        )


def test_invalid_profile_does_not_echo_the_value():
    secret = "SECRET_PROFILE_VALUE"

    with pytest.raises(ValueError) as raised:
        parse_tool_profile({"PSCAD_MCP_TOOL_PROFILE": secret})

    assert str(raised.value) == "INVALID_TOOL_PROFILE: PSCAD_MCP_TOOL_PROFILE"
    assert secret not in str(raised.value)


@pytest.mark.parametrize("raw", ["", ",", " , ", "core,unknown"])
def test_empty_or_unknown_profile_is_rejected(raw):
    with pytest.raises(
        ValueError,
        match=r"^INVALID_TOOL_PROFILE: PSCAD_MCP_TOOL_PROFILE$",
    ):
        parse_tool_profile({"PSCAD_MCP_TOOL_PROFILE": raw})


@pytest.mark.parametrize("raw", [None, b"SECRET", 7, [], {}])
def test_explicit_non_string_profile_is_rejected_without_echoing(raw):
    with pytest.raises(ValueError) as raised:
        parse_tool_profile(  # type: ignore[arg-type]
            {"PSCAD_MCP_TOOL_PROFILE": raw}
        )

    assert str(raised.value) == "INVALID_TOOL_PROFILE: PSCAD_MCP_TOOL_PROFILE"
    assert repr(raw) not in str(raised.value)


def test_profile_normalizes_whitespace_case_order_and_duplicates():
    profile = parse_tool_profile(
        {"PSCAD_MCP_TOOL_PROFILE": " HVDC, core,CORE "}
    )

    assert profile.label == "core,hvdc"
    assert profile.groups == frozenset({"core", "hvdc"})
    assert profile.includes("list_projects") is True
    assert profile.includes("inspect_hvdc_project") is True
    assert profile.includes("plan_lcc_model") is False
    with pytest.raises(FrozenInstanceError):
        profile.label = "changed"
