from dataclasses import replace
from pathlib import Path

from pscad_mcp.hvdc.classifier import classify_topology
from pscad_mcp.topology.adapters.hvdc import topology_to_hvdc_evidence
from pscad_mcp.topology.connectivity import build_connectivity
from pscad_mcp.topology.diagnostics.hvdc import diagnose_hvdc
from pscad_mcp.topology.models import ProjectTopology
from pscad_mcp.topology.providers.pscx import PscxSnapshotProvider
from pscad_mcp.topology.reconcile import reconcile_snapshots
from tests.topology_fakes import topology_with_candidate_only_connection


FIXTURE = Path(__file__).parent / "fixtures" / "topology" / "hvdc_lcc.pscx"


def canonical_hvdc_topology():
    saved = PscxSnapshotProvider().read(FIXTURE, "Main")
    return build_connectivity(reconcile_snapshots(None, saved)).topology


def test_adapter_preserves_components_labels_ports_and_confirmed_connections():
    topology = canonical_hvdc_topology()

    evidence = topology_to_hvdc_evidence(topology)

    assert len(evidence.components) == len(topology.components)
    assert len(evidence.labels) == len(topology.labels)
    assert sum(len(item.ports) for item in evidence.components) == sum(
        len(item.ports) for item in topology.components
    )
    assert evidence.connections
    assert all(
        record.evidence[0].startswith("topology_net:")
        for record in evidence.connections
    )
    assert classify_topology(evidence).family == "lcc"


def test_adapter_never_uses_candidate_edges_as_hvdc_connections():
    evidence = topology_to_hvdc_evidence(
        topology_with_candidate_only_connection()
    )

    assert evidence.connections == ()


def test_adapter_preserves_topology_unresolved_as_scanner_warnings():
    topology = replace(
        canonical_hvdc_topology(),
        unresolved=("source_evidence_missing:Main:103",),
    )

    evidence = topology_to_hvdc_evidence(topology)

    assert evidence.warnings == ("source_evidence_missing:Main:103",)


def test_hvdc_rules_preserve_stable_unresolved_codes():
    findings = diagnose_hvdc(
        canonical_hvdc_topology(),
        profile="lcc_bipolar_earth_return_v1",
    )

    assert {finding.code for finding in findings} >= {
        "HVDC_RETURN_PATH_UNRESOLVED"
    }


def test_auto_profile_reports_ambiguous_family_instead_of_guessing():
    findings = diagnose_hvdc(ProjectTopology("case", "4.6.2"), profile="auto")

    assert [finding.code for finding in findings] == [
        "HVDC_TOPOLOGY_AMBIGUOUS"
    ]
