from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from ..geometry import Segment, classify_intersection, normalize_vertices
from ..models import (
    CandidateEdge,
    DiagnosticFinding,
    ProjectTopology,
    TopologyComponent,
    TopologyConductor,
    TopologyPort,
)


_KNOWN_NAMESPACES = {"electrical", "data"}
_NEARBY_REASON = "nearby compatible dangling endpoint"


def diagnose_generic(
    topology: ProjectTopology,
) -> tuple[DiagnosticFinding, ...]:
    findings = []
    for rule in GENERIC_RULES:
        findings.extend(sorted(rule(topology), key=lambda item: item.objects))
    return tuple(findings)


def infer_candidate_edges(
    topology: ProjectTopology,
) -> tuple[CandidateEdge, ...]:
    if topology.grid_step <= 0:
        return ()
    connected_ports = {
        key for net in topology.nets for key in net.port_keys
    }
    candidates = []
    for component, port in _active_ports(topology):
        if port.key in connected_ports or port.absolute is None:
            continue
        for conductor, point in _dangling_endpoints(topology):
            if component.canvas_key != conductor.canvas_key:
                continue
            if port.kind != conductor.namespace:
                continue
            if not _dimension_compatible(topology, conductor.key, port):
                continue
            distance = abs(port.absolute[0] - point[0]) + abs(
                port.absolute[1] - point[1]
            )
            if distance <= 0 or distance > topology.grid_step:
                continue
            candidates.append(
                CandidateEdge(
                    left=f"{conductor.key}@{_point_text(point)}",
                    right=port.key,
                    confidence=max(
                        0.5,
                        1.0 - distance / (2 * topology.grid_step),
                    ),
                    reasons=(_NEARBY_REASON,),
                    counter_evidence=(),
                )
            )
    return tuple(sorted(candidates, key=lambda item: (item.left, item.right)))


def _unconnected_ports(
    topology: ProjectTopology,
) -> tuple[DiagnosticFinding, ...]:
    connected = {key for net in topology.nets for key in net.port_keys}
    findings = []
    for _component, port in _active_ports(topology):
        if port.key in connected:
            continue
        required = port.required is True
        findings.append(
            _finding(
                code=(
                    "REQUIRED_PORT_UNCONNECTED"
                    if required
                    else "PORT_UNCONNECTED"
                ),
                severity="error" if required else "info",
                status="derived",
                objects=(port.key,),
                evidence=_record_evidence(port, port.key),
                message=(
                    f"Required active port '{port.key}' has no confirmed net."
                    if required
                    else f"Active port '{port.key}' has no confirmed net."
                ),
                suggested_action=(
                    "Connect the required port manually or correct its audited "
                    "definition contract."
                    if required
                    else "Review the port contract and connect it manually if "
                    "the design requires it."
                ),
            )
        )
    return tuple(findings)


def _dangling_wire_endpoints(
    topology: ProjectTopology,
) -> tuple[DiagnosticFinding, ...]:
    findings = []
    for conductor, point in _dangling_endpoints(topology):
        endpoint = f"{conductor.key}@{_point_text(point)}"
        findings.append(
            _finding(
                code="WIRE_DANGLING_ENDPOINT",
                severity="error",
                status="derived",
                objects=(endpoint,),
                evidence=_record_evidence(conductor, endpoint),
                message=f"Conductor endpoint '{endpoint}' is dangling.",
                suggested_action=(
                    "Inspect the endpoint and add or correct the intended "
                    "connection manually."
                ),
            )
        )
    return tuple(findings)


def _isolated_networks(
    topology: ProjectTopology,
) -> tuple[DiagnosticFinding, ...]:
    return tuple(
        _finding(
            code="ISOLATED_NETWORK",
            severity="warning",
            status="derived",
            objects=(net.key,),
            evidence=net.conductor_keys,
            message=f"Confirmed net '{net.key}' has no component port or label.",
            suggested_action=(
                "Review the isolated conductors and remove or connect them "
                "manually."
            ),
        )
        for net in topology.nets
        if not net.port_keys and not net.label_keys
    )


def _port_kind_mismatches(
    topology: ProjectTopology,
) -> tuple[DiagnosticFinding, ...]:
    findings = []
    for _component, port in _active_ports(topology):
        if port.absolute is None or port.kind not in _KNOWN_NAMESPACES:
            continue
        for conductor in topology.conductors:
            if conductor.canvas_key != _component.canvas_key:
                continue
            if conductor.namespace not in _KNOWN_NAMESPACES:
                continue
            if conductor.namespace == port.kind:
                continue
            if port.absolute not in conductor.vertices:
                continue
            findings.append(
                _finding(
                    code="PORT_KIND_MISMATCH",
                    severity="error",
                    status="conflict",
                    objects=(port.key, conductor.key),
                    evidence=_record_evidence(port, port.key)
                    + _record_evidence(conductor, conductor.key),
                    message=(
                        f"Port '{port.key}' and the touching conductor use "
                        "different namespaces."
                    ),
                    suggested_action=(
                        "Correct the port or conductor type before connecting "
                        "them."
                    ),
                )
            )
    return tuple(findings)


