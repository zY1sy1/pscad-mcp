from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from typing import TypeAlias

from .geometry import GeometryError, Segment, classify_intersection, normalize_vertices
from .hashing import canonical_sha256
from .models import Point, ProjectTopology, TopologyNet, TopologyPort


_KNOWN_NAMESPACES = {"electrical", "data"}
_Node: TypeAlias = tuple[str, str, Point]


@dataclass(frozen=True)
class ConnectivityResult:
    topology: ProjectTopology
    ambiguous_crossings: tuple[tuple[str, str, Point], ...] = ()
    malformed_conductors: tuple[str, ...] = ()


@dataclass(frozen=True)
class _SegmentRecord:
    conductor_key: str
    canvas_key: str
    namespace: str
    segment: Segment

    @property
    def horizontal(self) -> bool:
        return self.segment.start[1] == self.segment.end[1]

    @property
    def interval(self) -> tuple[int, int]:
        axis = 0 if self.horizontal else 1
        return tuple(sorted((self.segment.start[axis], self.segment.end[axis])))

    @property
    def fixed(self) -> int:
        return self.segment.start[1 if self.horizontal else 0]


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[_Node, _Node] = {}
        self.rank: dict[_Node, int] = {}

    def add(self, item: _Node) -> None:
        if item not in self.parent:
            self.parent[item] = item
            self.rank[item] = 0

    def contains(self, item: _Node) -> bool:
        return item in self.parent

    def find(self, item: _Node) -> _Node:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: _Node, right: _Node) -> None:
        self.add(left)
        self.add(right)
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        left_rank = self.rank[left_root]
        right_rank = self.rank[right_root]
        if left_rank < right_rank:
            left_root, right_root = right_root, left_root
            left_rank, right_rank = right_rank, left_rank
        self.parent[right_root] = left_root
        if left_rank == right_rank:
            self.rank[left_root] += 1


def build_connectivity(topology: ProjectTopology) -> ConnectivityResult:
    union_find = _UnionFind()
    unresolved = set(topology.unresolved)
    malformed: set[str] = set()
    segments: list[_SegmentRecord] = []
    conductor_vertices: dict[str, tuple[_Node, ...]] = {}
    explicit_vertices: set[_Node] = set()

    for conductor in sorted(topology.conductors, key=lambda item: item.key):
        if conductor.namespace not in _KNOWN_NAMESPACES:
            unresolved.add(f"unknown_conductor_namespace:{conductor.key}")
            continue
        try:
            vertices = normalize_vertices(conductor.vertices)
        except GeometryError:
            malformed.add(conductor.key)
            unresolved.add(f"malformed_conductor:{conductor.key}")
            continue
        nodes = tuple(
            (conductor.namespace, conductor.canvas_key, point) for point in vertices
        )
        conductor_vertices[conductor.key] = nodes
        explicit_vertices.update(nodes)
        for node in nodes:
            union_find.add(node)
        for left, right in zip(nodes, nodes[1:]):
            union_find.union(left, right)
            segments.append(
                _SegmentRecord(
                    conductor.key,
                    conductor.canvas_key,
                    conductor.namespace,
                    Segment(left[2], right[2]),
                )
            )

    ambiguous = _join_segment_relations(union_find, segments)

    port_by_key: dict[str, TopologyPort] = {}
    port_attachments: list[tuple[str, _Node]] = []
    for component in sorted(topology.components, key=lambda item: item.key):
        for port in sorted(component.ports, key=lambda item: item.key):
            port_by_key[port.key] = port
            if port.absolute is None:
                unresolved.add(f"missing_port_geometry:{port.key}")
                continue
            if port.kind not in _KNOWN_NAMESPACES:
                unresolved.add(f"unknown_port_namespace:{port.key}")
                continue
            node = (port.kind, component.canvas_key, port.absolute)
            if node in explicit_vertices:
                port_attachments.append((port.key, node))

    label_by_key = {label.key: label for label in topology.labels}
    label_attachments: list[tuple[str, _Node]] = []
    aliases: dict[tuple[str, str, str], list[_Node]] = {}
    for label in sorted(topology.labels, key=lambda item: item.key):
        if label.location is None:
            unresolved.add(f"missing_label_geometry:{label.key}")
            continue
        if label.namespace not in _KNOWN_NAMESPACES:
            unresolved.add(f"unknown_label_namespace:{label.key}")
            continue
        node = (label.namespace, label.canvas_key, label.location)
        if node not in explicit_vertices:
            continue
        label_attachments.append((label.key, node))
        alias = (label.namespace, label.scope.casefold(), label.name.casefold())
        aliases.setdefault(alias, []).append(node)
    for nodes in aliases.values():
        for node in nodes[1:]:
            union_find.union(nodes[0], node)

    for boundary in sorted(topology.boundary_links, key=lambda item: item.key):
        outer = (boundary.namespace, boundary.outer_canvas_key, boundary.outer_point)
        inner = (boundary.namespace, boundary.inner_canvas_key, boundary.inner_point)
        outer_port = port_by_key.get(boundary.outer_port_key)
        inner_port = port_by_key.get(boundary.inner_port_key)
        status = _boundary_status(
            boundary.namespace,
            boundary.dimension,
            outer,
            inner,
            outer_port,
            inner_port,
            union_find,
        )
        if status != "valid":
            code = (
                "hierarchy_boundary_unresolved"
                if status == "unresolved"
                else "invalid_boundary_link"
            )
            unresolved.add(f"{code}:{boundary.key}")
            continue
        if (boundary.outer_port_key, outer) not in port_attachments:
            port_attachments.append((boundary.outer_port_key, outer))
        port_attachments.append((boundary.inner_port_key, inner))
        union_find.union(outer, inner)

    nets = _materialize_nets(
        union_find,
        conductor_vertices,
        port_attachments,
        label_attachments,
        label_by_key,
    )
    return ConnectivityResult(
        topology=replace(
            topology,
            nets=nets,
            unresolved=tuple(sorted(unresolved)),
        ),
        ambiguous_crossings=tuple(sorted(ambiguous)),
        malformed_conductors=tuple(sorted(malformed)),
    )


