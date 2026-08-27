"""Independent structural and signal validation for a saved MMC graph."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from ....core.backend.base import BackendError
from ..common.routing import validate_orthogonal_route
from .models import MmcBlueprint
from .project_graph import GraphComponent, GraphNet, MmcProjectGraph


def _finding(code: str, message: str, **evidence: Any) -> dict[str, Any]:
    bounded = {key: value for key, value in evidence.items() if key in {"logical_id", "component", "port", "net", "expected", "observed", "path", "measurement", "source"}}
    return {"code": code, "message": message, "evidence": bounded}


def _endpoint(value: str) -> tuple[str, str] | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    component, port = value.split(":", 1)
    return component, port


def _port_map(component: GraphComponent) -> dict[str, Any]:
    return {port.name: port for port in component.ports}


def _add(findings: list[dict[str, Any]], code: str, message: str, **evidence: Any) -> None:
    if len(findings) < 64:
        findings.append(_finding(code, message, **evidence))


def validate_project_graph(graph: MmcProjectGraph, blueprint: MmcBlueprint) -> dict[str, Any]:
    """Return bounded observed findings for a saved graph; never trust planner state."""

    findings: list[dict[str, Any]] = []
    component_map = {component.logical_id: component for component in graph.components}
    endpoint_nets: defaultdict[tuple[str, str], list[GraphNet]] = defaultdict(list)
    for net in graph.nets:
        for endpoint in net.endpoints:
            parsed = _endpoint(endpoint)
            if parsed is not None:
                endpoint_nets[parsed].append(net)

    expected_arms = {arm.logical_id: arm for station in blueprint.stations for arm in station.arms}
    actual_arms = {component.logical_id: component for component in graph.components if component.definition.endswith(":MMCAverageArm")}
    extra_arms = sorted(set(actual_arms) - set(expected_arms))
    if extra_arms:
        _add(findings, "MMC_STRUCTURE_INVALID", "saved graph contains unexpected average arms.", observed=extra_arms)
    for logical_id, arm in expected_arms.items():
        component = actual_arms.get(logical_id)
        if component is None:
            _add(findings, "MMC_STRUCTURE_INVALID", "required arm is missing from saved graph.", logical_id=logical_id)
            continue
        expected_ports = set(arm.ports)
        observed_ports = set(_port_map(component))
        if observed_ports != expected_ports:
            _add(findings, "MMC_PORT_MISMATCH", "arm ports do not match the blueprint contract.", component=logical_id, expected=sorted(expected_ports), observed=sorted(observed_ports), source=component.source)
        for port_name, port in _port_map(component).items():
            expected_kind = "electrical" if port_name in {"AC", "DC_POS", "DC_NEG"} else "signal"
            if port.dimension != 1 or port.kind != expected_kind:
                _add(findings, "MMC_PORT_MISMATCH", "arm port kind or dimension is incorrect.", component=logical_id, port=port_name, expected={"kind": expected_kind, "dimension": 1}, observed={"kind": port.kind, "dimension": port.dimension}, source=port.source)
            if not endpoint_nets.get((logical_id, port_name)):
                _add(findings, "MMC_STRUCTURE_INVALID", "required arm port is unconnected.", component=logical_id, port=port_name, source=component.source)

    expected_midpoints = {f"{station.logical_id}.{phase}.midpoint" for station in blueprint.stations for phase in ("A", "B", "C")}
    observed_midpoints = {logical_id for logical_id in component_map if logical_id.endswith(".midpoint")}
    for logical_id in sorted(expected_midpoints - observed_midpoints):
        _add(findings, "MMC_STRUCTURE_INVALID", "phase midpoint is missing.", logical_id=logical_id)
    for station in blueprint.stations:
        control_id = f"{station.logical_id}.control"
        if control_id not in component_map:
            _add(findings, "MMC_CONTROL_INFEASIBLE", "station controller component is missing.", component=control_id)
        elif not any(net.kind == "data" and any(endpoint.startswith(f"{control_id}:") for endpoint in net.endpoints) for net in graph.nets):
            _add(findings, "MMC_CONTROL_INFEASIBLE", "station controller has no saved data signal binding.", component=control_id, source=component_map[control_id].source)

    if not any("positive_bus" in logical_id for logical_id in component_map):
        _add(findings, "MMC_STRUCTURE_INVALID", "positive DC terminal is missing.")
    if not any("negative_bus" in logical_id for logical_id in component_map):
        _add(findings, "MMC_STRUCTURE_INVALID", "negative DC terminal is missing.")
    net_ids = {net.logical_id for net in graph.nets}
    for required in ("dc_positive_conductor", "dc_negative_conductor"):
        if required not in net_ids:
            _add(findings, "MMC_STRUCTURE_INVALID", "required DC conductor path is missing.", net=required)

    for net in graph.nets:
        lowered = " ".join((net.logical_id, *net.endpoints)).casefold()
        if "positive" in lowered and "negative" in lowered:
            _add(findings, "MMC_STRUCTURE_INVALID", "positive and negative poles are crossed.", net=net.logical_id, source=net.source)
        if net.kind == "electrical" and "ground" in lowered:
            _add(findings, "MMC_STRUCTURE_INVALID", "ground is used as a normal return conductor.", net=net.logical_id, source=net.source)
        has_ac = any(token in lowered for token in (".ac", ":ac", "transformer"))
        has_dc = any(token in lowered for token in ("dc_", "dc:", "positive_bus", "negative_bus", "_line"))
        if net.kind == "electrical" and has_ac and has_dc:
            _add(findings, "MMC_STRUCTURE_INVALID", "AC-to-DC short path is present.", net=net.logical_id, source=net.source)
        if net.vertices:
            try:
                validate_orthogonal_route(net.vertices)
            except BackendError:
                _add(findings, "MMC_LAYOUT_INVALID", "saved net route is not orthogonal.", net=net.logical_id, source=net.source)
        for endpoint in net.endpoints:
            parsed = _endpoint(endpoint)
            if parsed is None:
                _add(findings, "MMC_STRUCTURE_INVALID", "saved net endpoint is malformed.", net=net.logical_id, observed=endpoint)
                continue
            component_id, port_name = parsed
            component = component_map.get(component_id)
            if component is None:
                _add(findings, "MMC_STRUCTURE_INVALID", "saved net endpoint references a missing component.", net=net.logical_id, component=component_id, port=port_name)
                continue
            port = _port_map(component).get(port_name)
            if port is None:
                _add(findings, "MMC_PORT_MISMATCH", "saved net endpoint references a missing port.", net=net.logical_id, component=component_id, port=port_name, source=component.source)
                continue
            if net.kind == "electrical" and port.kind != "electrical":
                _add(findings, "MMC_PORT_MISMATCH", "electrical net contains a non-electrical port.", net=net.logical_id, component=component_id, port=port_name, observed=port.kind, source=port.source)
            if net.kind == "data" and port.kind == "electrical":
                _add(findings, "MMC_PORT_MISMATCH", "data net contains an electrical port.", net=net.logical_id, component=component_id, port=port_name, observed=port.kind, source=port.source)

    observed_output_ids = {output.logical_id for output in graph.outputs}
    observed_paths: dict[str, list[str]] = defaultdict(list)
    for output in graph.outputs:
        observed_paths[output.path].append(output.logical_id)
    for path, logical_ids in observed_paths.items():
        if len(logical_ids) > 1:
            _add(findings, "MMC_OUTPUT_INCOMPLETE", "duplicate output selector path is present.", path=path, observed=sorted(logical_ids))
    expected_output_ids = {output.logical_id for output in blueprint.outputs}
    if observed_output_ids != expected_output_ids:
        _add(findings, "MMC_OUTPUT_INCOMPLETE", "saved output selectors do not match the fixed profile.", expected=sorted(expected_output_ids), observed=sorted(observed_output_ids))
    for output in graph.outputs:
        if output.measurement:
            parsed = _endpoint(output.measurement)
            if parsed is None or parsed not in endpoint_nets:
                _add(findings, "MMC_OUTPUT_INCOMPLETE", "output measurement is not backed by a saved endpoint.", logical_id=output.logical_id, measurement=output.measurement, source=output.source)

    report = {
        "valid": not findings,
        "code": None if not findings else findings[0]["code"],
        "findings": findings,
        "observed": {
            "project_name": graph.project_name,
            "component_count": len(graph.components),
            "net_count": len(graph.nets),
            "output_count": len(graph.outputs),
            "arm_count": len(actual_arms),
            "expected_arm_count": len(expected_arms),
            "phase_midpoint_count": len(observed_midpoints),
            "positive_dc_terminal_count": sum("positive_bus" in logical_id for logical_id in component_map),
            "negative_dc_terminal_count": sum("negative_bus" in logical_id for logical_id in component_map),
            "required_output_count": len(expected_output_ids),
        },
    }
    return report


def assert_valid_project_graph(graph: MmcProjectGraph, blueprint: MmcBlueprint) -> dict[str, Any]:
    report = validate_project_graph(graph, blueprint)
    if not report["valid"]:
        first = report["findings"][0]
        raise BackendError(first["code"], first["message"], "hvdc", "validate_mmc_project_graph", first["evidence"])
    return report


validate_mmc_graph = validate_project_graph


__all__ = ["assert_valid_project_graph", "validate_mmc_graph", "validate_project_graph"]
