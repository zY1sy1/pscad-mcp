from pathlib import Path
import importlib.metadata

import pscad_mcp
from tests.mmc_parametric_fakes import built_wheel_names

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
    assert "assets/blueprints/*/*.json" in patterns


def test_project_packages_blueprint_corpus_assets():
    path = Path(__file__).parents[1] / "pyproject.toml"
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    patterns = document["tool"]["setuptools"]["package-data"]["pscad_mcp"]

    assert "assets/corpora/*/*.json" in patterns
    assert "assets/corpora/*/graphs/*.json" in patterns
    assert "assets/corpora/*/records/*.jsonl" in patterns


def test_canonical_corpus_assets_keep_lf_line_endings_on_checkout():
    root = Path(__file__).parents[1]
    attributes = (root / ".gitattributes").read_text(encoding="ascii").splitlines()

    assert "pscad_mcp/assets/corpora/*/*.json text eol=lf" in attributes
    assert "pscad_mcp/assets/corpora/*/graphs/*.json text eol=lf" in attributes
    assert "pscad_mcp/assets/corpora/*/records/*.jsonl text eol=lf" in attributes
    assert "pscad_mcp/assets/blueprints/*/*.json text eol=lf" in attributes


def test_project_packages_only_the_declared_mmc_asset_shapes():
    path = Path(__file__).parents[1] / "pyproject.toml"
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    patterns = document["tool"]["setuptools"]["package-data"]["pscad_mcp"]

    assert "assets/mmc/*/*.json" in patterns
    assert "assets/mmc/*/*.md" in patterns
    assert "assets/mmc/*/library/*.pslx" in patterns


def test_wheel_contains_owned_avm_assets_and_no_official_example():
    names = built_wheel_names()

    assert any(
        name.endswith("assets/mmc/cigre_b4_p2p_avm_v1/manifest.json")
        for name in names
    )
    assert not any(
        "H_MMC_Mono_DC" in name or name.endswith("intermediate.pslx")
        for name in names
    )


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