def _join_segment_relations(
    union_find: _UnionFind,
    segments: list[_SegmentRecord],
) -> set[tuple[str, str, Point]]:
    ambiguous: set[tuple[str, str, Point]] = set()
    collinear: dict[tuple[str, str, bool, int], list[_SegmentRecord]] = {}
    by_plane: dict[tuple[str, str], list[_SegmentRecord]] = {}
    for record in segments:
        collinear.setdefault(
            (record.canvas_key, record.namespace, record.horizontal, record.fixed),
            [],
        ).append(record)
        by_plane.setdefault((record.canvas_key, record.namespace), []).append(record)

    for records in collinear.values():
        active: list[_SegmentRecord] = []
        for current in sorted(
            records,
            key=lambda item: (item.interval, item.conductor_key),
        ):
            current_start = current.interval[0]
            active = [item for item in active if item.interval[1] >= current_start]
            for other in active:
                if other.conductor_key != current.conductor_key:
                    _apply_relation(union_find, other, current, ambiguous)
            active.append(current)

    for records in by_plane.values():
        horizontal = [item for item in records if item.horizontal]
        vertical = sorted(
            (item for item in records if not item.horizontal),
            key=lambda item: (item.fixed, item.interval, item.conductor_key),
        )
        vertical_x = [item.fixed for item in vertical]
        for current in sorted(
            horizontal,
            key=lambda item: (item.fixed, item.interval, item.conductor_key),
        ):
            start = bisect_left(vertical_x, current.interval[0])
            end = bisect_right(vertical_x, current.interval[1])
            for other in vertical[start:end]:
                if (
                    other.conductor_key != current.conductor_key
                    and other.interval[0] <= current.fixed <= other.interval[1]
                ):
                    _apply_relation(union_find, current, other, ambiguous)
    return ambiguous


