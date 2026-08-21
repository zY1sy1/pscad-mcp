from pathlib import Path

from pscad_mcp.hvdc.classifier import classify_topology
from pscad_mcp.hvdc.scanner import scan_project

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "hvdc" / "lcc_earth_return"


def test_classifies_verified_earth_return():
    summary = classify_topology(scan_project(FIXTURE_DIR / "bipolar_earth_return.pscx"))
    assert summary.family == "lcc"
    assert summary.polarity == "bipolar"
    assert summary.return_mode == "earth_return"
    assert summary.return_path_status == "verified"


def test_classifies_verified_metallic_return():
    summary = classify_topology(scan_project(FIXTURE_DIR / "bipolar_metallic_return.pscx"))
    assert summary.return_mode == "metallic_return"
    assert summary.return_path_status == "verified"


def test_classifies_single_pole_earth_return():
    summary = classify_topology(scan_project(FIXTURE_DIR / "positive_pole_outage_earth_return.pscx"))
    assert summary.polarity == "bipolar"
    assert summary.return_mode == "earth_return"
    assert "positive" in summary.pole_roles


def test_does_not_guess_when_return_path_is_ambiguous():
    summary = classify_topology(scan_project(FIXTURE_DIR / "ambiguous_return_mode.pscx"))
    assert summary.return_mode == "unknown"
    assert summary.return_path_status == "ambiguous"
    assert summary.unresolved_questions
