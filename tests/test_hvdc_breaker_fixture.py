from pathlib import Path

from pscad_mcp.hvdc.classifier import classify_topology, extract_assets
from pscad_mcp.hvdc.mappings import resolve_mappings
from pscad_mcp.hvdc.profiles import load_profile
from pscad_mcp.hvdc.scanner import scan_project


FIXTURE = Path(__file__).parent / "fixtures" / "hvdc" / "difforder_new.pscx"


def test_breaker_fixture_contains_domain_evidence():
    evidence = scan_project(FIXTURE)
    summary = classify_topology(evidence)
    assert summary.family == "lcc"
    assert summary.polarity == "bipolar"
    assert summary.breaker_protection_present
    assert summary.dc_line_present
    kinds = {asset.kind for asset in extract_assets(evidence)}
    assert {"rectifier", "inverter", "pole", "breaker", "dc_line"} <= kinds
    mappings = resolve_mappings(evidence, load_profile("hvdc_breaker_difforder"))
    assert {mapping.canonical for mapping in mappings.mappings if mapping.status == "observed"} >= {"dc_current", "dc_voltage", "breaker_command", "breaker_status", "protection_trip"}
