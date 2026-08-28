from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, TypeVar

from .models import (
    EvidenceRef,
    ProjectTopology,
    TopologyBoundaryLink,
    TopologyCanvas,
    TopologyComponent,
    TopologyConductor,
    TopologyConflict,
    TopologyLabel,
    TopologyPort,
    TopologySnapshot,
)


_Record = TypeVar("_Record")


def reconcile_snapshots(
    live: TopologySnapshot | None,
    saved: TopologySnapshot | None,
) -> ProjectTopology:
    if live is None and saved is None:
        raise ValueError("at least one topology snapshot is required")
    if live is None:
        return _project_from_file_only(saved)
    return _merge_live_with_saved(live, saved)


def _project_from_file_only(saved: TopologySnapshot | None) -> ProjectTopology:
    if saved is None:
        raise ValueError("saved topology snapshot is required")
    return ProjectTopology(
        project_name=saved.project_name,
        pscad_version=saved.pscad_version,
        project_path=saved.project_path,
        canvases=tuple(sorted(saved.canvases, key=lambda item: item.key)),
        components=tuple(sorted(saved.components, key=lambda item: item.key)),
        conductors=tuple(sorted(saved.conductors, key=lambda item: item.key)),
        labels=tuple(sorted(saved.labels, key=lambda item: item.key)),
        boundary_links=tuple(
            sorted(saved.boundary_links, key=lambda item: item.key)
        ),
        unresolved=tuple(sorted(set(saved.unresolved))),
        source_fingerprints=_source_fingerprints(None, saved),
        source_capabilities=_source_capabilities(None, saved),
        grid_step=saved.grid_step,
    )


def _merge_live_with_saved(
    live: TopologySnapshot,
    saved: TopologySnapshot | None,
) -> ProjectTopology:
    conflicts: list[TopologyConflict] = []
    unresolved = set(live.unresolved)
    if saved is not None:
        unresolved.update(saved.unresolved)

    saved_canvases = _by_key(saved.canvases if saved else ())
    canvases = tuple(
        sorted(
            (
                _merge_canvas(canvas, saved_canvases.get(canvas.key))
                for canvas in live.canvases
            ),
            key=lambda item: item.key,
        )
    )
    components = _merge_identity_records(
        live.components,
        saved.components if saved else (),
        lambda observed, file_record: _merge_component(
            observed, file_record, conflicts
        ),
        unresolved,
    )
    conductors = _merge_identity_records(
        live.conductors,
        saved.conductors if saved else (),
        _merge_conductor,
        unresolved,
    )
    labels = _merge_identity_records(
        live.labels,
        saved.labels if saved else (),
        _merge_label,
        unresolved,
    )
    boundary_links = _merge_boundary_links(
        live,
        saved,
        unresolved,
    )

    return ProjectTopology(
        project_name=live.project_name,
        pscad_version=live.pscad_version,
        project_path=live.project_path,
        canvases=canvases,
        components=components,
        conductors=conductors,
        labels=labels,
        boundary_links=boundary_links,
        conflicts=tuple(
            sorted(conflicts, key=lambda item: (item.object_key, item.field))
        ),
        unresolved=tuple(sorted(unresolved)),
        source_fingerprints=_source_fingerprints(live, saved),
        source_capabilities=_source_capabilities(live, saved),
        grid_step=live.grid_step,
    )


def _merge_identity_records(
    live_records: tuple[_Record, ...],
    saved_records: tuple[_Record, ...],
    merge: Callable[[_Record, _Record | None], _Record],
    unresolved: set[str],
) -> tuple[_Record, ...]:
    live_by_identity = {_identity(item): item for item in live_records}
    saved_by_identity = {_identity(item): item for item in saved_records}
    result = []
    for identity, observed in live_by_identity.items():
        file_record = saved_by_identity.get(identity)
        if file_record is None:
            unresolved.add(f"unsaved_live_evidence:{observed.key}")
        result.append(merge(observed, file_record))
    for identity, file_record in saved_by_identity.items():
        if identity not in live_by_identity:
            unresolved.add(f"stale_file_evidence:{file_record.key}")
    return tuple(sorted(result, key=lambda item: item.key))


