"""Validated access to packaged Blueprint corpus resources."""

from __future__ import annotations

from collections import Counter
import hashlib
from importlib import resources
import json
from pathlib import PurePosixPath
import re
from typing import Any

from ...core.backend.base import BackendError
from .corpus_extractor import graph_signature
from .corpus_models import CorpusManifest, ProjectGraph
from .corpus_schema import parse_corpus_spec
from .corpus_verifier import verify_blueprint_candidate
from .corpus_writer import (
    canonical_json,
    canonical_jsonl,
    derive_records,
    parse_corpus_manifest,
    parse_project_graph,
)
from .models import Blueprint, FrozenDict, freeze
from .schema import parse_blueprint


_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "corpus", "load_packaged_corpus", details)


def _corpus_root(name: str):
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise _error("CORPUS_ASSET_NOT_FOUND", "Corpus name must be a simple identifier.")
    return resources.files("pscad_mcp").joinpath("assets", "corpora", name)


def _read(resource: Any, label: str) -> bytes:
    if not resource.is_file():
        raise _error("CORPUS_ASSET_NOT_FOUND", f"Packaged {label} is missing.")
    try:
        return resource.read_bytes()
    except OSError as error:
        raise _error("CORPUS_ASSET_INVALID", f"Packaged {label} is unreadable.") from error


def _json(content: bytes, label: str) -> Any:
    try:
        return json.loads(
            content.decode("ascii"),
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise _error("CORPUS_ASSET_INVALID", f"Packaged {label} is not strict ASCII JSON.") from error


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _project_resource(root: Any, relative: str, expected: str):
    candidate = PurePosixPath(relative)
    if candidate.as_posix() != expected or candidate.is_absolute() or ".." in candidate.parts:
        raise _error("CORPUS_ASSET_INVALID", "Packaged manifest contains an unsafe artifact path.")
    return root.joinpath(*candidate.parts)


def load_packaged_corpus_manifest(name: str = "moxing_v1") -> CorpusManifest:
    """Load and validate a canonical corpus manifest from installed resources."""

    content = _read(_corpus_root(name).joinpath("manifest.json"), "corpus manifest")
    manifest = parse_corpus_manifest(_json(content, "corpus manifest"))
    if manifest.name != name or content != canonical_json(manifest.to_dict()):
        raise _error("CORPUS_ASSET_INVALID", "Packaged corpus manifest is noncanonical or misnamed.")
    return manifest


def load_packaged_corpus_graphs(manifest: CorpusManifest) -> tuple[ProjectGraph, ...]:
    """Load all packaged graphs and bind them to manifest hashes and signatures."""

    root = _corpus_root(manifest.name)
    graphs: list[ProjectGraph] = []
    for project in manifest.projects:
        expected_path = f"graphs/{project.project_id}.json"
        resource = _project_resource(root, project.graph_path, expected_path)
        content = _read(resource, f"graph {project.project_id}")
        graph = parse_project_graph(_json(content, f"graph {project.project_id}"))
        if (
            content != canonical_json(graph.to_dict())
            or len(content) != project.graph_byte_length
            or _sha256(content) != project.graph_sha256
            or graph.project_id != project.project_id
            or graph.source_sha256 != project.source_sha256
            or graph_signature(graph) != project.graph_signature
        ):
            raise _error("CORPUS_ASSET_INVALID", "Packaged graph does not match its manifest.", project_id=project.project_id)
        graphs.append(graph)
    return tuple(graphs)


def load_packaged_corpus_record_files(manifest: CorpusManifest) -> FrozenDict:
    """Load record-file bytes after re-deriving them from packaged graphs."""

    root = _corpus_root(manifest.name)
    graph_map = {graph.project_id: graph for graph in load_packaged_corpus_graphs(manifest)}
    result: dict[str, bytes] = {}
    for project in manifest.projects:
        expected_path = f"records/{project.project_id}.jsonl"
        resource = _project_resource(root, project.records_path, expected_path)
        content = _read(resource, f"records {project.project_id}")
        records = derive_records(manifest.name, manifest.normalization_profile, graph_map[project.project_id])
        counts = dict(sorted(Counter(record.kind for record in records).items()))
        if (
            content != canonical_jsonl(records)
            or len(content) != project.records_byte_length
            or _sha256(content) != project.records_sha256
            or len(records) != project.record_count
            or counts != dict(project.record_counts)
        ):
            raise _error("CORPUS_ASSET_INVALID", "Packaged records do not match their graph.", project_id=project.project_id)
        result[project.project_id] = content
    return freeze(result)


def _load_packaged_spec(manifest: CorpusManifest):
    root = _corpus_root(manifest.name)
    content = _read(root.joinpath("source-spec.json"), "corpus source specification")
    spec = parse_corpus_spec(_json(content, "corpus source specification"))
    if (
        spec.name != manifest.name
        or spec.normalization_profile != manifest.normalization_profile
        or _sha256(content) != manifest.source_spec_sha256
        or content != canonical_json(spec.to_dict())
    ):
        raise _error("CORPUS_ASSET_INVALID", "Packaged source specification does not match its manifest.")
    return spec


def load_corpus_blueprints(manifest: CorpusManifest) -> tuple[Blueprint, ...]:
    """Load and graph-verify every no-mutation Blueprint for a corpus manifest."""

    spec = _load_packaged_spec(manifest)
    graph_map = {graph.project_id: graph for graph in load_packaged_corpus_graphs(manifest)}
    source_map = {source.project_id: source for source in spec.entry_points}
    root = resources.files("pscad_mcp").joinpath("assets", "blueprints")
    blueprints: list[Blueprint] = []
    for project in manifest.projects:
        name = f"{project.project_id}-existing-v1"
        content = _read(root.joinpath(name, "blueprint.json"), f"Blueprint {name}")
        value = _json(content, f"Blueprint {name}")
        blueprint = parse_blueprint(value)
        if content != canonical_json(blueprint.to_dict()) or blueprint.identity.name != name:
            raise _error("CORPUS_ASSET_INVALID", "Packaged Blueprint is noncanonical or misnamed.", project_id=project.project_id)
        verify_blueprint_candidate(value, graph_map[project.project_id], source_map[project.project_id])
        blueprints.append(blueprint)
    return tuple(blueprints)
