from dataclasses import replace
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.models import LccBlueprint
from pscad_mcp.hvdc.builders.lcc.project_graph import (
    GraphComponent,
    GraphLabel,
    GraphNet,
    GraphPort,
    ProjectGraph,
)
from pscad_mcp.hvdc.builders.lcc.schema import parse_blueprint
from pscad_mcp.hvdc.builders.lcc.validator import (
    validate_companion_library,
    validate_project_graph,
)


BLUEPRINT_DATA = {
    "schema_version": 1,
    "name": "cigre_lcc_monopole_v1",
    "topology": "lcc",
    "poles": 1,
    "terminals": 2,
    "settings": {"simulation_duration_s": 1.0},
    "components": [
        {
            "logical_id": "source",
            "definition": "master:source3",
            "location": {"x": 0, "y": 0},
            "parameters": {"Amplitude": "230.0"},
            "ports": [{"name": "AC", "kind": "electrical", "dimension": 3}],
        },
        {
            "logical_id": "bridge",
            "definition": "cigre_lcc_v1:LCC12PulseBridge",
            "location": {"x": 100, "y": 0},
            "orientation": 0,
            "parameters": {"ValveDrop": "1.2"},
            "ports": [
                {"name": "ACY_A", "kind": "electrical", "dimension": 1},
                {"name": "DC_POS", "kind": "electrical", "dimension": 1},
                {"name": "GATES", "kind": "data", "dimension": 12},
            ],
        },
        {
            "logical_id": "load",
            "definition": "master:line",
            "location": {"x": 200, "y": 0},
            "ports": [{"name": "P", "kind": "electrical", "dimension": 1}],
        },
        {
            "logical_id": "control",
            "definition": "cigre_lcc_v1:RectifierControl",
            "location": {"x": 100, "y": 60},
            "ports": [
                {"name": "GATES", "kind": "data", "dimension": 12},
                {"name": "ENABLE", "kind": "data", "dimension": 1},
            ],
        },
        {
            "logical_id": "interface",
            "definition": "cigre_lcc_v1:SignalInterface",
            "location": {"x": 40, "y": 60},
            "ports": [{"name": "ENABLE", "kind": "data", "dimension": 1}],
        },
    ],
    "nets": [
        {
            "logical_id": "ac_a",
            "kind": "electrical",
            "endpoints": [
                {"component": "source", "port": "AC"},
                {"component": "bridge", "port": "ACY_A"},
            ],
            "route": {"vertices": [[10, 0], [90, 0]]},
        },
        {
            "logical_id": "dc_pos",
            "kind": "electrical",
            "endpoints": [
                {"component": "bridge", "port": "DC_POS"},
                {"component": "load", "port": "P"},
            ],
            "route": {"vertices": [[110, 0], [190, 0]]},
        },
        {
            "logical_id": "gate_bus",
            "kind": "data",
            "label": "GATE_CMD",
            "endpoints": [
                {"component": "bridge", "port": "GATES"},
                {"component": "control", "port": "GATES"},
            ],
            "route": {"vertices": [[100, 10], [100, 50]]},
        },
        {
            "logical_id": "enable",
            "kind": "data",
            "label": "ENABLE",
            "endpoints": [
                {"component": "interface", "port": "ENABLE"},
                {"component": "control", "port": "ENABLE"},
            ],
            "route": {"vertices": [[50, 60], [90, 60]]},
        },
    ],
    "outputs": [],
}


def _blueprint() -> LccBlueprint:
    return parse_blueprint(BLUEPRINT_DATA)


def _component(
    logical_id: str,
    definition: str,
    location: tuple[int, int],
    ports: tuple[GraphPort, ...],
    *,
    orientation: int = 0,
    parameters: dict[str, str] | None = None,
) -> GraphComponent:
    return GraphComponent(
        logical_id=logical_id,
        definition=definition,
        canvas="Main",
        location=location,
        orientation=orientation,
        parameters=parameters or {},
        ports=ports,
    )


