from pathlib import Path

from pscad_mcp.hvdc.scanner import scan_project


FIXTURE = Path(__file__).parent / "fixtures" / "mmc_synthetic" / "two_terminal_wire_graph.pscx"


def test_scanner_resolves_pscad_vertex_wire_to_component_ports() -> None:
    evidence = scan_project(FIXTURE)
    assert len(evidence.connections) == 1
    connection = evidence.connections[0]
    assert (connection.source_component_id, connection.source_port) == ("station-p", "dc")
    assert (connection.target_component_id, connection.target_port) == ("station-vdc", "dc")
    assert connection.evidence == ("WireOrthogonal", "vertex_coordinates")
