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


def test_server_preserves_the_exact_60_generic_tools_and_adds_hvdc_tools():
    tools = create_server()._tool_manager.list_tools()
    names = [tool.name for tool in tools]

    assert len(set(names)) == 70
    assert len(set(names) - HVDC_TOOLS) == 60
    assert HVDC_TOOLS <= set(names)
