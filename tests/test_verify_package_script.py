from pathlib import Path


def test_package_verification_script_builds_installs_and_cleans_up():
    script = Path(__file__).parents[1] / "scripts" / "verify_package.ps1"

    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "pip wheel" in text
    assert "pip install" in text
    assert "Get-ChildItem" in text
    assert "Remove-Item -LiteralPath" in text
