from pscad_mcp.main import create_server
from pscad_mcp.tools.catalog import (
    COMPATIBILITY_TOOL_NAMES,
    FULL_TOOL_NAMES,
    TOOL_GROUPS,
)


def test_default_server_matches_the_full_tool_catalog():
    names = {tool.name for tool in create_server()._tool_manager.list_tools()}

    assert names == FULL_TOOL_NAMES
    assert COMPATIBILITY_TOOL_NAMES <= names


def test_compatibility_groups_form_a_disjoint_complete_partition():
    grouped_names = frozenset().union(*TOOL_GROUPS.values())

    assert grouped_names == COMPATIBILITY_TOOL_NAMES
    assert sum(len(names) for names in TOOL_GROUPS.values()) == len(grouped_names)
