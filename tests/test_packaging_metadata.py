from pathlib import Path
import importlib.metadata

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


def test_project_packages_recursive_lcc_asset_set():
    path = Path(__file__).parents[1] / "pyproject.toml"
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    patterns = document["tool"]["setuptools"]["package-data"]["pscad_mcp"]

    assert "assets/lcc/*/*.json" in patterns
    assert "assets/lcc/*/*.md" in patterns
    assert "assets/lcc/*/library/*.pslx" in patterns


def test_runtime_version_matches_project_metadata():
    path = Path(__file__).parents[1] / "pyproject.toml"
    document = tomllib.loads(path.read_text(encoding="utf-8"))

    assert pscad_mcp.__version__ == document["project"]["version"]


def test_installed_metadata_matches_runtime_version_when_available():
    try:
        installed_version = importlib.metadata.version("pscad-mcp")
    except importlib.metadata.PackageNotFoundError:
        return

    assert installed_version == pscad_mcp.__version__
