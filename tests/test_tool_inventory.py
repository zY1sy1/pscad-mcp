from pscad_mcp.main import create_server


def test_server_exposes_exactly_60_unique_tools():
    tools = create_server()._tool_manager.list_tools()
    names = [tool.name for tool in tools]

    assert len(names) == 60
    assert len(set(names)) == 60
