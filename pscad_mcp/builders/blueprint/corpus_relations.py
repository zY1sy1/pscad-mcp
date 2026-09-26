"""Hierarchy and canonical relationship projection for schema-v2 corpora."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import perf_counter_ns

from ...core.backend.base import BackendError
from ...core.definition_metadata import (
    DefinitionMetadata,
    ParameterMetadata,
    PortMetadata,
)
from ...topology.connectivity import build_connectivity
from ...topology.diagnostics.generic import infer_candidate_edges
from ...topology.geometry import GeometryError, absolute_port
from ...topology.hashing import canonical_sha256, topology_sha256
from ...topology.models import (
    EvidenceRef,
    ProjectTopology,
    TopologyBoundaryLink,
    TopologyCanvas,
    TopologyComponent,
    TopologyConductor,
    TopologyLabel,
    TopologyPort,
)
from .corpus_conditions import ConditionUnresolved, evaluate_condition
from .corpus_models import CorpusSpec, ProjectGraph
from .corpus_relation_models import (
    CorpusCandidateEdge,
    CorpusComponentOccurrence,
    CorpusConductorOccurrence,
    CorpusConfirmedNet,
    CorpusDefinitionClassification,
    CorpusHierarchyRelation,
    CorpusInstancePort,
    CorpusLabelOccurrence,
    CorpusPortNetMembership,
    CorpusUnresolvedEvidence,
)
from .definition_catalog import (
    CatalogDefinition,
    DefinitionCatalog,
    classify_definition,
    load_definition_catalog,
)
from .models import FrozenDict, freeze


@dataclass(frozen=True)
class PendingHierarchyBoundary:
    key: str
    parent_component_key: str
    child_canvas_key: str
    source_child_canvas_key: str
    page_port_names: tuple[str, ...]
    hierarchy_path: tuple[str, ...]


@dataclass(frozen=True)
class ExpandedHierarchy:
    components: tuple[CorpusComponentOccurrence, ...]
    conductors: tuple[CorpusConductorOccurrence, ...]
    labels: tuple[CorpusLabelOccurrence, ...]
    boundaries: tuple[PendingHierarchyBoundary, ...]
    source_to_occurrences: FrozenDict


@dataclass(frozen=True)
class MaterializedPorts:
    classifications: tuple[CorpusDefinitionClassification, ...]
    ports: tuple[CorpusInstancePort, ...]


@dataclass(frozen=True)
class RelationshipBuild:
    graph: ProjectGraph
    topology: ProjectTopology = field(compare=False, repr=False)
    confirmed_topology_hash: str
    phase_timings_ms: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class _ResolvedDefinition:
    key: str
    definition: CatalogDefinition
    port_keys: tuple[str, ...]


def _relation_error(message: str, **details: object) -> BackendError:
    return BackendError(
        "CORPUS_RELATION_INCOMPLETE",
        message,
        "corpus",
        "expand_hierarchy_occurrences",
        details,
    )


def _occurrence_key(
    kind: str,
    hierarchy_path: tuple[str, ...],
    source_key: str,
) -> str:
    digest = canonical_sha256(
        {
            "kind": kind,
            "hierarchy_path": hierarchy_path,
            "source_key": source_key,
        }
    )
    return f"occurrence:{kind}:{digest}"


def _label_namespace(definition_key: str) -> str | None:
    name = definition_key.rsplit(":", 1)[-1].casefold()
    if name == "datalabel":
        return "data"
    if name == "nodelabel":
        return "electrical"
    return None


def _label_name(name: str, parameters: FrozenDict) -> str:
    for key, value in parameters.items():
        if str(key).casefold() == "name" and str(value).strip():
            return str(value).strip()
    return name


def expand_hierarchy_occurrences(graph: ProjectGraph) -> ExpandedHierarchy:
    if graph.schema_version != 2 or graph.normalization_profile != "pscad-xml-v2":
        raise _relation_error("Hierarchy expansion requires a schema-v2 graph.")
    components_by_key = {item.key: item for item in graph.components}
    canvases_by_key = {item.key: item for item in graph.canvases}
    canvases_by_definition = {item.owner_definition: item for item in graph.canvases}
    definitions_by_key = {item.key: item for item in graph.definitions}
    if (
        len(components_by_key) != len(graph.components)
        or len(canvases_by_key) != len(graph.canvases)
        or len(canvases_by_definition) != len(graph.canvases)
        or len(definitions_by_key) != len(graph.definitions)
    ):
        raise _relation_error("Hierarchy source identities are ambiguous.")
    components_by_canvas = defaultdict(list)
    conductors_by_canvas = defaultdict(list)
    for component in graph.components:
        components_by_canvas[component.canvas_key].append(component)
    for connection in graph.connections:
        if connection.kind != "hierarchy" and connection.canvas_key is not None:
            conductors_by_canvas[connection.canvas_key].append(connection)

    hierarchy = [item for item in graph.connections if item.kind == "hierarchy"]
    children_by_parent = defaultdict(list)
    root_edges = []
    relevant_edge_keys = set()
    called_components = set()
    for connection in hierarchy:
        if len(connection.endpoints) != 2:
            raise _relation_error(
                "Hierarchy relationship does not contain two endpoints.",
                relationship=connection.key,
            )
        parent, child = connection.endpoints
        if child not in components_by_key:
            if child.startswith("hierarchy-root:") and parent.startswith("project:"):
                continue
            raise _relation_error(
                "Hierarchy child component is unavailable.",
                relationship=connection.key,
            )
        relevant_edge_keys.add(connection.key)
        called_components.add(child)
        if parent in components_by_key:
            children_by_parent[parent].append((connection, child))
        else:
            root_edges.append((connection, child))

    if root_edges:
        root_canvases = {
            components_by_key[child].canvas_key for _connection, child in root_edges
        }
    else:
        root_canvases = {
            item.key for item in graph.canvases if item.name.casefold() == "main"
        }
    if not root_canvases:
        raise _relation_error("No explicit root canvas can be selected.")

    components = []
    conductors = []
    labels = []
    boundaries = []
    source_occurrences = defaultdict(list)
    used_edges = {connection.key for connection, _child in root_edges}

    def expand_canvas(
        source_canvas_key: str,
        hierarchy_path: tuple[str, ...],
        active_definitions: tuple[str, ...],
    ) -> str:
        source_canvas = canvases_by_key.get(source_canvas_key)
        if source_canvas is None:
            raise _relation_error(
                "Hierarchy canvas is unavailable.",
                canvas=source_canvas_key,
            )
        canvas_key = _occurrence_key("canvas", hierarchy_path, source_canvas_key)

        for connection in sorted(
            conductors_by_canvas[source_canvas_key],
            key=lambda item: item.key,
        ):
            key = _occurrence_key("conductor", hierarchy_path, connection.key)
            kind = "bus" if "bus" in connection.kind else "wire"
            occurrence = CorpusConductorOccurrence(
                key=key,
                source_connection_key=connection.key,
                canvas_key=canvas_key,
                kind=kind,
                namespace=connection.namespace,
                vertices=connection.vertices,
            )
            conductors.append(occurrence)
            source_occurrences[connection.key].append(key)

        for source_component in sorted(
            components_by_canvas[source_canvas_key],
            key=lambda item: item.key,
        ):
            label_namespace = _label_namespace(source_component.definition_key)
            if label_namespace is not None:
                key = _occurrence_key("label", hierarchy_path, source_component.key)
                labels.append(
                    CorpusLabelOccurrence(
                        key=key,
                        source_component_key=source_component.key,
                        canvas_key=canvas_key,
                        name=_label_name(
                            source_component.name,
                            source_component.parameters,
                        ),
                        namespace=label_namespace,
                        scope=canvas_key,
                        location=source_component.location,
                    )
                )
                source_occurrences[source_component.key].append(key)
                if children_by_parent.get(source_component.key):
                    raise _relation_error(
                        "A label cannot own a hierarchy child.",
                        component=source_component.key,
                    )
                continue

            key = _occurrence_key("component", hierarchy_path, source_component.key)
            component_occurrence = CorpusComponentOccurrence(
                key=key,
                source_component_key=source_component.key,
                canvas_key=canvas_key,
                source_canvas_key=source_component.canvas_key,
                definition_key=source_component.definition_key,
                hierarchy_path=hierarchy_path,
                name=source_component.name,
                location=source_component.location,
                orientation=source_component.orientation,
                parameters=source_component.parameters,
            )
            components.append(component_occurrence)
            source_occurrences[source_component.key].append(key)

            child_canvas = canvases_by_definition.get(source_component.definition_key)
            explicit_children = children_by_parent.get(source_component.key, [])
            if child_canvas is None:
                if explicit_children:
                    raise _relation_error(
                        "Hierarchy evidence names a definition without a canvas.",
                        component=source_component.key,
                    )
                continue

            child_definition = definitions_by_key.get(source_component.definition_key)
            page_ports = tuple(
                port.name
                for port in (() if child_definition is None else child_definition.ports)
                if port.page
            )
            if source_component.key not in called_components:
                raise _relation_error(
                    "Local child canvas lacks explicit hierarchy evidence.",
                    component=source_component.key,
                )
            if source_component.definition_key in active_definitions:
                raise _relation_error(
                    "Hierarchy definition cycle was detected.",
                    definition=source_component.definition_key,
                )
            if any(
                components_by_key[child].canvas_key != child_canvas.key
                for _connection, child in explicit_children
            ):
                raise _relation_error(
                    "Hierarchy child does not belong to the declared canvas.",
                    component=source_component.key,
                )
            used_edges.update(connection.key for connection, _child in explicit_children)
            child_path = (*hierarchy_path, source_component.key)
            child_canvas_key = expand_canvas(
                child_canvas.key,
                child_path,
                (*active_definitions, source_component.definition_key),
            )
            if page_ports:
                boundaries.append(
                    PendingHierarchyBoundary(
                        key=_occurrence_key(
                            "hierarchy",
                            child_path,
                            source_component.key,
                        ),
                        parent_component_key=key,
                        child_canvas_key=child_canvas_key,
                        source_child_canvas_key=child_canvas.key,
                        page_port_names=page_ports,
                        hierarchy_path=child_path,
                    )
                )
        return canvas_key

    for source_canvas_key in sorted(root_canvases):
        canvas = canvases_by_key[source_canvas_key]
        expand_canvas(
            source_canvas_key,
            (f"project:{graph.project_id}", source_canvas_key),
            (canvas.owner_definition,),
        )

    if used_edges != relevant_edge_keys:
        raise _relation_error(
            "Not every hierarchy relationship was consumed.",
            unused_count=len(relevant_edge_keys - used_edges),
        )
    return ExpandedHierarchy(
        components=tuple(sorted(components, key=lambda item: item.key)),
        conductors=tuple(sorted(conductors, key=lambda item: item.key)),
        labels=tuple(sorted(labels, key=lambda item: item.key)),
        boundaries=tuple(sorted(boundaries, key=lambda item: item.key)),
        source_to_occurrences=freeze(
            {
                key: tuple(sorted(values))
                for key, values in sorted(source_occurrences.items())
            }
        ),
    )


def _split_definition_key(key: str) -> tuple[str, str]:
    parts = key.split(":", 2)
    if len(parts) != 3 or parts[0] != "definition" or not all(parts[1:]):
        raise _relation_error("Component definition identity is invalid.", definition=key)
    return parts[1], parts[2]


def _local_port_dimension(
    value: str,
    definition_key: str,
    port_name: str,
) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise _relation_error(
            "Project-local port dimension is invalid.",
            definition=definition_key,
            port=port_name,
        ) from None


def _local_catalog_definition(graph: ProjectGraph, key: str) -> _ResolvedDefinition:
    definition = next((item for item in graph.definitions if item.key == key), None)
    if definition is None:
        raise _relation_error("Project-local definition is unavailable.", definition=key)
    ports = tuple(
        PortMetadata(
            name=port.name,
            x=port.offset[0],
            y=port.offset[1],
            dim=_local_port_dimension(port.dimension, key, port.name),
            type=port.type or None,
            model=port.model or None,
            kind=port.kind or None,
            page=port.page,
            mode=port.mode or None,
            condition=port.condition,
            occurrence=port.occurrence,
        )
        for port in definition.ports
    )
    parameters = {
        parameter.name: ParameterMetadata(
            name=parameter.name,
            type=parameter.type or None,
            unit=parameter.units or None,
            minimum=None,
            maximum=None,
            choices=(),
            default=parameter.default,
            intent=parameter.intent or None,
            readonly=False,
        )
        for parameter in definition.parameters
    }
    metadata = DefinitionMetadata(
        ports=ports,
        parameter_ranges={},
        parameters=parameters,
        name=definition.name,
    )
    return _ResolvedDefinition(
        key=key,
        definition=CatalogDefinition(
            namespace="user",
            pscad_version=graph.pscad_version,
            physical_name=definition.name,
            source_sha256=graph.source_sha256,
            metadata=metadata,
        ),
        port_keys=tuple(port.key for port in definition.ports),
    )


def _key_part(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    normalized = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE)
    return re.sub(r"-+", "-", normalized).strip("-.") or "unnamed"


def _external_port_key(definition_key: str, port: PortMetadata) -> str:
    return f"{definition_key}/port:{_key_part(port.name)}#{port.occurrence}"


def _resolve_definition(
    graph: ProjectGraph,
    catalog: DefinitionCatalog,
    key: str,
) -> _ResolvedDefinition:
    namespace, physical_name = _split_definition_key(key)
    if namespace == "user":
        return _local_catalog_definition(graph, key)
    definition = catalog.require(
        namespace,
        graph.pscad_version,
        physical_name,
    )
    return _ResolvedDefinition(
        key=key,
        definition=definition,
        port_keys=tuple(
            _external_port_key(key, port) for port in definition.metadata.ports
        ),
    )


def _port_namespace(port: PortMetadata) -> str:
    declared = (port.kind or "").strip().casefold()
    if declared in {"electrical", "natural"}:
        return "electrical"
    if declared in {"data", "signal", "transfer"}:
        return "data"
    model = (port.model or "").strip().casefold()
    if model == "natural":
        return "electrical"
    if model == "transfer":
        return "data"
    mode = (port.mode or "").strip().casefold()
    if mode == "electrical":
        return "electrical"
    return "unknown"


def _port_dimension(port: PortMetadata) -> int:
    dimension = int(port.dim or 1)
    if dimension < 1:
        raise ValueError("port dimension must be positive")
    return dimension


def _port_error(
    code: str,
    message: str,
    component_key: str,
    definition_key: str,
    port_name: str | None = None,
) -> BackendError:
    details = {
        "component": component_key,
        "definition": definition_key,
    }
    if port_name is not None:
        details["port"] = port_name
    return BackendError(code, message, "corpus", "materialize_instance_ports", details)


def materialize_instance_ports(
    graph: ProjectGraph,
    catalog: DefinitionCatalog,
    expanded: ExpandedHierarchy | None = None,
) -> MaterializedPorts:
    if graph.schema_version != 2 or graph.normalization_profile != "pscad-xml-v2":
        raise _relation_error("Port materialization requires a schema-v2 graph.")
    occurrences = expanded or expand_hierarchy_occurrences(graph)
    source_components = {item.key: item for item in graph.components}
    referenced_keys = {item.definition_key for item in occurrences.components}
    referenced_keys.update(
        source_components[item.source_component_key].definition_key
        for item in occurrences.labels
    )
    resolved = {
        key: _resolve_definition(graph, catalog, key)
        for key in sorted(referenced_keys)
    }
    classifications = tuple(
        CorpusDefinitionClassification(
            key=key,
            namespace=item.definition.namespace,
            pscad_version=item.definition.pscad_version,
            physical_name=item.definition.physical_name,
            classification=classify_definition(item.definition),
            port_contract_keys=item.port_keys,
            source_sha256=item.definition.source_sha256,
        )
        for key, item in sorted(resolved.items())
    )

    ports = []
    for component in sorted(occurrences.components, key=lambda item: item.key):
        contract = resolved[component.definition_key]
        if classify_definition(contract.definition) == "non_connective":
            continue
        defaults = {
            name: parameter.default
            for name, parameter in contract.definition.metadata.parameters.items()
            if parameter.default is not None
        }
        for port, definition_port_key in zip(
            contract.definition.metadata.ports,
            contract.port_keys,
            strict=True,
        ):
            try:
                active = evaluate_condition(
                    port.condition,
                    component.parameters,
                    defaults,
                )
            except ConditionUnresolved as error:
                raise _port_error(
                    "CORPUS_PORT_CONDITION_UNRESOLVED",
                    "Conditional port cannot be evaluated deterministically.",
                    component.key,
                    component.definition_key,
                    port.name,
                ) from error
            namespace = _port_namespace(port)
            if namespace == "unknown":
                raise _port_error(
                    "CORPUS_RELATION_INCOMPLETE",
                    "Port namespace cannot be classified.",
                    component.key,
                    component.definition_key,
                    port.name,
                )
            try:
                dimension = _port_dimension(port)
                absolute = absolute_port(
                    component.location,
                    (port.x, port.y),
                    component.orientation,
                )
            except (GeometryError, TypeError, ValueError) as error:
                raise _port_error(
                    "CORPUS_PORT_GEOMETRY_UNRESOLVED",
                    "Port geometry cannot be resolved.",
                    component.key,
                    component.definition_key,
                    port.name,
                ) from error
            ports.append(
                CorpusInstancePort(
                    key=(
                        f"{component.key}/port:{_key_part(port.name)}"
                        f"#{port.occurrence}"
                    ),
                    component_key=component.key,
                    source_component_key=component.source_component_key,
                    definition_port_key=definition_port_key,
                    name=port.name,
                    occurrence=port.occurrence,
                    relative=(port.x, port.y),
                    absolute=absolute,
                    namespace=namespace,
                    dimension=dimension,
                    active=active,
                    source_sha256=contract.definition.source_sha256,
                )
            )
    keys = [item.key for item in ports]
    if len(keys) != len(set(keys)):
        raise _relation_error("Materialized instance-port keys are ambiguous.")
    return MaterializedPorts(
        classifications=classifications,
        ports=tuple(sorted(ports, key=lambda item: item.key)),
    )


def _evidence(reference: str, fingerprint: str) -> tuple[EvidenceRef, ...]:
    return (EvidenceRef("corpus", reference, fingerprint=fingerprint),)


def _project_components(
    expanded: ExpandedHierarchy,
    ports: tuple[CorpusInstancePort, ...],
    fingerprint: str,
) -> tuple[TopologyComponent, ...]:
    ports_by_component = defaultdict(list)
    for port in ports:
        if port.active:
            ports_by_component[port.component_key].append(
                TopologyPort(
                    key=port.key,
                    component_key=port.component_key,
                    name=port.name,
                    absolute=port.absolute,
                    relative=port.relative,
                    kind=port.namespace,
                    dimension=port.dimension,
                    active=True,
                    evidence=_evidence(port.definition_port_key, port.source_sha256),
                )
            )
    return tuple(
        TopologyComponent(
            key=item.key,
            canvas_key=item.canvas_key,
            object_id=item.key,
            definition=item.definition_key,
            name=item.name,
            location=item.location,
            orientation=item.orientation,
            active=True,
            parameters=tuple(sorted(item.parameters.items())),
            ports=tuple(sorted(ports_by_component[item.key], key=lambda port: port.key)),
            evidence=_evidence(item.source_component_key, fingerprint),
        )
        for item in sorted(expanded.components, key=lambda component: component.key)
    )


def _project_conductors(
    expanded: ExpandedHierarchy,
    fingerprint: str,
) -> tuple[TopologyConductor, ...]:
    return tuple(
        TopologyConductor(
            key=item.key,
            canvas_key=item.canvas_key,
            object_id=item.key,
            kind=item.kind,
            namespace=item.namespace,
            vertices=item.vertices,
            evidence=_evidence(item.source_connection_key, fingerprint),
        )
        for item in sorted(expanded.conductors, key=lambda conductor: conductor.key)
    )


def _project_labels(
    expanded: ExpandedHierarchy,
    fingerprint: str,
) -> tuple[TopologyLabel, ...]:
    return tuple(
        TopologyLabel(
            key=item.key,
            canvas_key=item.canvas_key,
            object_id=item.key,
            name=item.name,
            namespace=item.namespace,
            scope=item.scope,
            location=item.location,
            evidence=_evidence(item.source_component_key, fingerprint),
        )
        for item in sorted(expanded.labels, key=lambda label: label.key)
    )


def _project_boundaries(
    expanded: ExpandedHierarchy,
    materialized: MaterializedPorts,
    fingerprint: str,
) -> tuple[
    tuple[CorpusInstancePort, ...],
    tuple[TopologyBoundaryLink, ...],
    tuple[CorpusHierarchyRelation, ...],
    dict[str, tuple[str, ...]],
]:
    components = {item.key: item for item in expanded.components}
    ports_by_component_name = defaultdict(list)
    for port in materialized.ports:
        ports_by_component_name[(port.component_key, port.name)].append(port)
    inner_ports = []
    links = []
    relations = []
    page_ports_by_canvas = defaultdict(list)
    for boundary in sorted(expanded.boundaries, key=lambda item: item.key):
        parent = components[boundary.parent_component_key]
        name_occurrences = defaultdict(int)
        for name in boundary.page_port_names:
            candidates = sorted(
                ports_by_component_name[(parent.key, name)],
                key=lambda item: item.occurrence,
            )
            index = name_occurrences[name]
            name_occurrences[name] += 1
            if index >= len(candidates):
                raise _relation_error(
                    "Hierarchy page port is absent from its parent component.",
                    component=parent.key,
                    port=name,
                )
            outer = candidates[index]
            if not outer.active:
                continue
            owner = f"boundary:{boundary.child_canvas_key}"
            inner_key = (
                f"{boundary.child_canvas_key}:page:{_key_part(name)}"
                f"#{outer.occurrence}"
            )
            inner = CorpusInstancePort(
                key=inner_key,
                component_key=owner,
                source_component_key=outer.source_component_key,
                definition_port_key=outer.definition_port_key,
                name=name,
                occurrence=outer.occurrence,
                relative=outer.relative,
                absolute=outer.relative,
                namespace=outer.namespace,
                dimension=outer.dimension,
                active=True,
                source_sha256=outer.source_sha256,
            )
            link_key = (
                f"{boundary.key}:port:{_key_part(name)}#{outer.occurrence}"
            )
            inner_ports.append(inner)
            page_ports_by_canvas[boundary.child_canvas_key].append(inner_key)
            links.append(
                TopologyBoundaryLink(
                    key=link_key,
                    outer_port_key=outer.key,
                    outer_canvas_key=parent.canvas_key,
                    outer_point=outer.absolute,
                    inner_port_key=inner_key,
                    inner_canvas_key=boundary.child_canvas_key,
                    inner_point=inner.absolute,
                    namespace=outer.namespace,
                    dimension=outer.dimension,
                    evidence=_evidence(boundary.key, fingerprint),
                )
            )
            relations.append(
                CorpusHierarchyRelation(
                    key=link_key,
                    parent_component_key=parent.key,
                    child_canvas_key=boundary.child_canvas_key,
                    outer_port_key=outer.key,
                    inner_port_key=inner_key,
                    namespace=outer.namespace,
                    dimension=outer.dimension,
                )
            )
    return (
        tuple(sorted(inner_ports, key=lambda item: item.key)),
        tuple(sorted(links, key=lambda item: item.key)),
        tuple(sorted(relations, key=lambda item: item.key)),
        {
            key: tuple(sorted(values))
            for key, values in sorted(page_ports_by_canvas.items())
        },
    )


def _project_canvases(
    graph: ProjectGraph,
    expanded: ExpandedHierarchy,
    boundaries: tuple[TopologyBoundaryLink, ...],
    page_ports_by_canvas: Mapping[str, tuple[str, ...]],
) -> tuple[TopologyCanvas, ...]:
    source_canvases = {item.key: item for item in graph.canvases}
    source_components = {item.key: item for item in graph.components}
    source_connections = {item.key: item for item in graph.connections}
    source_by_occurrence = {}
    for item in expanded.components:
        source_by_occurrence[item.canvas_key] = item.source_canvas_key
    for item in expanded.conductors:
        source = source_connections[item.source_connection_key]
        if source.canvas_key is not None:
            source_by_occurrence[item.canvas_key] = source.canvas_key
    for item in expanded.labels:
        source_by_occurrence[item.canvas_key] = source_components[
            item.source_component_key
        ].canvas_key
    for item in expanded.boundaries:
        source_by_occurrence[item.child_canvas_key] = item.source_child_canvas_key
    parent_by_canvas = {}
    component_by_key = {item.key: item for item in expanded.components}
    for boundary in boundaries:
        parent_by_canvas[boundary.inner_canvas_key] = component_by_key[
            next(
                item.parent_component_key
                for item in expanded.boundaries
                if boundary.key.startswith(item.key)
            )
        ].canvas_key
    return tuple(
        TopologyCanvas(
            key=canvas_key,
            name=source_canvases[source_key].name,
            parent_key=parent_by_canvas.get(canvas_key),
            page_ports=page_ports_by_canvas.get(canvas_key, ()),
        )
        for canvas_key, source_key in sorted(source_by_occurrence.items())
    )


def _unresolved_records(
    topology: ProjectTopology,
    ambiguous_crossings: tuple[tuple[str, str, tuple[int, int]], ...],
    graph: ProjectGraph,
) -> tuple[CorpusUnresolvedEvidence, ...]:
    result = []
    for item in topology.unresolved:
        code, separator, identity = item.partition(":")
        result.append(
            CorpusUnresolvedEvidence(
                code=code.upper(),
                object_keys=(identity if separator else item,),
                evidence=(item,),
                classification="engineering",
            )
        )
    for left, right, point in ambiguous_crossings:
        result.append(
            CorpusUnresolvedEvidence(
                code="CROSSING_AMBIGUOUS",
                object_keys=(left, right),
                evidence=(f"{point[0]},{point[1]}",),
                classification="engineering",
            )
        )
    for warning in graph.warnings:
        result.append(
            CorpusUnresolvedEvidence(
                code=warning.kind.upper(),
                object_keys=(warning.path,),
                evidence=(f"count:{warning.count}",),
                classification="blocking" if warning.blocking else "engineering",
            )
        )
    unique = {
        (item.code, item.object_keys): item
        for item in result
    }
    return tuple(sorted(unique.values(), key=lambda item: (item.code, item.object_keys)))


def confirmed_relation_signature(graph: ProjectGraph) -> str:
    return canonical_sha256(
        {
            "definition_classifications": [
                item.to_dict() for item in graph.definition_classifications
            ],
            "component_occurrences": [
                item.to_dict() for item in graph.component_occurrences
            ],
            "instance_ports": [item.to_dict() for item in graph.instance_ports],
            "confirmed_nets": [item.to_dict() for item in graph.confirmed_nets],
            "port_net_memberships": [
                item.to_dict() for item in graph.port_net_memberships
            ],
            "hierarchy_relations": [
                item.to_dict() for item in graph.hierarchy_relations
            ],
        }
    )


def build_relationship_truth(
    raw_graph: ProjectGraph,
    spec: CorpusSpec,
    definition_bindings: Mapping[tuple[str, str], Path],
    *,
    infer: bool = True,
) -> RelationshipBuild:
    if spec.schema_version != 2 or spec.normalization_profile != "pscad-xml-v2":
        raise _relation_error("Relationship truth requires a schema-v2 specification.")
    matching_sources = [
        source
        for source in spec.entry_points
        if source.project_id == raw_graph.project_id
    ]
    if (
        len(matching_sources) != 1
        or matching_sources[0].sha256 != raw_graph.source_sha256
        or raw_graph.pscad_version not in matching_sources[0].pscad_versions
    ):
        raise _relation_error("Graph and source specification do not match.")

    timings = {}
    started = perf_counter_ns()
    catalog = load_definition_catalog(spec.definition_sources, definition_bindings)
    timings["definition_catalog"] = (perf_counter_ns() - started) / 1_000_000

    started = perf_counter_ns()
    expanded = expand_hierarchy_occurrences(raw_graph)
    materialized = materialize_instance_ports(raw_graph, catalog, expanded)
    timings["relationship_evidence"] = (perf_counter_ns() - started) / 1_000_000

    inner_ports, boundary_links, hierarchy_relations, page_ports = (
        _project_boundaries(
            expanded,
            materialized,
            raw_graph.source_sha256,
        )
    )
    topology = ProjectTopology(
        project_name=raw_graph.name,
        pscad_version=raw_graph.pscad_version,
        canvases=_project_canvases(
            raw_graph,
            expanded,
            boundary_links,
            page_ports,
        ),
        components=_project_components(
            expanded,
            materialized.ports,
            raw_graph.source_sha256,
        ),
        conductors=_project_conductors(expanded, raw_graph.source_sha256),
        labels=_project_labels(expanded, raw_graph.source_sha256),
        boundary_links=boundary_links,
        unresolved=(),
        source_fingerprints=(("corpus", raw_graph.source_sha256),),
        source_capabilities=(
            ("corpus.components", True),
            ("corpus.conductors", True),
            ("corpus.hierarchy", True),
            ("corpus.labels", True),
            ("corpus.ports", True),
        ),
        grid_step=18,
    )
    started = perf_counter_ns()
    connectivity = build_connectivity(topology)
    topology = connectivity.topology
    timings["connectivity"] = (perf_counter_ns() - started) / 1_000_000

    started = perf_counter_ns()
    candidates = infer_candidate_edges(topology) if infer else ()
    timings["inference"] = (perf_counter_ns() - started) / 1_000_000
    if candidates:
        topology = replace(topology, candidate_edges=candidates)

    confirmed_nets = tuple(
        CorpusConfirmedNet(
            key=item.key,
            namespace=item.namespace,
            port_keys=item.port_keys,
            conductor_keys=item.conductor_keys,
            label_keys=item.label_keys,
            junctions=item.junctions,
        )
        for item in topology.nets
    )
    net_keys_by_port = defaultdict(set)
    for net in confirmed_nets:
        for port_key in net.port_keys:
            net_keys_by_port[port_key].add(net.key)
    confirmed_hierarchy_relations = tuple(
        item
        for item in hierarchy_relations
        if net_keys_by_port[item.outer_port_key]
        & net_keys_by_port[item.inner_port_key]
    )
    confirmed_inner_port_keys = {
        item.inner_port_key for item in confirmed_hierarchy_relations
    }
    all_ports = tuple(
        sorted(
            (
                *materialized.ports,
                *(
                    item
                    for item in inner_ports
                    if item.key in confirmed_inner_port_keys
                ),
            ),
            key=lambda item: item.key,
        )
    )
    port_by_key = {item.key: item for item in all_ports}
    memberships = []
    for net in confirmed_nets:
        for port_key in net.port_keys:
            port = port_by_key.get(port_key)
            if port is None:
                raise _relation_error(
                    "Confirmed net contains an unprojected port.",
                    port=port_key,
                )
            memberships.append(
                CorpusPortNetMembership(
                    key=f"membership:{canonical_sha256((port_key, net.key))}",
                    component_key=port.component_key,
                    port_key=port_key,
                    net_key=net.key,
                    namespace=net.namespace,
                )
            )
    candidate_records = tuple(
        CorpusCandidateEdge(
            left=item.left,
            right=item.right,
            confidence=item.confidence,
            reasons=item.reasons,
            counter_evidence=item.counter_evidence,
        )
        for item in candidates
    )
    graph = replace(
        raw_graph,
        definition_classifications=materialized.classifications,
        component_occurrences=expanded.components,
        conductor_occurrences=expanded.conductors,
        label_occurrences=expanded.labels,
        instance_ports=all_ports,
        confirmed_nets=confirmed_nets,
        port_net_memberships=tuple(sorted(memberships, key=lambda item: item.key)),
        hierarchy_relations=confirmed_hierarchy_relations,
        candidate_edges=candidate_records,
        unresolved_evidence=_unresolved_records(
            topology,
            connectivity.ambiguous_crossings,
            raw_graph,
        ),
        definition_catalog_signature=catalog.catalog_signature,
    )
    graph = replace(
        graph,
        confirmed_relation_signature=confirmed_relation_signature(graph),
    )
    catalog.verify_unchanged()
    return RelationshipBuild(
        graph=graph,
        topology=topology,
        confirmed_topology_hash=topology_sha256(topology),
        phase_timings_ms=tuple(sorted(timings.items())),
    )
