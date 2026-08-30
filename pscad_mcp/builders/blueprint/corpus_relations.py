"""Hierarchy and canonical relationship projection for schema-v2 corpora."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from ...core.backend.base import BackendError
from ...core.definition_metadata import (
    DefinitionMetadata,
    ParameterMetadata,
    PortMetadata,
)
from ...topology.geometry import GeometryError, absolute_port
from ...topology.hashing import canonical_sha256
from .corpus_conditions import ConditionUnresolved, evaluate_condition
from .corpus_models import ProjectGraph
from .corpus_relation_models import (
    CorpusComponentOccurrence,
    CorpusConductorOccurrence,
    CorpusDefinitionClassification,
    CorpusInstancePort,
    CorpusLabelOccurrence,
)
from .definition_catalog import (
    CatalogDefinition,
    DefinitionCatalog,
    classify_definition,
)
from .models import FrozenDict, freeze


@dataclass(frozen=True)
class PendingHierarchyBoundary:
    key: str
    parent_component_key: str
    child_canvas_key: str
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
