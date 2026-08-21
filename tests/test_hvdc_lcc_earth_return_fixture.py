import json
import pytest

from pscad_mcp.hvdc.classifier import classify_topology
from pscad_mcp.hvdc.scanner import scan_project

FIXTURE_DIR = __import__("pathlib").Path(__file__).parent / "fixtures" / "hvdc" / "lcc_earth_return"

@pytest.mark.parametrize("filename,mode,status", [
    ("bipolar_earth_return.pscx", "earth_return", "verified"),
    ("bipolar_metallic_return.pscx", "metallic_return", "verified"),
    ("positive_pole_outage_earth_return.pscx", "earth_return", "verified"),
    ("incomplete_return_path.pscx", "unknown", "incomplete"),
    ("ambiguous_return_mode.pscx", "unknown", "ambiguous"),
])
def test_lcc_earth_return_fixture_matrix(filename, mode, status):
    summary = classify_topology(scan_project(FIXTURE_DIR / filename))
    assert summary.family == "lcc"
    assert summary.polarity == "bipolar"
    assert summary.return_mode == mode
    assert summary.return_path_status == status

def test_verified_path_retains_source_refs():
    summary = classify_topology(scan_project(FIXTURE_DIR / "bipolar_earth_return.pscx"))
    assert all(item.project_path and item.canvas_name and item.component_id for path in summary.return_path for item in path.segments)
    json.dumps(summary, default=lambda value: value.__dict__)