def _port_dimension_mismatches(
    topology: ProjectTopology,
) -> tuple[DiagnosticFinding, ...]:
    ports = {
        port.key: port
        for component in topology.components
        for port in component.ports
    }
    findings = []
    for net in topology.nets:
        dimensions = {
            ports[key].dimension
            for key in net.port_keys
            if key in ports and ports[key].dimension is not None
        }
        if len(dimensions) < 2:
            continue
        findings.append(
            _finding(
                code="PORT_DIMENSION_MISMATCH",
                severity="error",
                status="conflict",
                objects=(net.key, *net.port_keys),
                evidence=net.port_keys,
                message=(
                    f"Confirmed net '{net.key}' contains incompatible known "
                    "dimensions."
                ),
                suggested_action=(
                    "Correct the port dimensions or split the net manually."
                ),
            )
        )
    return tuple(findings)


def _ambiguous_crossings(
    topology: ProjectTopology,
) -> tuple[DiagnosticFinding, ...]:
    segments = _segments(topology.conductors)
    findings = []
    for index, (left_conductor, left_segment) in enumerate(segments):
        for right_conductor, right_segment in segments[index + 1 :]:
            if left_conductor.key == right_conductor.key:
                continue
            if left_conductor.canvas_key != right_conductor.canvas_key:
                continue
            if left_conductor.namespace != right_conductor.namespace:
                continue
            relation = classify_intersection(left_segment, right_segment)
            if relation.kind != "crossing":
                continue
            point = relation.points[0]
            point_text = _point_text(point)
            objects = tuple(
                sorted((left_conductor.key, right_conductor.key))
            ) + (point_text,)
            findings.append(
                _finding(
                    code="CROSSING_AMBIGUOUS",
                    severity="warning",
                    status="unresolved",
                    objects=objects,
                    evidence=objects,
                    message=(
                        f"Conductors cross at '{point_text}' without explicit "
                        "junction evidence."
                    ),
                    suggested_action=(
                        "Add an explicit junction or reroute one conductor to "
                        "make intent clear."
                    ),
                )
            )
    return tuple(sorted(findings, key=lambda item: item.objects))


def _label_conflicts(
    topology: ProjectTopology,
) -> tuple[DiagnosticFinding, ...]:
    groups = defaultdict(list)
    for label in topology.labels:
        if label.namespace in _KNOWN_NAMESPACES:
            groups[(label.scope.casefold(), label.name.casefold())].append(label)
    findings = []
    for labels in groups.values():
        if len({label.namespace for label in labels}) < 2:
            continue
        keys = tuple(sorted(label.key for label in labels))
        findings.append(
            _finding(
                code="LABEL_CONFLICT",
                severity="error",
                status="conflict",
                objects=keys,
                evidence=keys,
                message=(
                    f"Label '{keys[0]}' aliases incompatible namespaces in "
                    "one scope."
                ),
                suggested_action=(
                    "Rename or correct the conflicting labels manually."
                ),
            )
        )
    return tuple(sorted(findings, key=lambda item: item.objects))


def _source_conflicts(
    topology: ProjectTopology,
) -> tuple[DiagnosticFinding, ...]:
    findings = []
    for conflict in topology.conflicts:
        findings.append(
            _finding(
                code="SOURCE_CONFLICT",
                severity="warning",
                status="conflict",
                objects=(conflict.object_key, conflict.field),
                evidence=_record_evidence(
                    conflict,
                    f"{conflict.field}:{conflict.object_key}",
                ),
                message=(
                    "Live and saved evidence disagree for "
                    f"'{conflict.object_key}'."
                ),
                suggested_action=(
                    "Review unsaved canvas changes and the saved project before "
                    "relying on this field."
                ),
            )
        )
    return tuple(findings)


def _incomplete_topology(
    topology: ProjectTopology,
) -> tuple[DiagnosticFinding, ...]:
    if not topology.unresolved:
        return ()
    count = len(topology.unresolved)
    return (
        _finding(
            code="TOPOLOGY_INCOMPLETE",
            severity="warning",
            status="unresolved",
            objects=tuple(topology.unresolved),
            evidence=topology.unresolved,
            message=f"Topology evidence is incomplete for {count} source items.",
            suggested_action=(
                "Inspect the reported capability or source gaps before "
                "validating the project."
            ),
        ),
    )


