from dataclasses import FrozenInstanceError

import pytest

from pscad_mcp.main import create_server
from pscad_mcp.tools.catalog import (
    COMPATIBILITY_TOOL_NAMES,
    FULL_TOOL_NAMES,
    TOOL_GROUPS,
    parse_tool_profile,
)


def _names(server):
    return {tool.name for tool in server._tool_manager.list_tools()}


def test_unset_profile_preserves_the_compatibility_inventory():
    names = _names(create_server(environ={}))

    assert len(names) == 83
    assert names == COMPATIBILITY_TOOL_NAMES == FULL_TOOL_NAMES


def test_full_profile_preserves_the_compatibility_inventory():
    names = _names(
        create_server(environ={"PSCAD_MCP_TOOL_PROFILE": " FuLl "})
    )

    assert len(names) == 83
    assert names == COMPATIBILITY_TOOL_NAMES == FULL_TOOL_NAMES


def test_core_profile_is_explicitly_smaller():
    names = _names(create_server(environ={"PSCAD_MCP_TOOL_PROFILE": "core"}))

    assert names == TOOL_GROUPS["core"]


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
