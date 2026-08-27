import copy
import json

import pytest

from pscad_mcp.topology.acceptance import (
    validate_acceptance_report,
    write_acceptance_report,
)


def _case(
    name,
    marker,
    object_count,
    elapsed_ms,
    *,
    healthy,
    error_codes=(),
    unresolved_codes=(),
    confirmed_edges=(),
):
    digest = marker * 64
    return {
        "name": name,
        "healthy": healthy,
        "source_sha256": digest,
        "before_sha256": digest,
        "after_sha256": digest,
        "topology_hashes": [digest, digest],
        "inventory_hashes": [digest, digest],
        "dirty_state": {"available": False, "before": None, "after": None},
        "elapsed_ms": elapsed_ms,
        "phase_timings_ms": {
            "live_capture": 10.0,
            "file_parse": 10.0,
            "reconcile": 10.0,
            "connectivity": 20.0,
            "generic_rules": 10.0,
        },
        "object_count": object_count,
        "source_capabilities": {
            "components": True,
            "ports": True,
            "conductors": True,
            "labels": True,
            "hierarchy": True,
            "dirty_state": False,
        },
        "finding_counts": {
            "info": 0,
            "warning": len(unresolved_codes),
            "error": len(error_codes),
        },
        "expected_confirmed_edges": list(confirmed_edges),
        "observed_confirmed_edges": list(confirmed_edges),
        "expected_error_codes": list(error_codes),
        "observed_error_codes": list(error_codes),
        "expected_unresolved_codes": list(unresolved_codes),
        "observed_unresolved_codes": list(unresolved_codes),
        "candidate_edges_confirmed": False,
    }


def valid_report():
    seeded_codes = (
        "LABEL_CONFLICT",
        "PORT_DIMENSION_MISMATCH",
        "PORT_KIND_MISMATCH",
        "REQUIRED_PORT_UNCONNECTED",
        "WIRE_DANGLING_ENDPOINT",
    )
    return {
        "schema_version": 1,
        "status": "PASS",
        "commit": "a" * 40,
        "rule_version": "generic-v1",
        "pscad": {
            "version": "4.6.2",
            "backend": "legacy",
            "licensed": True,
        },
        "cases": [
            _case(
                "ordinary",
                "b",
                500,
                120.0,
                healthy=True,
                confirmed_edges=("Main:1:A|Main:2:B",),
            ),
            _case(
                "seeded-defects",
                "c",
                100,
                80.0,
                healthy=False,
                error_codes=seeded_codes,
            ),
            _case(
                "uncertain-evidence",
                "d",
                100,
                90.0,
                healthy=False,
                unresolved_codes=("hierarchy_boundary_unconfirmed:Main:7:IN",),
            ),
            _case("scale-2000", "e", 2000, 9000.0, healthy=True),
        ],
        "coverage_codes": list(seeded_codes),
    }


def damage_report(report, damage):
    case = report["cases"][0]
    if damage == "changed_file":
        case["after_sha256"] = "f" * 64
    elif damage == "nondeterministic_topology":
        case["topology_hashes"][1] = "f" * 64
    elif damage == "object_mutation":
        case["inventory_hashes"][1] = "f" * 64
    elif damage == "false_error":
        case["observed_error_codes"] = ["WIRE_DANGLING_ENDPOINT"]
    elif damage == "connection_mismatch":
        case["observed_confirmed_edges"] = []
    elif damage == "dirty_state_changed":
        case["dirty_state"] = {
            "available": True,
            "before": False,
            "after": True,
        }
    elif damage == "candidate_promoted":
        report["cases"][2]["candidate_edges_confirmed"] = True
    elif damage == "uncertainty_guessed":
        report["cases"][2]["observed_unresolved_codes"] = []
    elif damage == "missing_seeded_coverage":
        report["coverage_codes"].remove("LABEL_CONFLICT")
    elif damage == "slow_500_object_case":
        case["elapsed_ms"] = 3000.1
    elif damage == "slow_2000_object_case":
        report["cases"][3]["elapsed_ms"] = 10000.1
    elif damage == "missing_phase_timing":
        del case["phase_timings_ms"]["connectivity"]
    elif damage == "missing_source_capability":
        case["source_capabilities"] = {}
    else:
        raise AssertionError(f"unknown damage case: {damage}")


def test_valid_pass_report_is_json_safe():
    report = validate_acceptance_report(valid_report())
    assert report["status"] == "PASS"
    json.dumps(report)


@pytest.mark.parametrize(
    "damage",
    [
        "changed_file",
        "nondeterministic_topology",
        "object_mutation",
        "false_error",
        "connection_mismatch",
        "dirty_state_changed",
        "candidate_promoted",
        "uncertainty_guessed",
        "missing_seeded_coverage",
        "slow_500_object_case",
        "slow_2000_object_case",
        "missing_phase_timing",
        "missing_source_capability",
    ],
)
def test_pass_report_rejects_missing_readonly_truth_or_performance_evidence(
    damage,
):
    report = copy.deepcopy(valid_report())
    damage_report(report, damage)
    with pytest.raises(ValueError):
        validate_acceptance_report(report)


@pytest.mark.parametrize("status", ["pass", "UNKNOWN", ""])
def test_report_rejects_unknown_status(status):
    report = valid_report()
    report["status"] = status
    with pytest.raises(ValueError, match="status"):
        validate_acceptance_report(report)


def test_writer_publishes_valid_utf8_json_atomically(tmp_path):
    destination = tmp_path / "acceptance-report.json"

    written = write_acceptance_report(destination, valid_report())

    assert written == destination
    assert json.loads(destination.read_text(encoding="utf-8")) == valid_report()
    assert list(tmp_path.iterdir()) == [destination]


def test_writer_does_not_publish_an_invalid_report(tmp_path):
    destination = tmp_path / "acceptance-report.json"
    report = valid_report()
    report["status"] = "UNKNOWN"

    with pytest.raises(ValueError, match="status"):
        write_acceptance_report(destination, report)

    assert not destination.exists()
