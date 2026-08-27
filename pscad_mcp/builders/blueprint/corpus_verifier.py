"""No-mutation Blueprint generation and verification for corpus graphs."""

from __future__ import annotations

import re
from typing import Any, Mapping
import unicodedata

from ...core.backend.base import BackendError
from .corpus_extractor import graph_signature
from .corpus_models import (
    BlueprintVerification,
    CorpusDefinition,
    CorpusSource,
    LiveVerification,
    LiveVerificationCheck,
    ProjectGraph,
)
from .inventory import InventorySnapshot, read_live_inventory
from .models import freeze, json_safe
from .schema import parse_blueprint


_INSPECTION_PROFILE = "corpus-existing-project-v1"
_EVIDENCE_FILES = ["plan.json", "validation-report.json", "manifest.json"]


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "corpus", "verify_blueprint_candidate", details)


def _required_structure(graph: ProjectGraph) -> list[dict[str, Any]]:
    return [
        {
            "logical_id": component.key,
            "definition": component.definition_key,
            "canvas": component.canvas_key,
        }
        for component in sorted(graph.components, key=lambda item: item.key)
    ]


def _required_parameters(graph: ProjectGraph) -> list[dict[str, Any]]:
    return [
        {
            "logical_id": component.key,
            "name": name,
            "value": value,
        }
        for component in sorted(graph.components, key=lambda item: item.key)
        for name, value in sorted(component.parameters.items())
    ]


def _required_outputs(graph: ProjectGraph) -> list[dict[str, Any]]:
    return [
        {
            "channel": channel.key,
            "units": channel.units or channel.dimension or "unspecified",
            "required": channel.resolved,
        }
        for channel in sorted(graph.output_channels, key=lambda item: item.key)
    ]


def _source_requirements(source: CorpusSource) -> list[dict[str, Any]]:
    return [
        {"path": source.basename, "kind": "file", "sha256": source.sha256},
        *[
            {"path": dependency.basename, "kind": "file", "sha256": dependency.sha256}
            for dependency in source.dependencies
        ],
    ]


def _expected_acceptance(graph: ProjectGraph) -> dict[str, Any]:
    return {
        "required_structure": _required_structure(graph),
        "required_parameters": _required_parameters(graph),
        "blocking_messages": ["error", "fatal"],
        "outputs": _required_outputs(graph),
        "rules": [],
    }


def generate_blueprint_candidate(source: CorpusSource, graph: ProjectGraph) -> dict[str, Any]:
    """Generate a production-schema Blueprint that can only inspect existing sources."""

    observed_dependencies = dict(graph.dependency_hashes)
    expected_dependencies = {dependency.basename: dependency.sha256 for dependency in source.dependencies}
    if (
        source.project_id != graph.project_id
        or source.sha256 != graph.source_sha256
        or graph.pscad_version not in source.pscad_versions
        or observed_dependencies != expected_dependencies
    ):
        raise _error(
            "CORPUS_BLUEPRINT_MISMATCH",
            "Source specification and normalized graph do not describe the same project.",
            project_id=graph.project_id,
        )
    return {
        "identity": {
            "schema_version": 1,
            "name": f"{source.project_id}-existing-v1",
            "supported_pscad_versions": list(source.pscad_versions),
            "inspection_profile": _INSPECTION_PROFILE,
        },
        "source_package": {
            "entry_point": source.basename,
            "required": _source_requirements(source),
            "handling_policy": "read_only",
        },
        "operations": [],
        "acceptance": _expected_acceptance(graph),
        "publication": {
            "delivery_package": False,
            "evidence_files": list(_EVIDENCE_FILES),
            "scope": "evidence_only",
        },
    }


def _reject_unsafe_shape(value: Any) -> None:
    if not isinstance(value, Mapping):
        return
    operations = value.get("operations")
    source_package = value.get("source_package")
    publication = value.get("publication")
    if isinstance(operations, list) and operations:
        raise _error("CORPUS_BLUEPRINT_UNSAFE", "Corpus Blueprint operations must be empty.")
    if isinstance(source_package, Mapping) and source_package.get("handling_policy") != "read_only":
        raise _error("CORPUS_BLUEPRINT_UNSAFE", "Corpus Blueprint source handling must be read-only.")
    if isinstance(publication, Mapping) and (
        publication.get("delivery_package") is not False or publication.get("scope") != "evidence_only"
    ):
        raise _error("CORPUS_BLUEPRINT_UNSAFE", "Corpus Blueprint publication must remain evidence-only.")


