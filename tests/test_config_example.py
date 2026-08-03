from pathlib import Path
import tomllib


def test_codex_config_template_is_portable():
    path = Path(__file__).parents[1] / "config.example.toml"
    path_text = path.read_text(encoding="utf-8")
    config = tomllib.loads(path_text)
    server = config["mcp_servers"]["pscad"]

    assert server["type"] == "stdio"
    assert server["args"] == ["-m", "pscad_mcp.main"]
    assert "PSCAD_MCP_BACKEND" in server["env"]
    assert r"D:\pscad-mcp" not in path_text
    assert r"D:\PSCAD-Workspace" not in path_text
