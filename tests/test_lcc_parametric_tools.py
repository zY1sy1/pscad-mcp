from pscad_mcp.main import create_server


def test_parametric_lcc_tools_are_registered():
    names = {tool.name for tool in create_server()._tool_manager.list_tools()}
    expected = {
        "derive_lcc_parameters",
        "audit_lcc_template",
        "plan_parametric_lcc_model",
        "build_parametric_lcc_model",
        "get_parametric_lcc_build_status",
        "validate_lcc_operating_modes",
    }
    assert expected <= names
    assert len(names) == 83
