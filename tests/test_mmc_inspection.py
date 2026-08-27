from pscad_mcp.hvdc.builders.mmc.inspection import inspect_mmc_evidence
from pscad_mcp.hvdc.classifier import classify_topology
from pscad_mcp.hvdc.service import HvdcDomainService
from tests.mmc_parametric_fakes import load_mmc_synthetic_evidence


def test_mmc_inspection_uses_structure_for_terminal_and_polarity() -> None:
    report = inspect_mmc_evidence(load_mmc_synthetic_evidence("two_terminal_monopole"))
    assert report["family"] == "mmc"
    assert report["topology"] == "two_terminal_symmetrical_monopole"
    assert report["terminal_count"] == 2
    assert report["model_fidelity"] == "detailed_pwm"
    assert report["stations"] == ["STATION_P", "STATION_VDC"]
    assert report["unresolved_questions"] == []


def test_mmc_inspection_does_not_emit_lcc_return_path_questions() -> None:
    report = inspect_mmc_evidence(load_mmc_synthetic_evidence("incomplete_mmc"))
    assert report["unresolved_questions"]
    assert all("LCC" not in item for item in report["unresolved_questions"])


def test_generic_classifier_uses_mmc_terminal_and_polarity_evidence() -> None:
    summary = classify_topology(load_mmc_synthetic_evidence("two_terminal_monopole"))
    assert summary.family == "mmc"
    assert summary.polarity == "symmetrical_monopole"
    assert summary.terminal_count == 2
    assert summary.return_path_status == "not_applicable"
    assert all("LCC" not in item for item in summary.unresolved_questions)


def test_domain_inspection_attaches_mmc_report() -> None:
    path = load_mmc_synthetic_evidence("two_terminal_monopole").project_path
    result = HvdcDomainService().inspect_project(path)
    assert result["mmc"]["topology"] == "two_terminal_symmetrical_monopole"
