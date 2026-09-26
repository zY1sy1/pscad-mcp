"""Generate and verify deterministic PSCAD Blueprint corpus proposals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

# Keep direct ``python scripts/build_blueprint_corpus.py`` invocation working.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pscad_mcp.builders.blueprint.corpus_extractor import extract_project
from pscad_mcp.builders.blueprint.corpus_models import (
    CorpusDefinitionSource,
    CorpusSpec,
    ProjectGraph,
)
from pscad_mcp.builders.blueprint.corpus_relations import build_relationship_truth
from pscad_mcp.builders.blueprint.corpus_schema import parse_corpus_spec
from pscad_mcp.builders.blueprint.corpus_verifier import (
    generate_blueprint_candidate,
    verify_blueprint_candidate,
)
from pscad_mcp.builders.blueprint.corpus_writer import (
    canonical_json,
    validate_candidate,
    write_corpus_candidate,
)
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.definition_metadata import parse_definition_metadata_source

_MAX_SPEC_BYTES = 1024 * 1024
_PORTABLE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")


def _error(code: str, message: str) -> BackendError:
    return BackendError(code, message, "corpus", "build_blueprint_corpus")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Build deterministic PSCAD Blueprint corpus proposals.")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("generate", "verify", "compare", "preflight"):
        command = commands.add_parser(name)
        command.add_argument("--source-root", type=Path, required=True)
        command.add_argument("--spec", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--definition-source", action="append", default=[])
    proposal = commands.add_parser("propose-spec")
    proposal.add_argument("--source-root", type=Path, required=True)
    proposal.add_argument("--spec", type=Path, required=True)
    proposal.add_argument("--proposal", type=Path, required=True)
    proposal.add_argument("--definition-source", action="append", default=[])
    return root


def _load_spec(path: Path) -> CorpusSpec:
    if path.is_symlink() or not path.is_file():
        raise _error("CORPUS_SPEC_INVALID", "Corpus specification must be a regular file.")
    try:
        content = path.read_bytes()
        if len(content) > _MAX_SPEC_BYTES:
            raise _error("CORPUS_SPEC_INVALID", "Corpus specification exceeds the size limit.")
        value = json.loads(content.decode("utf-8"), parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise _error("CORPUS_SPEC_INVALID", "Corpus specification is not strict UTF-8 JSON.") from error
    return parse_corpus_spec(value)


def _blueprint_output(output: Path) -> Path:
    return output.with_name(f"{output.name}-blueprints")


def _verification_blueprint_output(output: Path) -> tuple[Path, bool]:
    if output.parent.name.casefold() == "corpora" and output.parent.parent.name.casefold() == "assets":
        return output.parent.parent / "blueprints", True
    return _blueprint_output(output), False


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _resolve_boundaries(
    source_root: Path,
    output: Path,
    *,
    packaged_blueprints: bool = False,
) -> tuple[Path, Path, Path, bool]:
    try:
        source = source_root.resolve(strict=True)
        destination = output.resolve(strict=False)
        if packaged_blueprints:
            blueprints, shared_blueprint_root = _verification_blueprint_output(destination)
        else:
            blueprints = _blueprint_output(destination)
            shared_blueprint_root = False
    except OSError as error:
        raise _error("CORPUS_OUTPUT_UNSAFE", "Corpus paths could not be resolved safely.") from error
    if not source.is_dir() or any(_paths_overlap(source, path) for path in (destination, blueprints)):
        raise _error("CORPUS_OUTPUT_UNSAFE", "Corpus output must not overlap the source root.")
    for path in (destination, blueprints):
        if path.is_symlink():
            raise _error("CORPUS_OUTPUT_UNSAFE", "Corpus output directories cannot be symbolic links.")
    return source, destination, blueprints, shared_blueprint_root


def _definition_bindings(values: Sequence[str]) -> dict[tuple[str, str], Path]:
    result = {}
    for value in values:
        identity, separator, raw_path = value.partition("=")
        namespace, marker, version = identity.partition("@")
        key = (namespace, version)
        path = Path(raw_path)
        if (
            not separator
            or not marker
            or identity.count("@") != 1
            or not namespace
            or not version
            or _PORTABLE_NAME.fullmatch(namespace) is None
            or not path.is_absolute()
            or key in result
        ):
            raise _error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition-source binding is invalid.",
            )
        result[key] = path
    return result


def _extract_graphs(
    source_root: Path,
    spec: CorpusSpec,
    definition_bindings: Mapping[tuple[str, str], Path] | None = None,
) -> tuple[ProjectGraph, ...]:
    bindings = dict(definition_bindings or {})
    raw = tuple(
        extract_project(
            source_root,
            source,
            schema_version=spec.schema_version,
            normalization_profile=spec.normalization_profile,
        )
        for source in spec.entry_points
    )
    if spec.schema_version == 1:
        if bindings:
            raise _error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Schema-v1 generation does not accept definition sources.",
            )
        return raw
    return tuple(
        build_relationship_truth(graph, spec, bindings).graph for graph in raw
    )


def _required_definition_binding_keys(
    source_root: Path,
    spec: CorpusSpec,
    graphs: Sequence[ProjectGraph],
) -> set[tuple[str, str]]:
    required: set[tuple[str, str]] = set()
    for source, graph in zip(spec.entry_points, graphs, strict=True):
        path = source_root / source.basename
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise _error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition references could not be observed.",
            ) from error
        if (
            len(payload) != source.byte_length
            or hashlib.sha256(payload).hexdigest() != source.sha256
        ):
            raise _error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition references changed while being observed.",
            )
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as error:
            raise _error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition references are not valid XML.",
            ) from error
        for reference in root.findall("./definitions/Definition/references/using"):
            namespace = reference.get("namespace") or ""
            if _PORTABLE_NAME.fullmatch(namespace) is None:
                raise _error(
                    "CORPUS_DEFINITION_SOURCE_MISMATCH",
                    "Definition reference namespace is invalid.",
                )
            required.add((namespace, graph.pscad_version))
    return required


def _expected_blueprint_names(spec: CorpusSpec) -> tuple[str, ...]:
    return tuple(
        f"{source.project_id}-existing-v{spec.schema_version}"
        for source in spec.entry_points
    )


def _summary_schema_version(spec: CorpusSpec) -> dict[str, int]:
    return {"schema_version": 2} if spec.schema_version == 2 else {}


def _write_blueprint_candidates(
    directory: Path,
    spec: CorpusSpec,
    graphs: Sequence[ProjectGraph],
) -> tuple[str, ...]:
    graph_map = {graph.project_id: graph for graph in graphs}
    if len(graph_map) != len(graphs) or set(graph_map) != {source.project_id for source in spec.entry_points}:
        raise _error("CORPUS_BLUEPRINT_MISMATCH", "Blueprint graphs do not match the corpus specification.")
    directory.mkdir(parents=True)
    names: list[str] = []
    for source in spec.entry_points:
        graph = graph_map[source.project_id]
        value = generate_blueprint_candidate(source, graph)
        verification = verify_blueprint_candidate(value, graph, source)
        blueprint_directory = directory / verification.blueprint_name
        blueprint_directory.mkdir()
        (blueprint_directory / "blueprint.json").write_bytes(canonical_json(value))
        names.append(verification.blueprint_name)
    _validate_blueprint_candidates(directory, spec, graphs)
    return tuple(names)


def _validate_blueprint_candidates(
    directory: Path,
    spec: CorpusSpec,
    graphs: Sequence[ProjectGraph],
    *,
    allow_extra: bool = False,
) -> tuple[str, ...]:
    if directory.is_symlink() or not directory.is_dir():
        raise _error("CORPUS_BLUEPRINT_MISMATCH", "Blueprint candidate root is invalid.")
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise _error("CORPUS_BLUEPRINT_MISMATCH", "Blueprint candidates cannot contain links.")
    names = _expected_blueprint_names(spec)
    expected_files = {f"{name}/blueprint.json" for name in names}
    observed_files = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    }
    if (allow_extra and not expected_files.issubset(observed_files)) or (not allow_extra and observed_files != expected_files):
        raise _error("CORPUS_BLUEPRINT_MISMATCH", "Blueprint candidate file set is incomplete or unexpected.")
    graph_map = {graph.project_id: graph for graph in graphs}
    for source, name in zip(spec.entry_points, names):
        path = directory / name / "blueprint.json"
        try:
            content = path.read_bytes()
            value = json.loads(content.decode("ascii"), parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise _error("CORPUS_BLUEPRINT_MISMATCH", "Blueprint candidate is not strict ASCII JSON.") from error
        verify_blueprint_candidate(value, graph_map[source.project_id], source)
        if content != canonical_json(value):
            raise _error("CORPUS_BLUEPRINT_MISMATCH", "Blueprint candidate is not canonical JSON.")
    return names


def _tree_bytes(directory: Path) -> dict[str, bytes]:
    if directory.is_symlink() or not directory.is_dir():
        raise _error("CORPUS_COMPARE_DIFFERENT", "Compared artifact root is invalid.")
    result: dict[str, bytes] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise _error("CORPUS_COMPARE_DIFFERENT", "Compared artifact tree contains links.")
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = path.read_bytes()
    return result


def _selected_blueprint_bytes(directory: Path, names: Sequence[str]) -> dict[str, bytes]:
    if directory.is_symlink() or not directory.is_dir():
        raise _error("CORPUS_COMPARE_DIFFERENT", "Compared Blueprint root is invalid.")
    result: dict[str, bytes] = {}
    for name in names:
        relative = f"{name}/blueprint.json"
        path = directory / name / "blueprint.json"
        if path.is_symlink() or not path.is_file():
            raise _error("CORPUS_COMPARE_DIFFERENT", "Compared Blueprint candidate is missing or linked.")
        result[relative] = path.read_bytes()
    return result


def _make_empty_sibling(destination: Path, label: str) -> Path:
    path = Path(tempfile.mkdtemp(prefix=f".{destination.name}-{label}-", dir=destination.parent))
    path.rmdir()
    return path


def _promote_bundle(staged: Sequence[tuple[Path, Path]]) -> None:
    backups: dict[Path, Path] = {}
    promoted: list[tuple[Path, Path]] = []
    try:
        for _, destination in staged:
            if destination.exists():
                backup = _make_empty_sibling(destination, "backup")
                destination.replace(backup)
                backups[destination] = backup
        for candidate, destination in staged:
            candidate.replace(destination)
            promoted.append((candidate, destination))
    except Exception:
        for candidate, destination in reversed(promoted):
            if destination.exists() and not candidate.exists():
                destination.replace(candidate)
        for destination, backup in backups.items():
            if backup.exists() and not destination.exists():
                backup.replace(destination)
        raise
    for destination, backup in backups.items():
        if backup.parent == destination.parent and backup.name.startswith(f".{destination.name}-backup-"):
            shutil.rmtree(backup)


def _build_staged_bundle(
    staging_root: Path,
    spec: CorpusSpec,
    graphs: Sequence[ProjectGraph],
) -> tuple[Path, Path, tuple[str, ...]]:
    corpus = staging_root / "corpus"
    blueprints = staging_root / "blueprints"
    write_corpus_candidate(spec, graphs, corpus)
    names = _write_blueprint_candidates(blueprints, spec, graphs)
    validate_candidate(corpus, spec)
    _validate_blueprint_candidates(blueprints, spec, graphs)
    return corpus, blueprints, names


def _temporary_bundle_root(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f".{destination.name}-bundle-", dir=destination.parent))


def _remove_bundle_root(path: Path, destination: Path) -> None:
    if (
        path.exists()
        and path.parent.resolve() == destination.parent.resolve()
        and path.name.startswith(f".{destination.name}-bundle-")
    ):
        shutil.rmtree(path)


def generate_corpus(
    source_root: Path,
    spec: CorpusSpec,
    output: Path,
    definition_bindings: Mapping[tuple[str, str], Path] | None = None,
) -> dict[str, Any]:
    source, destination, blueprint_destination, _ = _resolve_boundaries(source_root, output)
    graphs = _extract_graphs(source, spec, definition_bindings)
    staging_root = _temporary_bundle_root(destination)
    try:
        corpus, blueprints, names = _build_staged_bundle(staging_root, spec, graphs)
        _promote_bundle(((corpus, destination), (blueprints, blueprint_destination)))
    finally:
        _remove_bundle_root(staging_root, destination)
    return {
        "command": "generate",
        "status": "generated",
        "corpus": spec.name,
        **_summary_schema_version(spec),
        "projects": [graph.project_id for graph in graphs],
        "blueprints": list(names),
    }


def verify_corpus(
    source_root: Path,
    spec: CorpusSpec,
    output: Path,
    definition_bindings: Mapping[tuple[str, str], Path] | None = None,
) -> dict[str, Any]:
    source, destination, blueprint_destination, shared_blueprint_root = _resolve_boundaries(
        source_root,
        output,
        packaged_blueprints=True,
    )
    graphs = _extract_graphs(source, spec, definition_bindings)
    validate_candidate(destination, spec)
    for graph in graphs:
        graph_path = destination / "graphs" / f"{graph.project_id}.json"
        if graph_path.read_bytes() != canonical_json(graph.to_dict()):
            raise _error("CORPUS_MANIFEST_INVALID", "Committed graph differs from fresh extraction.")
    names = _validate_blueprint_candidates(
        blueprint_destination,
        spec,
        graphs,
        allow_extra=shared_blueprint_root,
    )
    return {
        "command": "verify",
        "status": "verified",
        "corpus": spec.name,
        **_summary_schema_version(spec),
        "projects": [graph.project_id for graph in graphs],
        "blueprints": list(names),
    }


def compare_corpus(
    source_root: Path,
    spec: CorpusSpec,
    output: Path,
    definition_bindings: Mapping[tuple[str, str], Path] | None = None,
) -> tuple[dict[str, Any], bool]:
    source, destination, blueprint_destination, _ = _resolve_boundaries(
        source_root,
        output,
        packaged_blueprints=True,
    )
    graphs = _extract_graphs(source, spec, definition_bindings)
    staging_root = _temporary_bundle_root(destination)
    try:
        corpus, blueprints, names = _build_staged_bundle(staging_root, spec, graphs)
        identical = (
            _tree_bytes(corpus) == _tree_bytes(destination)
            and _selected_blueprint_bytes(blueprints, names)
            == _selected_blueprint_bytes(blueprint_destination, names)
        )
    except BackendError as error:
        if error.code != "CORPUS_COMPARE_DIFFERENT":
            raise
        identical = False
        names = _expected_blueprint_names(spec)
    finally:
        _remove_bundle_root(staging_root, destination)
    return (
        {
            "command": "compare",
            "status": "identical" if identical else "different",
            "corpus": spec.name,
            **_summary_schema_version(spec),
            "projects": [graph.project_id for graph in graphs],
            "blueprints": list(names),
        },
        identical,
    )


def preflight_corpus(
    source_root: Path,
    spec: CorpusSpec,
    output: Path,
    definition_bindings: Mapping[tuple[str, str], Path] | None = None,
) -> dict[str, Any]:
    source, _destination, _blueprints, _ = _resolve_boundaries(source_root, output)
    graphs = _extract_graphs(source, spec, definition_bindings)
    blocking = [
        item
        for graph in graphs
        for item in graph.unresolved_evidence
        if item.classification == "blocking"
    ]
    if blocking:
        raise _error(
            "CORPUS_RELATION_INCOMPLETE",
            "Corpus relationship preflight found blocking evidence.",
        )
    return {
        "command": "preflight",
        "status": "verified",
        "corpus": spec.name,
        "schema_version": spec.schema_version,
        "projects": [
            {
                "project_id": graph.project_id,
                "definitions": len(graph.definition_classifications),
                "component_occurrences": len(graph.component_occurrences),
                "instance_ports": len(graph.instance_ports),
                "confirmed_nets": len(graph.confirmed_nets),
                "memberships": len(graph.port_net_memberships),
                "confirmed_relation_signature": graph.confirmed_relation_signature,
                "definition_catalog_signature": graph.definition_catalog_signature,
            }
            for graph in graphs
        ],
    }


def propose_spec(
    source_root: Path,
    spec: CorpusSpec,
    proposal: Path,
    definition_bindings: Mapping[tuple[str, str], Path],
) -> dict[str, Any]:
    if spec.schema_version != 1 or not definition_bindings:
        raise _error(
            "CORPUS_SPEC_INVALID",
            "A schema-v1 specification and definition sources are required.",
        )
    try:
        source = source_root.resolve(strict=True)
        destination = proposal.resolve(strict=False)
    except OSError as error:
        raise _error(
            "CORPUS_OUTPUT_UNSAFE",
            "Proposal paths could not be resolved safely.",
        ) from error
    if (
        not source.is_dir()
        or _paths_overlap(source, destination)
        or proposal.exists()
        or proposal.is_symlink()
    ):
        raise _error(
            "CORPUS_OUTPUT_UNSAFE",
            "The proposal destination is unsafe or already exists.",
        )

    raw_graphs = _extract_graphs(source, spec)
    if set(definition_bindings) != _required_definition_binding_keys(
        source,
        spec,
        raw_graphs,
    ):
        raise _error(
            "CORPUS_DEFINITION_SOURCE_MISMATCH",
            "Definition-source bindings do not cover the observed references.",
        )

    definition_sources = []
    for (namespace, version), raw_path in sorted(definition_bindings.items()):
        if (
            not raw_path.is_absolute()
            or raw_path.is_symlink()
            or not raw_path.is_file()
        ):
            raise _error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition source is missing or unsafe.",
            )
        payload = raw_path.read_bytes()
        try:
            parsed = parse_definition_metadata_source(payload)
        except (ET.ParseError, TypeError, ValueError) as error:
            raise _error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition source is invalid.",
            ) from error
        if parsed.version != version:
            raise _error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition source PSCAD version does not match its binding.",
            )
        definition_sources.append(
            CorpusDefinitionSource(
                namespace=namespace,
                basename=raw_path.name,
                byte_length=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                pscad_versions=(version,),
                policy="ports-and-classification-v1",
            )
        )
    candidate = replace(
        spec,
        schema_version=2,
        normalization_profile="pscad-xml-v2",
        definition_sources=tuple(definition_sources),
    )
    serialized = canonical_json(candidate.to_dict())
    parse_corpus_spec(json.loads(serialized.decode("ascii")))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(serialized)
    return {
        "command": "propose-spec",
        "status": "proposed",
        "corpus": candidate.name,
        "schema_version": 2,
        "definition_sources": len(candidate.definition_sources),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        spec = _load_spec(args.spec)
        bindings = _definition_bindings(args.definition_source)
        if args.command == "generate":
            summary = generate_corpus(
                args.source_root,
                spec,
                args.output,
                bindings,
            )
            exit_code = 0
        elif args.command == "verify":
            summary = verify_corpus(
                args.source_root,
                spec,
                args.output,
                bindings,
            )
            exit_code = 0
        elif args.command == "compare":
            summary, identical = compare_corpus(
                args.source_root,
                spec,
                args.output,
                bindings,
            )
            exit_code = 0 if identical else 1
        elif args.command == "preflight":
            summary = preflight_corpus(
                args.source_root,
                spec,
                args.output,
                bindings,
            )
            exit_code = 0
        else:
            summary = propose_spec(
                args.source_root,
                spec,
                args.proposal,
                bindings,
            )
            exit_code = 0
    except BackendError as error:
        summary = {"code": error.code, "status": "failed"}
        exit_code = 1
    except (OSError, TypeError, ValueError):
        summary = {"code": "CORPUS_CLI_FAILED", "status": "failed"}
        exit_code = 1
    print(json.dumps(summary, sort_keys=True, ensure_ascii=True, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
