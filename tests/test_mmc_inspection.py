from pscad_mcp.hvdc.builders.mmc.inspection import inspect_mmc_evidence
from pscad_mcp.hvdc.classifier import classify_topology
from pscad_mcp.hvdc.models import (
    HvdcComponentRecord,
    HvdcProjectEvidence,
    HvdcSourceRef,
)
from pscad_mcp.hvdc.service import HvdcDomainService
from tests.mmc_parametric_fakes import load_mmc_synthetic_evidence


def test_native_observed_cells_are_twelve_distinct_station_arms():
    components = []
    for station in ("T1", "T2"):
        components.append(
            HvdcComponentRecord(station, station, "case:MFE_PWM_" + station)
        )
        for phase in "ABC":
            canvas = f"MFE_Pole_{station}_{phase}"
            for arm, signal in (("upper", "MmcVTop"), ("lower", "MmcVBtm")):
                components.append(
                    HvdcComponentRecord(
                        arm,
                        "FullCell",
                        "case:MmcObservedFullCell",
                        parameters={"MmcInserted": signal},
                        source=HvdcSourceRef("fixture", canvas_name=canvas),
                    )
                )
    evidence = HvdcProjectEvidence(
        "fixture", "case", "4.6.2", components=tuple(components)
    )
    report = inspect_mmc_evidence(evidence)
    assert report["terminal_count"] == 2
    assert report["converter"] == "full_bridge"
    assert len(report["arms"]) == 12
    assert {(a["station"], a["phase"], a["position"]) for a in report["arms"]} == {
        (s, p, a)
        for s in ("STATION_P", "STATION_VDC")
        for p in "ABC"
        for a in ("upper", "lower")
    }
    assert (
        report["topology"] == "unknown"
    )  # Cells alone do not prove the line connection.


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
