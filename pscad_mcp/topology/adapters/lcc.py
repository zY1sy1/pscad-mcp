"""Compatibility adaptation from canonical topology to the LCC graph API."""

from __future__ import annotations

from types import MappingProxyType

from ...core.backend.base import BackendError
from ...hvdc.builders.lcc.catalog import LccCatalog
from ...hvdc.builders.lcc.project_graph import (
    GraphComponent,
    GraphLabel,
    GraphNet,
    GraphPort,
    GraphWire,
    ProjectGraph,
)
from ...hvdc.builders.lcc.routing import validate_orthogonal_route
from ..models import DefinitionPortContract, ProjectTopology


def lcc_port_contracts(
    catalog: LccCatalog | None,
) -> dict[str, tuple[DefinitionPortContract, ...]]:
    """Expose audited LCC catalog ports to the neutral PSCX provider."""
    if catalog is None:
        return {}
    return {
        name: tuple(
            DefinitionPortContract(
                name=port.name,
                kind=port.kind,
                dimension=port.dimension,
                offset=port.offset,
            )
            for port in definition.ports
        )
        for name, definition in catalog.definitions.items()
    }


def topology_to_lcc_graph(
    topology: ProjectTopology,
    catalog: LccCatalog | None = None,
) -> ProjectGraph:
    """Map confirmed canonical records into the public frozen LCC graph."""
    component_by_key = {
        item.key: _component(item) for item in topology.components
    }
    components = tuple(
        sorted(
            component_by_key.values(),
            key=lambda item: (
                item.canvas,
                item.definition,
                item.location,
                item.logical_id,
            ),
        )
    )
    port_by_key = {
        port.key: (component_by_key[component.key], port)
        for component in topology.components
        for port in component.ports
    }
    labels_by_key = {item.key: item for item in topology.labels}
    consumed_labels: set[str] = set()
    nets: list[GraphNet] = []
    for net in topology.nets:
        label_keys = tuple(
            key for key in net.label_keys if key in labels_by_key
        )
        consumed_labels.update(label_keys)
        endpoints = tuple(
            sorted(
                f"{component.logical_id}:{port.name}"
                for key in net.port_keys
                if key in port_by_key
                for component, port in (port_by_key[key],)
            )
        )
        nets.append(
            GraphNet(
                kind=net.namespace,
                points=tuple(sorted(net.junctions)),
                labels=tuple(
                    sorted({labels_by_key[key].name for key in label_keys})
                ),
                endpoints=endpoints,
            )
        )

    label_aliases: dict[tuple[str, str, str], list] = {}
    for label in topology.labels:
        if label.key in consumed_labels or label.location is None:
            continue
        alias = (
            label.namespace,
            label.scope.casefold(),
            label.name.casefold(),
        )
        label_aliases.setdefault(alias, []).append(label)
    for records in label_aliases.values():
        nets.append(
            GraphNet(
                kind=records[0].namespace,
                points=tuple(
                    sorted({item.location for item in records if item.location})
                ),
                labels=tuple(sorted({item.name for item in records})),
            )
        )

    wires = tuple(
        sorted(
            (
                GraphWire(
                    item.namespace,
                    _validated_vertices(item.key, item.vertices),
                )
                for item in topology.conductors
            ),
            key=lambda item: (item.kind, item.vertices),
        )
    )
    labels = tuple(
        sorted(
            (
                GraphLabel(
                    item.name,
                    item.namespace,
                    item.location,
                )
                for item in topology.labels
            ),
            key=lambda item: (
                item.kind,
                item.text,
                item.location or (0, 0),
            ),
        )
    )
    return ProjectGraph(
        project_name=topology.project_name,
        pscad_version=topology.pscad_version,
        components=components,
        wires=wires,
        labels=labels,
        nets=tuple(
            sorted(
                nets,
                key=lambda item: (
                    item.kind,
                    item.points,
                    item.labels,
                    item.endpoints,
                ),
            )
        ),
    )


def _component(item) -> GraphComponent:
    if item.location is None:
        raise _invalid("A component location is unresolved.", item.key)
    orientation = item.orientation if item.orientation is not None else 0
    ports = []
    for port in item.ports:
        if port.absolute is None:
            raise _invalid("A component port geometry is unresolved.", port.key)
        relative = port.relative
        if relative is None and orientation == 0:
            relative = (
                port.absolute[0] - item.location[0],
                port.absolute[1] - item.location[1],
            )
        if relative is None:
            raise _invalid("A component port offset is unresolved.", port.key)
        ports.append(
            GraphPort(
                name=port.name,
                kind=port.kind,
                dimension=port.dimension if port.dimension is not None else 1,
                offset=relative,
                absolute=port.absolute,
            )
        )
    return GraphComponent(
        logical_id=_logical_id(item),
        definition=item.definition,
        canvas=item.canvas_key,
        location=item.location,
        orientation=orientation,
        parameters=MappingProxyType(dict(sorted(item.parameters))),
        ports=tuple(
            sorted(
                ports,
                key=lambda port: (
                    port.name,
                    port.kind,
                    port.dimension,
                    port.offset,
                ),
            )
        ),
        component_id=item.object_id,
    )


def _logical_id(item) -> str:
    parameters = dict(item.parameters)
    return str(
        parameters.get("LogicalId")
        or parameters.get("LOGICAL_ID")
        or item.name
        or (
            f"{item.definition}@{item.location[0]},{item.location[1]}"
            if item.location is not None
            else f"{item.definition}@unresolved"
        )
    )


def _validated_vertices(key, vertices):
    try:
        return validate_orthogonal_route(vertices)
    except BackendError as error:
        raise _invalid("A conductor route is invalid.", key) from error


def _invalid(message: str, object_key: str) -> BackendError:
    return BackendError(
        "LCC_STRUCTURE_INVALID",
        message,
        "hvdc",
        "read_lcc_project_graph",
        {"object_key": object_key},
    )
