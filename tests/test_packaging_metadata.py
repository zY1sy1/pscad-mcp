from pathlib import Path

import pscad_mcp

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def test_project_declares_release_and_dev_metadata():
    path = Path(__file__).parents[1] / "pyproject.toml"
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    project = document["project"]

    assert project["version"] == "0.2.0"
    assert "pytest" in " ".join(project["optional-dependencies"]["dev"])


def test_runtime_version_matches_project_metadata():
    path = Path(__file__).parents[1] / "pyproject.toml"
    document = tomllib.loads(path.read_text(encoding="utf-8"))

    assert pscad_mcp.__version__ == document["project"]["version"]
