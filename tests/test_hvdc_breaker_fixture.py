from pathlib import Path

from pscad_mcp.hvdc.classifier import classify_topology, extract_assets
from pscad_mcp.hvdc.mappings import resolve_mappings
from pscad_mcp.hvdc.profiles import load_profile
from pscad_mcp.hvdc.scanner import scan_project


FIXTURE = Path(__file__).parent / "fixtures" / "hvdc" / "difforder_new.pscx"
REACHABLE_FIXTURE = Path(__file__).parent / "fixtures" / "hvdc" / "reachable_definitions.pscx"


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
    assert all(mapping.source and mapping.source.component_id for mapping in mappings.mappings if mapping.status == "observed")
    assert next(mapping for mapping in mappings.mappings if mapping.canonical == "dc_voltage").units is None
    profile = load_profile("hvdc_breaker_difforder")
    assert profile["profile_version"] == 2
    assert profile["command_bindings"] == []
    assert {item["canonical"] for item in profile["result_channels"]} == {
        "dc_voltage_breaker",
        "dc_current_breaker",
        "breaker_command_observed",
        "dc_voltage_rectifier_pole1",
        "dc_voltage_inverter_pole1",
        "dc_voltage_rectifier_pole2",
        "dc_voltage_inverter_pole2",
    }


def test_reachable_definition_evidence_resolves_current_control_and_line_interface():
    evidence = scan_project(REACHABLE_FIXTURE)
    assets = extract_assets(evidence)
    line = next(asset for asset in assets if asset.kind == "dc_line" and asset.source.canvas_name == "LineBlock")
    assert line.source.canvas_name == "LineBlock"
    component = next(item for item in evidence.components if item.source == line.source)
    assert {port["name"] for port in component.ports} == {"P1", "P2"}
    mappings = resolve_mappings(evidence, load_profile("hvdc_breaker_difforder"))
    by_name = {mapping.canonical: mapping for mapping in mappings.mappings}
    assert by_name["dc_current"].status == "observed"
    assert by_name["dc_current"].source.canvas_name == "BreakerBlock"
    assert by_name["dc_current"].source.definition == "master:ammeter"
    assert by_name["breaker_command"].status == "observed"
    assert by_name["breaker_command"].source.canvas_name == "BreakerBlock"