def _port(name: str, kind: str, dimension: int, absolute: tuple[int, int]) -> GraphPort:
    return GraphPort(name=name, kind=kind, dimension=dimension, offset=(0, 0), absolute=absolute)


def _net(
    kind: str,
    points: tuple[tuple[int, int], ...],
    endpoints: tuple[str, ...],
    labels: tuple[str, ...] = (),
) -> GraphNet:
    return GraphNet(kind=kind, points=tuple(sorted(points)), labels=labels, endpoints=tuple(sorted(endpoints)))


def _graph() -> ProjectGraph:
    components = (
        _component(
            "source",
            "master:source3",
            (0, 0),
            (_port("AC", "electrical", 3, (10, 0)),),
            parameters={"Amplitude": "230.0"},
        ),
        _component(
            "bridge",
            "cigre_lcc_v1:LCC12PulseBridge",
            (100, 0),
            (
                _port("ACY_A", "electrical", 1, (90, 0)),
                _port("DC_POS", "electrical", 1, (110, 0)),
                _port("GATES", "data", 12, (100, 10)),
            ),
            parameters={"ValveDrop": "1.2"},
        ),
        _component("load", "master:line", (200, 0), (_port("P", "electrical", 1, (190, 0)),)),
        _component(
            "control",
            "cigre_lcc_v1:RectifierControl",
            (100, 60),
            (
                _port("GATES", "data", 12, (100, 50)),
                _port("ENABLE", "data", 1, (90, 60)),
            ),
        ),
        _component(
            "interface",
            "cigre_lcc_v1:SignalInterface",
            (40, 60),
            (_port("ENABLE", "data", 1, (50, 60)),),
        ),
    )
    labels = (
        GraphLabel("GATE_CMD", "data", (100, 30)),
        GraphLabel("ENABLE", "data", (70, 60)),
    )
    nets = (
        _net("electrical", ((10, 0), (90, 0)), ("source:AC", "bridge:ACY_A")),
        _net("electrical", ((110, 0), (190, 0)), ("bridge:DC_POS", "load:P")),
        _net("data", ((100, 10), (100, 30), (100, 50)), ("bridge:GATES", "control:GATES"), ("GATE_CMD",)),
        _net("data", ((50, 60), (70, 60), (90, 60)), ("interface:ENABLE", "control:ENABLE"), ("ENABLE",)),
    )
    return ProjectGraph("CIGRE_LCC", "4.6.2", components, (), labels, nets)


def _mutate_graph(**overrides) -> ProjectGraph:
    values = {
        "project_name": "CIGRE_LCC",
        "pscad_version": "4.6.2",
        "components": _graph().components,
        "wires": (),
        "labels": _graph().labels,
        "nets": _graph().nets,
    }
    values.update(overrides)
    return ProjectGraph(**values)


def _codes(result: dict) -> list[str]:
    return [error["reason"] for error in result["errors"]]


def test_validate_project_graph_accepts_exact_blueprint_owned_structure():
    result = validate_project_graph(_graph(), _blueprint())

    assert result == {
        "valid": True,
        "blueprint": "cigre_lcc_monopole_v1",
        "components": {"expected": 5, "observed": 5},
        "nets": {"expected": 4, "observed": 4},
        "errors": [],
        "warnings": [],
    }


def test_validate_project_graph_rejects_non_exact_route_vertices():
    graph = _graph()
    observed_nets = tuple(
        replace(net, points=((90, 0), (50, 0), (10, 0)))
        if net.endpoints == ("bridge:ACY_A", "source:AC")
        else net
        for net in graph.nets
    )

    result = validate_project_graph(replace(graph, nets=observed_nets), _blueprint())

    assert result["valid"] is False
    route_errors = [error for error in result["errors"] if error["reason"] == "net route mismatch"]
    assert route_errors == [
        {
            "code": "LCC_STRUCTURE_INVALID",
            "logical_id": "ac_a",
            "reason": "net route mismatch",
            "expected": [[10, 0], [90, 0]],
            "observed": [[90, 0], [50, 0], [10, 0]],
        }
    ]


