from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest


def test_built_wheel_is_installable_and_exposes_tools():
    wheel = os.environ.get("PSCAD_MCP_SMOKE_WHEEL")
    if not wheel:
        pytest.skip("Set PSCAD_MCP_SMOKE_WHEEL to run the isolated wheel smoke test.")

    wheel_path = Path(wheel).resolve()
    assert wheel_path.is_file()

    with tempfile.TemporaryDirectory() as target, tempfile.TemporaryDirectory() as cwd:
        install = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--target",
                target,
                str(wheel_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert install.returncode == 0, install.stderr

        env = os.environ.copy()
        env["PYTHONPATH"] = target
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.metadata as metadata; "
                    "import pscad_mcp; "
                    "from pscad_mcp.main import create_server; "
                    "assert metadata.version('pscad-mcp') == '0.2.0'; "
                    "tools = create_server()._tool_manager.list_tools(); "
                    "assert len(tools) == 60; "
                    "assert len({tool.name for tool in tools}) == 60; "
                    "print(pscad_mcp.__version__, len(tools))"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
        )
        assert probe.returncode == 0, probe.stderr
        assert probe.stdout.strip() == "0.2.0 60"
