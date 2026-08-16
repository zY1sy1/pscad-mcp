from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def _read_project_version() -> str:
    project_path = Path(__file__).parents[1] / "pyproject.toml"
    document = tomllib.loads(project_path.read_text(encoding="utf-8"))
    return document["project"]["version"]


def test_built_wheel_is_installable_and_exposes_tools():
    wheel = os.environ.get("PSCAD_MCP_SMOKE_WHEEL")
    if not wheel:
        pytest.skip("Set PSCAD_MCP_SMOKE_WHEEL to run the isolated wheel smoke test.")

    wheel_path = Path(wheel).resolve()
    assert wheel_path.is_file()
    expected_version = _read_project_version()

    with tempfile.TemporaryDirectory() as temp_root:
        root = Path(temp_root)
        venv = root / "venv"
        cwd = root / "probe"
        cwd.mkdir()

        create_venv = subprocess.run(
            [sys.executable, "-m", "venv", str(venv)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert create_venv.returncode == 0, create_venv.stderr

        venv_python = venv / "Scripts" / "python.exe"
        assert venv_python.is_file()

        install = subprocess.run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                str(wheel_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert install.returncode == 0, install.stderr

        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["PYTHONNOUSERSITE"] = "1"
        probe = subprocess.run(
            [
                str(venv_python),
                "-c",
                (
                    "import importlib.metadata as metadata; "
                    "import pscad_mcp; "
                    "from pscad_mcp.main import create_server; "
                    "installed = metadata.version('pscad-mcp'); "
                    f"expected_version = {expected_version!r}; "
                    "assert installed == expected_version == pscad_mcp.__version__; "
                    "tools = create_server()._tool_manager.list_tools(); "
                    "assert len(tools) == 70; "
                    "assert len({tool.name for tool in tools}) == 70; "
                    "print(installed, len(tools))"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            env=env,
        )
        assert probe.returncode == 0, probe.stderr
        assert probe.stdout.strip() == f"{expected_version} 70"