def test_validate_project_graph_rejects_extra_observed_component_parameter():
    graph = _graph()
    observed_components = tuple(
        replace(component, parameters={**component.parameters, "ExtraParameter": "unexpected"})
        if component.logical_id == "bridge"
        else component
        for component in graph.components
    )

    result = validate_project_graph(replace(graph, components=observed_components), _blueprint())

    assert result["valid"] is False
    assert result["errors"] == [
        {
            "code": "LCC_STRUCTURE_INVALID",
            "logical_id": "bridge",
            "reason": "component parameter set mismatch",
            "expected": ["ValveDrop"],
            "observed": ["ExtraParameter", "ValveDrop"],
        }
    ]


def test_validate_project_graph_rejects_extra_observed_component_port():
    graph = _graph()
    observed_components = tuple(
        replace(
            component,
            ports=component.ports + (_port("EXTRA", "electrical", 1, (120, 0)),),
        )
        if component.logical_id == "bridge"
        else component
        for component in graph.components
    )

    result = validate_project_graph(replace(graph, components=observed_components), _blueprint())

    assert result["valid"] is False
    assert result["errors"] == [
        {
            "code": "LCC_STRUCTURE_INVALID",
            "logical_id": "bridge",
            "reason": "component port set mismatch",
            "expected": ["ACY_A", "DC_POS", "GATES"],
            "observed": ["ACY_A", "DC_POS", "EXTRA", "GATES"],
        }
    ]


@pytest.mark.parametrize(
    ("graph", "reason"),
    [
        (
            lambda graph: _mutate_graph(components=tuple(component for component in graph.components if component.logical_id != "bridge")),
            "missing component",
        ),
        (
            lambda graph: _mutate_graph(
                components=tuple(
                    replace(component, definition="cigre_lcc_v1:OtherBridge") if component.logical_id == "bridge" else component
                    for component in graph.components
                )
            ),
            "component definition mismatch",
        ),
        (
            lambda graph: _mutate_graph(
                components=tuple(replace(component, orientation=4) if component.logical_id == "bridge" else component for component in graph.components)
            ),
            "component orientation mismatch",
        ),
        (
            lambda graph: _mutate_graph(
                components=tuple(
                    replace(component, parameters={"ValveDrop": "1.3"}) if component.logical_id == "bridge" else component
                    for component in graph.components
                )
            ),
            "component parameter mismatch",
        ),
        (
            lambda graph: _mutate_graph(nets=tuple(net for net in graph.nets if "bridge:ACY_A" not in net.endpoints)),
            "missing net",
        ),
        (
            lambda graph: _mutate_graph(
                nets=graph.nets
                + (_net("electrical", ((10, 0), (190, 0)), ("source:AC", "load:P")),)
            ),
            "unexpected net",
        ),
        (
            lambda graph: _mutate_graph(labels=graph.labels + (GraphLabel("GATE_CMD", "data", (100, 80)),)),
            "duplicate data label",
        ),
        (
            lambda graph: _mutate_graph(
                nets=tuple(
                    _net(net.kind, net.points, ("control:GATES",), net.labels) if net.labels == ("GATE_CMD",) else net
                    for net in graph.nets
                )
            ),
            "unconnected required port",
        ),
        (
            lambda graph: _mutate_graph(
                nets=tuple(replace(net, kind="electrical") if net.labels == ("GATE_CMD",) else net for net in graph.nets)
            ),
            "net namespace mismatch",
        ),
    ],
)
def test_validate_project_graph_detects_single_structural_mutations(graph, reason):
    result = validate_project_graph(graph(_graph()), BLUEPRINT_DATA)

    assert result["valid"] is False
    assert {error["code"] for error in result["errors"]} == {"LCC_STRUCTURE_INVALID"}
    assert reason in _codes(result)
    assert result["errors"] == sorted(result["errors"], key=lambda item: (item["code"], item["logical_id"], item["reason"]))


