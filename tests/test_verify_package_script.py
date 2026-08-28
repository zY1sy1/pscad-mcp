import importlib.metadata as metadata
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
import pscad_mcp
from pscad_mcp.hvdc.builders.lcc import assets
import pscad_mcp.main as main
from pscad_mcp.tools.catalog import FULL_TOOL_NAMES
from pscad_mcp.tools import catalog
from tests.test_install_smoke import _build_probe


def test_package_verification_script_builds_installs_and_cleans_up():
    script = Path(__file__).parents[1] / "scripts" / "verify_package.ps1"

    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "pip wheel" in text
    assert "python -m venv" in text
    assert "Scripts\\python.exe" in text
    assert "pip install" in text
    assert "pip install --no-deps --target" not in text
    assert "Get-ChildItem" in text
    assert "Remove-Item -LiteralPath" in text


def test_package_verification_isolates_pythonpath_before_building_wheel():
    script = Path(__file__).parents[1] / "scripts" / "verify_package.ps1"
    text = script.read_text(encoding="utf-8")

    clear = text.index("Remove-Item Env:PYTHONPATH")
    build = text.index("-m pip wheel")
    assert clear < build


def test_package_smoke_probes_do_not_hardcode_release_version():
    root = Path(__file__).parents[1]

    for relative in ("scripts/verify_package.ps1", "tests/test_install_smoke.py"):
        text = (root / relative).read_text(encoding="utf-8")
        assert not re.search(r"(?<![\w])\d+\.\d+\.\d+(?![\w])", text), relative
        assert "pscad_mcp.__version__" in text


def test_python_smoke_reads_expected_version_from_project_metadata():
    smoke = (Path(__file__).parents[1] / "tests" / "test_install_smoke.py").read_text(
        encoding="utf-8"
    )

    assert "pyproject.toml" in smoke
    assert "expected_version" in smoke


def test_package_probes_compare_the_full_catalog_without_literal_inventory_counts():
    root = Path(__file__).parents[1]

    probes = (
        (root / "scripts" / "verify_package.ps1").read_text(encoding="utf-8"),
        _build_probe("expected_version"),
    )
    for text in probes:
        assert "from pscad_mcp.tools.catalog import FULL_TOOL_NAMES" in text
        assert "{tool.name for tool in tools} != FULL_TOOL_NAMES" in text
        assert "raise RuntimeError" in text
        assert not re.search(r"assert\s+len\(tools\)\s*==\s*(?:77|83)", text)
        assert not re.search(
            r"assert\s+len\(\{tool\.name for tool in tools\}\)\s*==\s*(?:77|83)",
            text,
        )

    script = (root / "scripts" / "verify_package.ps1").read_text(encoding="utf-8")
    assert "Remove-Item Env:PSCAD_MCP_TOOL_PROFILE" in script
    assert str(len(FULL_TOOL_NAMES)) not in script


def _package_script_probe() -> str:
    script = (Path(__file__).parents[1] / "scripts" / "verify_package.ps1").read_text(
        encoding="utf-8"
    )
    match = re.search(r'\$probe = @"\r?\n(?P<probe>.*?)\r?\n"@', script, re.DOTALL)

    assert match is not None
    return match.group("probe")


def _run_probe_with_optimized_python(probe: str, monkeypatch: pytest.MonkeyPatch, failure: str):
    tool = SimpleNamespace(name="expected_tool")
    server = SimpleNamespace(
        _tool_manager=SimpleNamespace(list_tools=lambda: [tool])
    )
    asset_set = SimpleNamespace(
        name="cigre_lcc_monopole_v1", pscad_version="4.6", hashes={}
    )

    monkeypatch.setattr(metadata, "version", lambda _: "expected_version")
    monkeypatch.setattr(pscad_mcp, "__version__", "expected_version")
    monkeypatch.setattr(main, "create_server", lambda: server)
    monkeypatch.setattr(catalog, "FULL_TOOL_NAMES", frozenset({"expected_tool"}))
    monkeypatch.setattr(assets, "load_packaged_asset_set", lambda: asset_set)

    if failure == "version":
        monkeypatch.setattr(metadata, "version", lambda _: "unexpected_version")
    elif failure == "inventory":
        tool.name = "unexpected_tool"
    elif failure == "asset_name":
        asset_set.name = "unexpected_asset"
    elif failure == "asset_version":
        asset_set.pscad_version = "5.0"

    with pytest.raises(RuntimeError):
        exec(compile(probe, "<package-probe>", "exec", optimize=1), {})


@pytest.mark.parametrize("failure", ["version", "inventory", "asset_name", "asset_version"])
@pytest.mark.parametrize(
    "probe",
    [_package_script_probe(), _build_probe("expected_version")],
    ids=["powershell", "wheel_smoke"],
)
def test_package_probes_keep_runtime_validations_under_optimization(
    probe: str, failure: str, monkeypatch: pytest.MonkeyPatch
):
    _run_probe_with_optimized_python(probe, monkeypatch, failure)
