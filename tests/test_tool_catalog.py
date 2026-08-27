from pscad_mcp.main import create_server
from pscad_mcp.tools.catalog import (
    COMPATIBILITY_TOOL_NAMES,
    FULL_TOOL_NAMES,
    TOOL_GROUPS,
)
import pytest


HVDC_TOOL_NAMES = frozenset(
    {
        "inspect_hvdc_project",
        "get_hvdc_assets",
        "get_hvdc_mappings",
        "validate_hvdc_project",
        "run_hvdc_scenario",
        "get_hvdc_scenario_status",
        "analyze_hvdc_results",
        "compare_hvdc_scenarios",
        "list_hvdc_profiles",
        "register_hvdc_profile",
    }
)
LCC_TOOL_NAMES = frozenset(
    {
        "plan_lcc_model",
        "build_lcc_model",
        "get_lcc_build_status",
        "validate_lcc_model",
    }
)
PARAMETRIC_LCC_TOOL_NAMES = frozenset(
    {
        "derive_lcc_parameters",
        "audit_lcc_template",
        "plan_parametric_lcc_model",
        "build_parametric_lcc_model",
        "get_parametric_lcc_build_status",
        "validate_lcc_operating_modes",
    }
)
LEARNING_TOOL_NAMES = frozenset(
    {
        "record_goal_failure",
        "review_improvement_backlog",
        "clear_learning_history",
    }
)


def test_default_server_matches_the_full_tool_catalog():
    names = {tool.name for tool in create_server()._tool_manager.list_tools()}

    assert names == FULL_TOOL_NAMES
    assert COMPATIBILITY_TOOL_NAMES <= names


def test_compatibility_groups_form_a_disjoint_complete_partition():
    grouped_names = frozenset().union(*TOOL_GROUPS.values())

    assert grouped_names == COMPATIBILITY_TOOL_NAMES
    assert sum(len(names) for names in TOOL_GROUPS.values()) == len(grouped_names)


def test_catalog_locks_group_boundaries_and_immutable_values():
    domain_tool_names = frozenset().union(
        HVDC_TOOL_NAMES,
        LCC_TOOL_NAMES,
        PARAMETRIC_LCC_TOOL_NAMES,
        LEARNING_TOOL_NAMES,
    )

    assert set(TOOL_GROUPS) == {"core", "hvdc", "lcc", "parametric_lcc", "learning"}
    assert {name: len(tools) for name, tools in TOOL_GROUPS.items()} == {
        "core": 60,
        "hvdc": 10,
        "lcc": 4,
        "parametric_lcc": 6,
        "learning": 3,
    }
    assert TOOL_GROUPS["hvdc"] == HVDC_TOOL_NAMES
    assert TOOL_GROUPS["lcc"] == LCC_TOOL_NAMES
    assert TOOL_GROUPS["parametric_lcc"] == PARAMETRIC_LCC_TOOL_NAMES
    assert TOOL_GROUPS["learning"] == LEARNING_TOOL_NAMES
    assert TOOL_GROUPS["core"] == COMPATIBILITY_TOOL_NAMES - domain_tool_names

    with pytest.raises(TypeError):
        TOOL_GROUPS["new_group"] = frozenset()
    with pytest.raises(AttributeError):
        TOOL_GROUPS["core"].add("new_tool")