def verify_blueprint_candidate(
    value: Any,
    graph: ProjectGraph,
    source: CorpusSource | None = None,
) -> BlueprintVerification:
    """Verify a corpus Blueprint against its immutable offline graph contract."""

    _reject_unsafe_shape(value)
    blueprint = parse_blueprint(value)
    if blueprint.operations:
        raise _error("CORPUS_BLUEPRINT_UNSAFE", "Corpus Blueprint operations must be empty.")
    if source is None:
        expected_required = [
            {
                "path": blueprint.source_package["entry_point"],
                "kind": "file",
                "sha256": graph.source_sha256,
            },
            *[
                {"path": basename, "kind": "file", "sha256": digest}
                for basename, digest in graph.dependency_hashes.items()
            ],
        ]
        source_identity_matches = True
    else:
        expected_required = _source_requirements(source)
        source_identity_matches = (
            source.project_id == graph.project_id
            and source.sha256 == graph.source_sha256
            and blueprint.source_package["entry_point"] == source.basename
            and blueprint.identity.supported_pscad_versions == source.pscad_versions
            and dict(graph.dependency_hashes)
            == {dependency.basename: dependency.sha256 for dependency in source.dependencies}
        )
    observed_required = json_safe(blueprint.source_package["required"])
    identity_matches = (
        blueprint.identity.name == f"{graph.project_id}-existing-v1"
        and blueprint.identity.inspection_profile == _INSPECTION_PROFILE
        and graph.pscad_version in blueprint.identity.supported_pscad_versions
    )
    source_matches = source_identity_matches and observed_required == expected_required
    acceptance_matches = json_safe(blueprint.acceptance) == _expected_acceptance(graph)
    publication_matches = (
        blueprint.publication.delivery_package is False
        and blueprint.publication.evidence_files == tuple(_EVIDENCE_FILES)
        and blueprint.publication.scope == "evidence_only"
    )
    if not (identity_matches and source_matches and acceptance_matches and publication_matches):
        raise _error(
            "CORPUS_BLUEPRINT_MISMATCH",
            "Blueprint candidate does not match the normalized project graph.",
            project_id=graph.project_id,
        )
    return BlueprintVerification(
        project_id=graph.project_id,
        blueprint_name=blueprint.identity.name,
        graph_signature=graph_signature(graph),
        source_hash_verified=True,
        operations_empty=True,
        status="verified",
    )


def _identity_part(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold().replace("_", "-")
    normalized = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE)
    return re.sub(r"-+", "-", normalized).strip("-.")


def _definition_identity(value: str) -> str:
    parts = value.split(":")
    if parts and parts[0].casefold() == "definition":
        parts = parts[1:]
    return ":".join(_identity_part(part) for part in parts)


def _definition_aliases(definition: CorpusDefinition) -> set[str]:
    aliases = {_definition_identity(definition.key), _definition_identity(definition.name)}
    if ":" not in definition.name:
        aliases.add(f"user:{_definition_identity(definition.name)}")
    return aliases


def _canvas_identity(value: str) -> str:
    normalized = value.split(":", 1)[1] if value.casefold().startswith("canvas:") else value
    return _identity_part(normalized)


def _equivalent(expected: Any, observed: Any) -> bool:
    return expected == observed or (observed is not None and str(expected) == str(observed))


def _check(kind: str, key: str, expected: Any, observed: Any, matched: bool) -> LiveVerificationCheck:
    return LiveVerificationCheck(
        kind=kind,
        key=key,
        status="matched" if matched else "mismatched",
        expected=freeze(expected),
        observed=freeze(observed),
    )


def _live_definition_lookup(snapshot: InventorySnapshot) -> dict[str, tuple[str, Mapping[str, Any]]]:
    lookup: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for name, metadata in snapshot.definitions.items():
        lookup[_definition_identity(name)] = (name, metadata)
    return lookup


def _definition_match(
    definition_key: str,
    definition_map: Mapping[str, CorpusDefinition],
    observed: str,
) -> bool:
    expected = definition_map.get(definition_key)
    aliases = {_definition_identity(definition_key)} if expected is None else _definition_aliases(expected)
    return _definition_identity(observed) in aliases


def _parameter_matches(
    graph: ProjectGraph,
    observed_components: Mapping[str, Mapping[str, Any]],
) -> tuple[bool, dict[str, Any]]:
    definitions = {definition.key: definition for definition in graph.definitions}
    mismatches: list[str] = []
    checked = 0
    for component in graph.components:
        observed = observed_components.get(component.key)
        if observed is None:
            mismatches.append(component.key)
            continue
        parameters = observed.get("parameters")
        metadata = observed.get("parameter_metadata")
        if not isinstance(parameters, Mapping) or not isinstance(metadata, Mapping):
            mismatches.append(component.key)
            continue
        definition = definitions.get(component.definition_key)
        declared = {parameter.name: parameter for parameter in definition.parameters} if definition else {}
        for name, value in component.parameters.items():
            checked += 1
            if name not in parameters or not _equivalent(value, parameters.get(name)):
                mismatches.append(f"{component.key}:{name}")
                continue
            expected_units = declared[name].units if name in declared else ""
            observed_metadata = metadata.get(name)
            observed_units = observed_metadata.get("units") if isinstance(observed_metadata, Mapping) else None
            if expected_units and not _equivalent(expected_units, observed_units):
                mismatches.append(f"{component.key}:{name}:units")
    return not mismatches, {"checked": checked, "mismatches": mismatches}


