"""No-mutation Blueprint generation and verification for corpus graphs."""

from __future__ import annotations

from typing import Any, Mapping

from ...core.backend.base import BackendError
from .corpus_extractor import graph_signature
from .corpus_models import BlueprintVerification, CorpusSource, ProjectGraph
from .models import json_safe
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


def verify_blueprint_candidate(value: Any, graph: ProjectGraph) -> BlueprintVerification:
    """Verify a corpus Blueprint against its immutable offline graph contract."""

    _reject_unsafe_shape(value)
    blueprint = parse_blueprint(value)
    if blueprint.operations:
        raise _error("CORPUS_BLUEPRINT_UNSAFE", "Corpus Blueprint operations must be empty.")
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
    observed_required = json_safe(blueprint.source_package["required"])
    identity_matches = (
        blueprint.identity.name == f"{graph.project_id}-existing-v1"
        and blueprint.identity.inspection_profile == _INSPECTION_PROFILE
        and graph.pscad_version in blueprint.identity.supported_pscad_versions
    )
    source_matches = observed_required == expected_required
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
