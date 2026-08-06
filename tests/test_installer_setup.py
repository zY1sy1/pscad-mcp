import json
import logging
import os
from unittest.mock import patch

import mcp_installer


def _logged_config(caplog):
    return json.loads(next(message for message in caplog.messages if message.startswith("{")))


def test_configured_workspace_is_included_in_setup_json(caplog):
    workspace = r"D:\PSCAD-Workspace"
    caplog.set_level(logging.INFO, logger="mcp-installer")

    with patch("mcp_installer.platform.system", return_value="Windows"), patch.object(
        mcp_installer.sys, "executable", r"C:\Python312\python.exe"
    ), patch.dict(
        os.environ,
        {
            "PSCAD_MCP_WORKSPACE": workspace,
            "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "false",
        },
        clear=True,
    ):
        mcp_installer.print_copilot_cli_setup()

    server = _logged_config(caplog)["mcpServers"]["pscad"]
    assert server["env"] == {
        "PSCAD_MCP_WORKSPACE": workspace,
        "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "false",
    }
    output = "\n".join(caplog.messages)
    assert f"PSCAD_MCP_WORKSPACE={workspace}" in output
    assert "PSCAD_MCP_ALLOW_UNSCOPED_PATHS=false" in output


def test_missing_workspace_warns_that_file_operations_are_unavailable(caplog):
    caplog.set_level(logging.INFO, logger="mcp-installer")

    with patch("mcp_installer.platform.system", return_value="Windows"), patch.object(
        mcp_installer.sys, "executable", r"C:\Python312\python.exe"
    ), patch.dict(os.environ, {}, clear=True):
        mcp_installer.print_copilot_cli_setup()

    output = "\n".join(caplog.messages)
    server = _logged_config(caplog)["mcpServers"]["pscad"]
    assert "WORKSPACE_NOT_CONFIGURED" in output
    assert "file operations are unavailable" in output.lower()
    assert "PSCAD_MCP_WORKSPACE" in output
    assert server["env"] == {"PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "false"}


def test_explicit_development_override_is_preserved_in_setup_json(caplog):
    caplog.set_level(logging.INFO, logger="mcp-installer")

    with patch("mcp_installer.platform.system", return_value="Windows"), patch.object(
        mcp_installer.sys, "executable", r"C:\Python312\python.exe"
    ), patch.dict(
        os.environ,
        {"PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "yes"},
        clear=True,
    ):
        mcp_installer.print_copilot_cli_setup()

    server = _logged_config(caplog)["mcpServers"]["pscad"]
    assert server["env"] == {"PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "true"}