def _port_matches(graph: ProjectGraph, snapshot: InventorySnapshot) -> tuple[bool, dict[str, Any]]:
    live_definitions = _live_definition_lookup(snapshot)
    mismatches: list[str] = []
    checked = 0
    for definition in graph.definitions:
        observed_entry = next(
            (live_definitions[alias] for alias in _definition_aliases(definition) if alias in live_definitions),
            None,
        )
        if observed_entry is None:
            if definition.ports:
                mismatches.append(definition.key)
            continue
        ports = observed_entry[1].get("ports")
        if not isinstance(ports, Mapping):
            if definition.ports:
                mismatches.append(definition.key)
            continue
        for port in definition.ports:
            checked += 1
            observed = ports.get(port.name)
            if not isinstance(observed, Mapping) or not _equivalent(port.dimension, observed.get("dimension")):
                mismatches.append(port.key)
                continue
            observed_kind = observed.get("kind", observed.get("type"))
            expected_kinds = {item.casefold() for item in (port.type, port.model, port.mode) if item}
            if expected_kinds and observed_kind is not None and str(observed_kind).casefold() not in expected_kinds:
                mismatches.append(f"{port.key}:kind")
    return not mismatches, {"checked": checked, "mismatches": mismatches}


def _compare_live(graph: ProjectGraph, snapshot: InventorySnapshot, project_name: str) -> tuple[LiveVerificationCheck, ...]:
    checks: list[LiveVerificationCheck] = []
    checks.append(
        _check("project", graph.project_id, graph.name, project_name, graph.name.casefold() == project_name.casefold())
    )
    checks.append(
        _check(
            "pscad_version",
            graph.project_id,
            graph.pscad_version,
            snapshot.pscad_version,
            graph.pscad_version == snapshot.pscad_version,
        )
    )
    live_definitions = _live_definition_lookup(snapshot)
    missing_definitions = [
        definition.key
        for definition in graph.definitions
        if not any(alias in live_definitions for alias in _definition_aliases(definition))
    ]
    checks.append(
        _check(
            "definitions",
            graph.project_id,
            {"required": len(graph.definitions)},
            {"observed": len(snapshot.definitions), "missing": missing_definitions},
            not missing_definitions,
        )
    )
    logical_ids = [str(component["logical_id"]) for component in snapshot.components]
    observed_components = {str(component["logical_id"]): component for component in snapshot.components}
    expected_ids = {component.key for component in graph.components}
    component_shape_matches = len(logical_ids) == len(set(logical_ids)) and set(observed_components) == expected_ids
    definition_map = {definition.key: definition for definition in graph.definitions}
    component_mismatches: list[str] = []
    if component_shape_matches:
        for component in graph.components:
            observed = observed_components[component.key]
            if not (
                _definition_match(component.definition_key, definition_map, str(observed["definition"]))
                and _canvas_identity(component.canvas_key) == _canvas_identity(str(observed["canvas"]))
                and tuple(observed["location"]) == component.location
                and int(observed["orientation"]) == component.orientation
                and bool(observed["resolved"]) == component.resolved
            ):
                component_mismatches.append(component.key)
    checks.append(
        _check(
            "components",
            graph.project_id,
            {"count": len(graph.components), "logical_ids_unique": True},
            {
                "count": len(snapshot.components),
                "logical_ids_unique": len(logical_ids) == len(set(logical_ids)),
                "missing_or_extra": sorted(expected_ids.symmetric_difference(observed_components)),
                "mismatches": component_mismatches,
            },
            component_shape_matches and not component_mismatches,
        )
    )
    expected_canvases = {_canvas_identity(component.canvas_key) for component in graph.components}
    observed_canvases = {_canvas_identity(str(component["canvas"])) for component in snapshot.components}
    checks.append(
        _check(
            "canvases",
            graph.project_id,
            sorted(expected_canvases),
            sorted(observed_canvases),
            expected_canvases == observed_canvases,
        )
    )
    parameters_matched, parameter_evidence = _parameter_matches(graph, observed_components)
    checks.append(
        _check("parameters", graph.project_id, {"mismatches": []}, parameter_evidence, parameters_matched)
    )
    ports_matched, port_evidence = _port_matches(graph, snapshot)
    checks.append(_check("ports", graph.project_id, {"mismatches": []}, port_evidence, ports_matched))
    return tuple(checks)


async def verify_live_inventory(
    graph: ProjectGraph,
    service: Any,
    project_name: str,
) -> LiveVerification:
    """Compare the immutable offline graph with a read-only live inventory snapshot."""

    service_status = await service.status()
    snapshot = await read_live_inventory(service, project_name, _INSPECTION_PROFILE)
    checks = _compare_live(graph, snapshot, project_name)
    matched = all(check.status == "matched" for check in checks)
    backend = service_status.get("backend")
    return LiveVerification(
        project_id=graph.project_id,
        source_sha256=graph.source_sha256,
        backend=str(backend) if backend is not None else "unknown",
        pscad_version=snapshot.pscad_version,
        status="verified" if matched else "failed",
        live_verified=matched,
        checks=checks,
    )
