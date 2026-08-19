from pathlib import Path


def test_changelog_describes_current_release_boundary():
    text = (Path(__file__).parents[1] / "CHANGELOG.md").read_text(encoding="utf-8").lower()

    assert "## [0.2.0]" in text
    assert "60" in text
    assert "simulation set" in text
    assert "pscad 4.6.2" in text
    assert "pscad 5.x" in text
    assert "contract" in text
    assert "silent learning" in text
    assert "73" in text
