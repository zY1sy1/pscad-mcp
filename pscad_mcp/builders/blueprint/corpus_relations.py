"""Hierarchy and canonical relationship projection for schema-v2 corpora."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ...core.backend.base import BackendError
from ...topology.hashing import canonical_sha256
from .corpus_models import ProjectGraph
from .corpus_relation_models import (
    CorpusComponentOccurrence,
    CorpusConductorOccurrence,
    CorpusLabelOccurrence,
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
            has_content = bool(
                components_by_canvas[child_canvas.key]
                or conductors_by_canvas[child_canvas.key]
                or page_ports
            )
            if not explicit_children:
                if has_content:
                    raise _relation_error(
                        "Local child canvas lacks explicit hierarchy evidence.",
                        component=source_component.key,
                    )
                continue
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
