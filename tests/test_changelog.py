from pathlib import Path


def _unreleased_section(text: str) -> str:
    match = text.split("## [Unreleased]", maxsplit=1)
    assert len(match) == 2
    return match[1].split("## [", maxsplit=1)[0]


def test_changelog_describes_current_release_boundary():
    text = (Path(__file__).parents[1] / "CHANGELOG.md").read_text(encoding="utf-8").lower()

    assert "## [0.2.0]" in text
    assert "60" in text
    assert "simulation set" in text
    assert "pscad 4.6.2" in text
    assert "pscad 5.x" in text
    assert "contract" in text
    assert "silent learning" in text
    assert "83" in text


def test_unreleased_describes_horizontal_mcp_hardening():
    text = (Path(__file__).parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = _unreleased_section(text).lower()

    for phrase in (
        "horizontal hardening",
        "tool annotations",
        "runtime lifecycle",
        "local documentation",
    ):
        assert phrase in unreleased


def test_readmes_document_the_fixed_lcc_builder_boundary():
    root = Path(__file__).parents[1]
    english = (root / "README.md").read_text(encoding="utf-8").lower()
    chinese = (root / "docs" / "zh-CN" / "README.md").read_text(encoding="utf-8")

    for tool in ("plan_lcc_model", "build_lcc_model", "get_lcc_build_status", "validate_lcc_model"):
        assert tool in english
        assert tool in chinese
    for phrase in (
        "pscad 4.6.2",
        "fixed electrical parameters",
        "single-pole",
        "confirm=true",
        "plan hash",
        "original companion library",
        "workspace writes",
        "planned",
        "built",
        "simulated",
        "accepted",
        "licensed acceptance has not passed",
    ):
        assert phrase in english
    for phrase in ("PSCAD 4.6.2", "固定电气参数", "单极", "confirm=true", "工作区写入", "授权验收尚未通过"):
        assert phrase in chinese
