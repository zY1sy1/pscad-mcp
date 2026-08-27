"""Deterministic adaptation from canonical topology to HVDC evidence."""

from __future__ import annotations

from ...hvdc.models import (
    HvdcComponentRecord,
    HvdcConnectionRecord,
    HvdcLabelRecord,
    HvdcProjectEvidence,
    HvdcSourceRef,
)
from ..models import ProjectTopology, TopologyPort


def topology_to_hvdc_evidence(
    topology: ProjectTopology,
) -> HvdcProjectEvidence:
    """Map confirmed canonical records into the public HVDC evidence model."""
    project_path = topology.project_path or topology.project_name
    ports_by_key = {
        port.key: (component, port)
        for component in topology.components
        for port in component.ports
    }
    label_names_by_key = {item.key: item.name for item in topology.labels}
    component_labels: dict[str, set[str]] = {
        item.key: set() for item in topology.components
    }
    for net in topology.nets:
        names = {
            label_names_by_key[key]
            for key in net.label_keys
            if key in label_names_by_key
        }
        if not names:
            continue
        for port_key in net.port_keys:
            record = ports_by_key.get(port_key)
            if record is not None:
                component_labels[record[0].key].update(names)

    components = tuple(
        HvdcComponentRecord(
            component_id=component.object_id,
            name=component.name or component.object_id,
            definition=component.definition,
            parameters=dict(component.parameters),
            labels=tuple(sorted(component_labels[component.key])),
            ports=tuple(_port_payload(port) for port in component.ports),
            source=HvdcSourceRef(
                project_path=project_path,
                canvas_name=component.canvas_key,
                component_id=component.object_id,
                definition=component.definition,
            ),
        )
        for component in sorted(topology.components, key=lambda item: item.key)
    )
    labels = tuple(
        HvdcLabelRecord(
            text=label.name,
            kind="datalabel" if label.namespace == "data" else "label",
            source=HvdcSourceRef(
                project_path=project_path,
                canvas_name=label.canvas_key,
                component_id=label.object_id,
                definition=f"topology:{label.namespace}_label",
                label=label.name,
            ),
        )
        for label in sorted(topology.labels, key=lambda item: item.key)
    )

    connections = []
    for net in sorted(topology.nets, key=lambda item: item.key):
        endpoints = [
            ports_by_key[key]
            for key in sorted(net.port_keys)
            if key in ports_by_key
        ]
        if len(endpoints) < 2:
            continue
        source_component, source_port = endpoints[0]
        for index, (target_component, target_port) in enumerate(
            endpoints[1:],
            start=1,
        ):
            connections.append(
                HvdcConnectionRecord(
                    connection_id=f"{net.key}:{index}",
                    source_component_id=source_component.object_id,
                    source_port=source_port.name,
                    target_component_id=target_component.object_id,
                    target_port=target_port.name,
                    source=HvdcSourceRef(
                        project_path=project_path,
                        canvas_name=source_component.canvas_key,
                    ),
                    evidence=(f"topology_net:{net.key}",),
                )
            )

    return HvdcProjectEvidence(
        project_path=project_path,
        project_name=topology.project_name,
        pscad_version=topology.pscad_version,
        definitions=tuple(
            sorted(
                {
                    item.definition
                    for item in topology.components
                    if item.definition
                }
            )
        ),
        components=components,
        labels=labels,
        connections=tuple(connections),
        warnings=tuple(sorted(topology.unresolved)),
    )


def _port_payload(port: TopologyPort) -> dict[str, object]:
    return {
        "key": port.key,
        "name": port.name,
        "absolute": port.absolute,
        "relative": port.relative,
        "kind": port.kind,
        "dimension": port.dimension,
        "active": port.active,
        "required": port.required,
    }