def _apply_relation(
    union_find: _UnionFind,
    left: _SegmentRecord,
    right: _SegmentRecord,
    ambiguous: set[tuple[str, str, Point]],
) -> None:
    relation = classify_intersection(left.segment, right.segment)
    if relation.kind == "none":
        return
    if relation.kind == "crossing":
        conductor_keys = tuple(sorted((left.conductor_key, right.conductor_key)))
        ambiguous.add((conductor_keys[0], conductor_keys[1], relation.points[0]))
        return
    for point in relation.points:
        left_point = (left.namespace, left.canvas_key, point)
        right_point = (right.namespace, right.canvas_key, point)
        for endpoint in (left.segment.start, left.segment.end):
            union_find.union(
                left_point,
                (left.namespace, left.canvas_key, endpoint),
            )
        for endpoint in (right.segment.start, right.segment.end):
            union_find.union(
                right_point,
                (right.namespace, right.canvas_key, endpoint),
            )
        union_find.union(left_point, right_point)


def _boundary_status(
    namespace: str,
    dimension: int | None,
    outer: _Node,
    inner: _Node,
    outer_port: TopologyPort | None,
    inner_port: TopologyPort | None,
    union_find: _UnionFind,
) -> str:
    if namespace not in _KNOWN_NAMESPACES:
        return "invalid"
    if outer_port is None:
        return "invalid"
    for port, expected_point in (
        (outer_port, outer[2]),
        (inner_port, inner[2]),
    ):
        if port is None:
            continue
        if port.absolute != expected_point:
            return "invalid"
        if port.kind != namespace:
            return "invalid"
        if port.dimension is not None and dimension is not None:
            if port.dimension != dimension:
                return "invalid"
    if not union_find.contains(outer) or not union_find.contains(inner):
        return "unresolved"
    return "valid"


def _materialize_nets(
    union_find: _UnionFind,
    conductor_vertices: dict[str, tuple[_Node, ...]],
    port_attachments: list[tuple[str, _Node]],
    label_attachments: list[tuple[str, _Node]],
    label_by_key,
) -> tuple[TopologyNet, ...]:
    groups: dict[_Node, dict[str, set]] = {}

    def group_for(node: _Node):
        root = union_find.find(node)
        return root, groups.setdefault(
            root,
            {
                "namespaces": set(),
                "ports": set(),
                "conductors": set(),
                "labels": set(),
                "junctions": set(),
            },
        )

    for conductor_key, nodes in conductor_vertices.items():
        _root, group = group_for(nodes[0])
        group["conductors"].add(conductor_key)
    for port_key, node in port_attachments:
        _root, group = group_for(node)
        group["ports"].add(port_key)
    for label_key, node in label_attachments:
        _root, group = group_for(node)
        group["labels"].add(label_key)
    for node in union_find.parent:
        root, group = group_for(node)
        group["namespaces"].add(node[0])
        group["junctions"].add(node[2])

    # Union operations after the first conductor insertion can change roots.
    confirmed_roots = {
        union_find.find(nodes[0]) for nodes in conductor_vertices.values()
    }
    consolidated: dict[_Node, dict[str, set]] = {}
    for root, group in groups.items():
        current_root = union_find.find(root)
        target = consolidated.setdefault(
            current_root,
            {
                "namespaces": set(),
                "ports": set(),
                "conductors": set(),
                "labels": set(),
                "junctions": set(),
            },
        )
        for field, values in group.items():
            target[field].update(values)

    nets = []
    for root in sorted(confirmed_roots):
        group = consolidated[root]
        namespace = sorted(group["namespaces"])[0]
        ports = tuple(sorted(group["ports"]))
        conductors = tuple(sorted(group["conductors"]))
        labels = tuple(sorted(group["labels"]))
        junctions = tuple(sorted(group["junctions"]))
        label_records = tuple(
            {
                "key": key,
                "scope": label_by_key[key].scope.casefold(),
            }
            for key in labels
        )
        key = canonical_sha256(
            {
                "namespace": namespace,
                "ports": ports,
                "conductors": conductors,
                "labels": label_records,
                "junctions": junctions,
            }
        )
        nets.append(
            TopologyNet(
                key=key,
                namespace=namespace,
                port_keys=ports,
                conductor_keys=conductors,
                label_keys=labels,
                junctions=junctions,
            )
        )
    return tuple(sorted(nets, key=lambda item: item.key))
