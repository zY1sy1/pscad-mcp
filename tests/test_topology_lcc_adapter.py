from pscad_mcp.hvdc.builders.lcc.catalog import parse_catalog
from pscad_mcp.hvdc.builders.lcc.project_graph import read_project_graph
from pscad_mcp.topology.adapters.lcc import (
    lcc_port_contracts,
    topology_to_lcc_graph,
)
from pscad_mcp.topology.connectivity import build_connectivity
from pscad_mcp.topology.providers.pscx import PscxSnapshotProvider
from pscad_mcp.topology.reconcile import reconcile_snapshots
from tests.test_lcc_project_graph import CATALOG, FIXTURE
from tests.topology_fakes import topology_with_candidate_only_connection


def test_canonical_adapter_matches_public_lcc_graph_contract_exactly():
    catalog = parse_catalog(CATALOG)
    saved = PscxSnapshotProvider(
        definition_ports=lcc_port_contracts(catalog)
    ).read(FIXTURE, "Main")
    topology = build_connectivity(reconcile_snapshots(None, saved)).topology

    adapted = topology_to_lcc_graph(topology, catalog)
    current = read_project_graph(FIXTURE, catalog)

    assert adapted.to_dict() == current.to_dict()


def test_adapter_never_uses_candidate_edges_as_lcc_nets():
    topology = topology_with_candidate_only_connection()

    graph = topology_to_lcc_graph(topology, parse_catalog(CATALOG))

    assert all(net.endpoints == () for net in graph.nets)
    assert all("Main:1:P" not in net.endpoints for net in graph.nets)
