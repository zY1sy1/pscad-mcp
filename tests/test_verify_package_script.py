from pathlib import Path
import re


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
