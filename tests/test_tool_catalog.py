from dataclasses import FrozenInstanceError

from mcp.server.fastmcp import FastMCP
from pscad_mcp.main import create_server
from pscad_mcp.tools.catalog import (
    COMPATIBILITY_TOOL_SPECS,
    COMPATIBILITY_TOOL_NAMES,
    FULL_TOOL_NAMES,
    TOOL_GROUPS,
    TOOL_SPECS,
)
from pscad_mcp.tools.project_tools import list_projects
from pscad_mcp.tools.registration import register_tool
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


def test_every_catalog_tool_has_bounded_description_and_annotations():
    assert TOOL_SPECS is COMPATIBILITY_TOOL_SPECS
    assert set(TOOL_SPECS) == COMPATIBILITY_TOOL_NAMES
    for name, spec in TOOL_SPECS.items():
        assert spec.name == name
        assert name in TOOL_GROUPS[spec.group]
        assert 12 <= len(spec.description) <= 240, name
        assert isinstance(spec.read_only, bool), name
        assert isinstance(spec.destructive, bool), name
        assert isinstance(spec.idempotent, bool), name
        assert isinstance(spec.open_world, bool), name
        assert isinstance(spec.backend_support, frozenset), name
        assert spec.backend_support <= {"legacy", "modern"}, name
        assert spec.limitation_code is None or (
            spec.limitation_code.isascii()
            and spec.limitation_code.replace("_", "").isalnum()
            and spec.limitation_code == spec.limitation_code.upper()
            and len(spec.limitation_code) <= 64
        )

    with pytest.raises(TypeError):
        TOOL_SPECS["new_tool"] = TOOL_SPECS["list_projects"]
    with pytest.raises(FrozenInstanceError):
        TOOL_SPECS["list_projects"].description = "Changed description"


def test_fastmcp_exposes_catalog_metadata_for_every_tool():
    by_name = {tool.name: tool for tool in create_server()._tool_manager.list_tools()}
    for name, spec in TOOL_SPECS.items():
        tool = by_name[name]
        assert tool.description == spec.description
        assert tool.annotations.title == name.replace("_", " ").title()
        assert tool.annotations.readOnlyHint is spec.read_only
        assert tool.annotations.destructiveHint is spec.destructive
        assert tool.annotations.idempotentHint is spec.idempotent
        assert tool.annotations.openWorldHint is spec.open_world


def test_component_deletion_is_catalogued_as_destructive():
    deletion = TOOL_SPECS["delete_component"]

    assert deletion.read_only is False
    assert deletion.destructive is True


@pytest.mark.parametrize(
    ("tool_name", "field", "expected"),
    [
        ("set_component_location", "idempotent", True),
        ("get_lcc_build_status", "open_world", True),
        ("validate_lcc_model", "backend_support", frozenset()),
        ("plan_parametric_lcc_model", "backend_support", frozenset()),
    ],
)
def test_capability_metadata_matches_verified_execution_boundaries(
    tool_name,
    field,
    expected,
):
    assert getattr(TOOL_SPECS[tool_name], field) == expected


def test_registration_rejects_duplicate_and_uncatalogued_primary_tools():
    server = FastMCP("catalog-contract")
    register_tool(server, list_projects, record_learning=False)
    with pytest.raises(ValueError, match="^list_projects$"):
        register_tool(server, list_projects, record_learning=False)

    async def uncatalogued_primary_tool() -> str:
        return "never registered"

    with pytest.raises(ValueError, match="^uncatalogued_primary_tool$"):
        register_tool(server, uncatalogued_primary_tool, record_learning=False)


def test_failed_fastmcp_registration_does_not_reserve_the_tool_name(monkeypatch):
    server = FastMCP("catalog-registration-retry")
    original_add_tool = server.add_tool

    def fail_once(*args, **kwargs):
        monkeypatch.setattr(server, "add_tool", original_add_tool)
        raise RuntimeError("registration failed")

    monkeypatch.setattr(server, "add_tool", fail_once)
    with pytest.raises(RuntimeError, match="registration failed"):
        register_tool(server, list_projects, record_learning=False)

    register_tool(server, list_projects, record_learning=False)
    assert server._tool_manager.get_tool("list_projects") is not None


def test_complex_inputs_have_model_facing_shape_examples():
    by_name = {tool.name: tool for tool in create_server()._tool_manager.list_tools()}

    expected_fields = {
        ("get_project_settings", "parameter_grid"): "action",
        ("set_project_settings", "settings"): "time_duration",
        ("set_project_settings", "parameter_grid"): "action",
        ("set_component_parameters", "parameters"): "parameter_name",
        ("validate_component_parameters", "parameters"): "parameter_name",
        ("set_simulation_task_parameters", "parameters"): "controlgroup",
        ("add_component", "parameters"): "parameter_name",
        ("create_component", "parameters"): "parameter_name",
        ("create_bus", "parameters"): "parameter_name",
        ("run_hvdc_scenario", "scenario"): "changes",
        ("derive_lcc_parameters", "request"): "base_mva",
        ("plan_parametric_lcc_model", "request"): "rated_power_mw",
        ("build_parametric_lcc_model", "request"): "rated_power_mw",
        ("validate_lcc_operating_modes", "events"): "time_s",
    }
    for (tool_name, parameter_name), expected in expected_fields.items():
        description = by_name[tool_name].parameters["properties"][parameter_name][
            "description"
        ]
        assert expected in description
        assert "{" in description and "}" in description
