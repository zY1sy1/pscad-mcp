from pscad_mcp.hvdc.classifier import classify_topology, extract_assets
from pscad_mcp.hvdc.models import HvdcProjectEvidence
from pscad_mcp.hvdc.scanner import scan_project


def test_classifier_reports_lcc_bipolar_breaker_with_evidence(tmp_path):
    path = tmp_path / "case.pscx"
    path.write_text(
        "<project><definitions>"
        "<Definition name='RectCC'/><Definition name='RectPole'/><Definition name='InverterPole'/>"
        "<Definition name='InvCtrl'/><Definition name='Rectifier_AC'/><Definition name='loadbreaker_3'/>"
        "<Definition name='TL1'/></definitions><canvas name='Main'>"
        "<component id='1' name='P1' definition='RectPole'/><component id='2' name='P2' definition='InverterPole'/>"
        "<component id='3' name='B1' definition='loadbreaker_3'/><component id='4' name='L1' definition='TL1'/>"
        "</canvas></project>", encoding="utf-8"
    )
    evidence = scan_project(path)
    summary = classify_topology(evidence)
    assert summary.family == "lcc"
    assert summary.polarity == "bipolar"
    assert summary.breaker_protection_present is True
    assert any("RectCC" in item for item in summary.evidence)
    assets = extract_assets(evidence)
    assert {asset.kind for asset in assets} >= {"rectifier", "inverter", "pole", "breaker", "dc_line"}


def test_definitions_classify_topology_but_do_not_create_instantiated_assets(tmp_path):
    path = tmp_path / "definitions_only.pscx"
    path.write_text(
        "<project><definitions><Definition name='RectCC'/><Definition name='RectPole'/>"
        "<Definition name='InverterPole'/><Definition name='loadbreaker_3'/><Definition name='TL1'/>"
        "</definitions><canvas name='Main'/></project>",
        encoding="utf-8",
    )
    evidence = scan_project(path)
    assert classify_topology(evidence).family == "lcc"
    assert extract_assets(evidence) == []


def test_classifier_does_not_force_family_from_one_generic_name():
    evidence = HvdcProjectEvidence("case.pscx", "case", None, definitions=("converter",))
    summary = classify_topology(evidence)
    assert summary.family == "unknown"
    assert summary.unresolved_questions


def test_explicit_annotation_overrides_weak_name_evidence(tmp_path):
    path = tmp_path / "case.pscx"
    path.write_text("<project><definitions><Definition name='converter'/></definitions><canvas name='Main'><label>Topology: VSC 2-level</label></canvas></project>", encoding="utf-8")
    summary = classify_topology(scan_project(path))
    assert summary.family == "vsc_2level"
    assert any("override" in item.lower() for item in summary.evidence)