GENERIC_RULES = (
    _unconnected_ports,
    _dangling_wire_endpoints,
    _isolated_networks,
    _port_kind_mismatches,
    _port_dimension_mismatches,
    _ambiguous_crossings,
    _label_conflicts,
    _source_conflicts,
    _incomplete_topology,
)


def _active_ports(
    topology: ProjectTopology,
) -> Iterable[tuple[TopologyComponent, TopologyPort]]:
    for component in sorted(topology.components, key=lambda item: item.key):
        if not component.active:
            continue
        for port in sorted(component.ports, key=lambda item: item.key):
            if port.active:
                yield component, port


def _segments(
    conductors: Iterable[TopologyConductor],
) -> list[tuple[TopologyConductor, Segment]]:
    result = []
    for conductor in sorted(conductors, key=lambda item: item.key):
        try:
            vertices = normalize_vertices(conductor.vertices)
        except ValueError:
            continue
        result.extend(
            (conductor, Segment(start, end))
            for start, end in zip(vertices, vertices[1:])
        )
    return result


def _dangling_endpoints(
    topology: ProjectTopology,
) -> tuple[tuple[TopologyConductor, tuple[int, int]], ...]:
    segments = _segments(topology.conductors)
    attached = _attached_points(topology)
    result = []
    for conductor in sorted(topology.conductors, key=lambda item: item.key):
        try:
            vertices = normalize_vertices(conductor.vertices)
        except ValueError:
            continue
        for point in (vertices[0], vertices[-1]):
            identity = (conductor.namespace, conductor.canvas_key, point)
            if identity in attached:
                continue
            degree = sum(
                1
                for other, segment in segments
                if other.canvas_key == conductor.canvas_key
                and other.namespace == conductor.namespace
                and _point_on_segment(point, segment)
            )
            if degree == 1:
                result.append((conductor, point))
    return tuple(result)


def _attached_points(topology: ProjectTopology) -> set[tuple]:
    points = {
        (port.kind, component.canvas_key, port.absolute)
        for component, port in _active_ports(topology)
        if port.absolute is not None
    }
    points.update(
        (label.namespace, label.canvas_key, label.location)
        for label in topology.labels
        if label.location is not None
    )
    for boundary in topology.boundary_links:
        points.add(
            (
                boundary.namespace,
                boundary.outer_canvas_key,
                boundary.outer_point,
            )
        )
        points.add(
            (
                boundary.namespace,
                boundary.inner_canvas_key,
                boundary.inner_point,
            )
        )
    return points


def _point_on_segment(point: tuple[int, int], segment: Segment) -> bool:
    return (
        min(segment.start[0], segment.end[0])
        <= point[0]
        <= max(segment.start[0], segment.end[0])
        and min(segment.start[1], segment.end[1])
        <= point[1]
        <= max(segment.start[1], segment.end[1])
        and (
            segment.start[0] == segment.end[0]
            or segment.start[1] == segment.end[1]
        )
    )


def _dimension_compatible(
    topology: ProjectTopology,
    conductor_key: str,
    port: TopologyPort,
) -> bool:
    ports = {
        item.key: item
        for component in topology.components
        for item in component.ports
    }
    dimensions = {
        ports[key].dimension
        for net in topology.nets
        if conductor_key in net.conductor_keys
        for key in net.port_keys
        if key in ports and ports[key].dimension is not None
    }
    return (
        port.dimension is None
        or not dimensions
        or dimensions == {port.dimension}
    )


def _record_evidence(record, fallback: str) -> tuple[str, ...]:
    references = tuple(
        evidence.reference for evidence in getattr(record, "evidence", ())
    )
    return references or (fallback,)


def _finding(
    *,
    code: str,
    severity: str,
    status: str,
    objects: tuple[str, ...],
    evidence: Iterable[str],
    message: str,
    suggested_action: str,
) -> DiagnosticFinding:
    return DiagnosticFinding(
        code=code,
        severity=severity,
        status=status,
        confidence=1.0,
        objects=tuple(objects),
        evidence=_bounded_references(evidence),
        message=message,
        suggested_action=suggested_action,
    )


def _bounded_references(values: Iterable[str]) -> tuple[str, ...]:
    references = sorted({str(value) for value in values})
    if len(references) <= 50:
        return tuple(references)
    sentinel = f"evidence_truncated:{len(references) - 49}"
    return (*references[:49], sentinel)


def _point_text(point: tuple[int, int]) -> str:
    return f"({point[0]},{point[1]})"
