from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def test_codex_config_template_is_portable():
    path = Path(__file__).parents[1] / "config.example.toml"
    path_text = path.read_text(encoding="utf-8")
    config = tomllib.loads(path_text)
    server = config["mcp_servers"]["pscad"]

    assert server["type"] == "stdio"
    assert server["args"] == ["-m", "pscad_mcp.main"]
    assert "PSCAD_MCP_BACKEND" in server["env"]
    assert server["env"]["PSCAD_MCP_ALLOW_UNSCOPED_PATHS"] == "false"
    assert r"D:\pscad-mcp" not in path_text
    assert r"D:\PSCAD-Workspace" not in path_text


def test_workspace_safety_is_documented_in_both_languages():
    root = Path(__file__).parents[1]
    for relative in ("README.md", "docs/zh-CN/README.md"):
        text = (root / relative).read_text(encoding="utf-8")
        assert "PSCAD_MCP_ALLOW_UNSCOPED_PATHS" in text
        assert "WORKSPACE_NOT_CONFIGURED" in text


def test_readme_copilot_configuration_includes_workspace_environment():
    text = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert '"env": {' in text
    assert '"PSCAD_MCP_WORKSPACE": "C:\\\\path\\\\to\\\\PSCAD-Workspace"' in text
    assert '"PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "false"' in text
