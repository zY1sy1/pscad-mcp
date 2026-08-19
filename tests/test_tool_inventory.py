from pscad_mcp.main import create_server


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


def test_server_preserves_the_exact_60_generic_tools_and_adds_hvdc_tools():
    tools = create_server()._tool_manager.list_tools()
    names = [tool.name for tool in tools]

    assert len(set(names)) == 74
    assert len(set(names) - HVDC_TOOLS - LEARNING_TOOLS - LCC_TOOLS) == 60
    assert HVDC_TOOLS <= set(names)
    assert LEARNING_TOOLS <= set(names)
    assert LCC_TOOLS <= set(names)