def _identity(record) -> tuple[str, str]:
    return record.canvas_key, record.object_id


def _merge_canvas(
    live: TopologyCanvas,
    saved: TopologyCanvas | None,
) -> TopologyCanvas:
    if saved is None:
        return live
    return replace(
        live,
        name=_fill(live.name, saved.name),
        parent_key=_fill(live.parent_key, saved.parent_key),
        page_ports=_fill(live.page_ports, saved.page_ports),
    )


def _merge_component(
    live: TopologyComponent,
    saved: TopologyComponent | None,
    conflicts: list[TopologyConflict],
) -> TopologyComponent:
    if saved is None:
        return live
    definition = _field(
        live.key,
        "definition",
        live.definition,
        saved.definition,
        live.evidence,
        saved.evidence,
        conflicts,
    )
    location = _field(
        live.key,
        "location",
        live.location,
        saved.location,
        live.evidence,
        saved.evidence,
        conflicts,
    )
    orientation = _field(
        live.key,
        "orientation",
        live.orientation,
        saved.orientation,
        live.evidence,
        saved.evidence,
        conflicts,
    )
    active = _field(
        live.key,
        "active",
        live.active,
        saved.active,
        live.evidence,
        saved.evidence,
        conflicts,
    )
    ports = _merge_ports(live, saved, conflicts)
    return replace(
        live,
        definition=definition,
        name=_fill(live.name, saved.name),
        location=location,
        orientation=orientation,
        active=active,
        parameters=_fill(live.parameters, saved.parameters),
        ports=ports,
        evidence=_merge_evidence(live.evidence, saved.evidence),
    )


def _merge_ports(
    live_component: TopologyComponent,
    saved_component: TopologyComponent,
    conflicts: list[TopologyConflict],
) -> tuple[TopologyPort, ...]:
    if not live_component.ports:
        return saved_component.ports
    saved_ports = {port.key: port for port in saved_component.ports}
    result = []
    for live in live_component.ports:
        saved = saved_ports.get(live.key)
        if saved is None:
            result.append(live)
            continue
        absolute = _field(
            live.key,
            "absolute",
            live.absolute,
            saved.absolute,
            live.evidence,
            saved.evidence,
            conflicts,
        )
        kind = _field(
            live.key,
            "kind",
            live.kind,
            saved.kind,
            live.evidence,
            saved.evidence,
            conflicts,
        )
        dimension = _field(
            live.key,
            "dimension",
            live.dimension,
            saved.dimension,
            live.evidence,
            saved.evidence,
            conflicts,
        )
        active = _field(
            live.key,
            "active",
            live.active,
            saved.active,
            live.evidence,
            saved.evidence,
            conflicts,
        )
        result.append(
            replace(
                live,
                name=_fill(live.name, saved.name),
                absolute=absolute,
                relative=_fill(live.relative, saved.relative),
                kind=kind,
                dimension=dimension,
                active=active,
                required=_fill(live.required, saved.required),
                evidence=_merge_evidence(live.evidence, saved.evidence),
            )
        )
    return tuple(sorted(result, key=lambda item: item.key))


def _merge_conductor(
    live: TopologyConductor,
    saved: TopologyConductor | None,
) -> TopologyConductor:
    if saved is None:
        return live
    return replace(
        live,
        namespace=_fill(live.namespace, saved.namespace),
        vertices=_fill(live.vertices, saved.vertices),
        evidence=_merge_evidence(live.evidence, saved.evidence),
    )