def _library_xml(*, missing_valve: bool = False, gate_dimension: int = 12, extra_definition: bool = False) -> str:
    valves = "\n".join(f'<valve id="V{index:02d}" />' for index in range(1, 12 if missing_valve else 13))
    extra = '<definition name="cigre_lcc_v1:Extra" />' if extra_definition else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<pslx>
  <definition name="cigre_lcc_v1:LCC12PulseBridge">
    <external_ports>
      <port name="ACY_A" kind="electrical" dimension="1" group="acy" />
      <port name="ACY_B" kind="electrical" dimension="1" group="acy" />
      <port name="ACY_C" kind="electrical" dimension="1" group="acy" />
      <port name="ACD_A" kind="electrical" dimension="1" group="acd" />
      <port name="ACD_B" kind="electrical" dimension="1" group="acd" />
      <port name="ACD_C" kind="electrical" dimension="1" group="acd" />
      <port name="DC_POS" kind="electrical" dimension="1" />
      <port name="DC_NEG" kind="electrical" dimension="1" />
      <port name="GATES" kind="data" dimension="{gate_dimension}" />
    </external_ports>
    <six_pulse_group name="upper" />
    <six_pulse_group name="lower" />
    <valves>{valves}</valves>
    <dc_series_path common="true" />
    <gate_interface port="GATES" dimension="{gate_dimension}" />
  </definition>
  <definition name="cigre_lcc_v1:RectifierControl">
    <external_ports>
      <port name="VDC" /><port name="IDC" /><port name="IORDER" />
      <port name="ENABLE" /><port name="GATES" dimension="12" /><port name="ALPHA" />
    </external_ports>
  </definition>
  <definition name="cigre_lcc_v1:InverterControl">
    <external_ports>
      <port name="VDC" /><port name="IDC" /><port name="GAMMA_ORDER" />
      <port name="ENABLE" /><port name="GATES" dimension="12" /><port name="GAMMA" />
    </external_ports>
  </definition>
  <definition name="cigre_lcc_v1:SignalInterface" />
  <definition name="cigre_lcc_v1:Initialization" />
  {extra}
</pslx>
"""


def test_validate_companion_library_accepts_required_custom_definitions(tmp_path):
    library = tmp_path / "cigre_lcc_v1.pslx"
    library.write_text(_library_xml(), encoding="utf-8")

    result = validate_companion_library(library)

    assert result == {"valid": True, "errors": [], "warnings": []}


def test_validate_companion_library_rejects_extra_custom_definition(tmp_path):
    library = tmp_path / "extra_cigre_lcc_v1.pslx"
    library.write_text(_library_xml(extra_definition=True), encoding="utf-8")

    result = validate_companion_library(library)

    assert result["valid"] is False
    assert {
        error["reason"] for error in result["errors"]
    } == {"unexpected companion definition"}
    assert result["errors"][0]["logical_id"] == "cigre_lcc_v1:Extra"


def test_validate_companion_library_reports_bridge_internal_contract_failures(tmp_path):
    library = tmp_path / "bad_cigre_lcc_v1.pslx"
    library.write_text(_library_xml(missing_valve=True, gate_dimension=6), encoding="utf-8")

    with pytest.raises(BackendError) as raised:
        validate_companion_library(library, raise_on_error=True)

    assert raised.value.code == "LCC_STRUCTURE_INVALID"
    assert raised.value.operation == "validate_lcc_companion_library"
    assert {"bridge gate interface dimension mismatch", "bridge valve count mismatch"} <= {
        error["reason"] for error in raised.value.details["errors"]
    }
