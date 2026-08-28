from pscad_mcp.main import create_server
from pscad_mcp.tools.catalog import COMPATIBILITY_TOOL_NAMES, FULL_TOOL_NAMES


HVDC_TOOLS = {
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
LEARNING_TOOLS = {
    "record_goal_failure",
    "review_improvement_backlog",
    "clear_learning_history",
}

LCC_TOOLS = {
    "plan_lcc_model",
    "build_lcc_model",
    "get_lcc_build_status",
    "validate_lcc_model",
}
PARAMETRIC_LCC_TOOLS = {
    "derive_lcc_parameters",
    "audit_lcc_template",
    "plan_parametric_lcc_model",
    "build_parametric_lcc_model",
    "get_parametric_lcc_build_status",
    "validate_lcc_operating_modes",
}
TOPOLOGY_TOOLS = {
    "inspect_project_topology",
    "diagnose_project_topology",
}


def test_server_preserves_the_compatibility_inventory():
    tools = create_server(environ={})._tool_manager.list_tools()
    names = {tool.name for tool in tools}

    assert names == FULL_TOOL_NAMES
    assert COMPATIBILITY_TOOL_NAMES <= names
    assert HVDC_TOOLS <= COMPATIBILITY_TOOL_NAMES
    assert LEARNING_TOOLS <= COMPATIBILITY_TOOL_NAMES
    assert LCC_TOOLS <= COMPATIBILITY_TOOL_NAMES
    assert PARAMETRIC_LCC_TOOLS <= COMPATIBILITY_TOOL_NAMES
    assert TOPOLOGY_TOOLS <= COMPATIBILITY_TOOL_NAMES