def _merge_label(
    live: TopologyLabel,
    saved: TopologyLabel | None,
) -> TopologyLabel:
    if saved is None:
        return live
    return replace(
        live,
        name=_fill(live.name, saved.name),
        namespace=_fill(live.namespace, saved.namespace),
        scope=_fill(live.scope, saved.scope),
        location=_fill(live.location, saved.location),
        evidence=_merge_evidence(live.evidence, saved.evidence),
    )


def _merge_boundary_links(
    live: TopologySnapshot,
    saved: TopologySnapshot | None,
    unresolved: set[str],
) -> tuple[TopologyBoundaryLink, ...]:
    links = {link.key: link for link in live.boundary_links}
    if saved is None:
        unresolved.update(
            f"unsaved_live_evidence:{link.key}" for link in live.boundary_links
        )
        return tuple(sorted(links.values(), key=lambda item: item.key))
    saved_keys = {link.key for link in saved.boundary_links}
    unresolved.update(
        f"unsaved_live_evidence:{link.key}"
        for link in live.boundary_links
        if link.key not in saved_keys
    )
    live_components = {component.key for component in live.components}
    live_canvases = {canvas.key for canvas in live.canvases}
    for saved_link in saved.boundary_links:
        if saved_link.key in links:
            observed = links[saved_link.key]
            links[saved_link.key] = replace(
                observed,
                evidence=_merge_evidence(
                    observed.evidence, saved_link.evidence
                ),
            )
            continue
        outer_component_key = saved_link.outer_port_key.rsplit(":", 1)[0]
        required_canvases = {
            saved_link.outer_canvas_key,
            saved_link.inner_canvas_key,
        }
        if (
            outer_component_key in live_components
            and required_canvases <= live_canvases
        ):
            links[saved_link.key] = saved_link
        else:
            unresolved.add(
                f"hierarchy_boundary_unconfirmed:{saved_link.key}"
            )
    return tuple(sorted(links.values(), key=lambda item: item.key))


def _field(
    object_key: str,
    field: str,
    live_value: Any,
    file_value: Any,
    live_evidence: tuple[EvidenceRef, ...],
    file_evidence: tuple[EvidenceRef, ...],
    conflicts: list[TopologyConflict],
) -> Any:
    if _is_empty(live_value):
        return file_value
    if not _is_empty(file_value) and live_value != file_value:
        conflicts.append(
            TopologyConflict(
                field=field,
                object_key=object_key,
                live_value=live_value,
                file_value=file_value,
                evidence=_merge_evidence(live_evidence, file_evidence),
            )
        )
    return live_value


def _fill(live_value: Any, file_value: Any) -> Any:
    return file_value if _is_empty(live_value) else live_value


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == "unknown" or value == ()


def _merge_evidence(
    live: tuple[EvidenceRef, ...],
    saved: tuple[EvidenceRef, ...],
) -> tuple[EvidenceRef, ...]:
    unique = {item for item in live + saved}
    return tuple(
        sorted(
            unique,
            key=lambda item: (
                item.source,
                item.reference,
                item.status,
                item.fingerprint or "",
                item.observed_at_ns if item.observed_at_ns is not None else -1,
            ),
        )
    )


def _source_fingerprints(
    live: TopologySnapshot | None,
    saved: TopologySnapshot | None,
) -> tuple[tuple[str, str], ...]:
    result = []
    for snapshot in (live, saved):
        if snapshot is not None and snapshot.source_fingerprint:
            result.append((snapshot.source, snapshot.source_fingerprint))
    return tuple(result)


def _source_capabilities(
    live: TopologySnapshot | None,
    saved: TopologySnapshot | None,
) -> tuple[tuple[str, bool], ...]:
    result = []
    for snapshot in (live, saved):
        if snapshot is None:
            continue
        result.extend(
            (f"{snapshot.source}.{name}", supported)
            for name, supported in snapshot.capabilities
        )
    return tuple(sorted(result))


def _by_key(records) -> dict[str, Any]:
    return {item.key: item for item in records}
