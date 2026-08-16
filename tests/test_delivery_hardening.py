from __future__ import annotations

import importlib
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 CI
    import tomli as tomllib


ROOT = Path(__file__).parents[1]


def _read_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_package_metadata_declares_release_version_and_dev_dependencies():
    project = _read_toml(ROOT / "pyproject.toml")["project"]

    assert project["version"] == "0.2.0"
    assert project["requires-python"] == ">=3.10"
    requirements = project["optional-dependencies"]["dev"]
    assert any(item.startswith("pytest") for item in requirements)
    assert any("tomli" in item for item in requirements)
    assert importlib.import_module("pscad_mcp").__version__ == "0.2.0"


def test_portable_config_example_describes_stdio_and_pscad_environment():
    config = _read_toml(ROOT / "config.example.toml")
    server = config["mcp_servers"]["pscad"]

    assert server["type"] == "stdio"
    assert server["args"] == ["-m", "pscad_mcp.main"]
    assert server["command"]
    for key in (
        "PSCAD_MCP_BACKEND",
        "PSCAD_MCP_VERSION",
        "PSCAD_MCP_X64",
        "PSCAD_MCP_WORKSPACE",
    ):
        assert key in server["env"]


def test_release_notes_cover_all_approved_batches():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "0.2.0" in changelog
    for phrase in (
        "Delivery hardening",
        "NOT_LICENSED",
        "PSOUT",
        "parameter-grid",
    ):
        assert phrase in changelog


def test_windows_ci_covers_supported_python_versions_and_release_gates():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    for version in ("3.10", "3.11", "3.12"):
        assert version in workflow
    assert "python -m pip check" in workflow
    assert "python -m compileall -q pscad_mcp tests" in workflow
    assert "print(len(tools), len({tool.name for tool in tools}))" in workflow
    assert "70 70" in workflow
