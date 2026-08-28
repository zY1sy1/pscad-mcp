"""Canonical corpus records, manifests, validation, and candidate promotion."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

from ...core.backend.base import BackendError
from .corpus_extractor import graph_signature
from .corpus_models import (
    CorpusCanvas,
    CorpusComponent,
    CorpusConnection,
    CorpusDefinition,
    CorpusManifest,
    CorpusOutputChannel,
    CorpusProjectManifest,
    CorpusRecord,
    CorpusSpec,
    CorpusWarning,
    DefinitionParameter,
    DefinitionPort,
    ProjectGraph,
)
from .corpus_schema import parse_corpus_spec
from .models import freeze, json_safe


KIND_ORDER = {
    "project": 0,
    "definition": 1,
    "component": 2,
    "parameter": 3,
    "port": 4,
    "connection": 5,
    "project_setting": 6,
    "output_channel": 7,
}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)")
_DENIED_FIELDS = {
    "absolute_path",
    "build_time",
    "credentials",
    "creator",
    "environment",
    "generated_at",
    "host",
    "hostname",
    "output_filename",
    "recent_file",
    "revisor",
    "snapshot_filename",
    "source_path",
    "startup_filename",
}


def _error(message: str, *, path: str | None = None, **details: Any) -> BackendError:
    payload = dict(details)
    if path is not None:
        payload["path"] = path
    return BackendError("CORPUS_MANIFEST_INVALID", message, "corpus", "validate_candidate", payload)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: Any) -> bytes:
    """Serialize finite JSON as stable ASCII bytes with one trailing newline."""

    return (
        json.dumps(
            json_safe(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def canonical_jsonl(records: Iterable[CorpusRecord]) -> bytes:
    ordered = sorted(records, key=lambda record: (KIND_ORDER[record.kind], record.record_key))
    return b"".join(canonical_json(record.to_dict()) for record in ordered)


def _key_part(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold().replace("_", "-")
    normalized = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE)
    return re.sub(r"-+", "-", normalized).strip("-.") or "unnamed"


def _unique_key_parts(names: Iterable[str]) -> dict[str, str]:
    values = tuple(names)
    if len(set(values)) != len(values):
        raise _error("Record owner contains duplicate parameter names.")
    bases = {name: _key_part(name) for name in values}
    counts = Counter(bases.values())
    result = {
        name: (
            base
            if counts[base] == 1
            else f"{base}-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:16]}"
        )
        for name, base in bases.items()
    }
    if len(set(result.values())) != len(result):
        raise _error("Derived parameter key parts are not unique.")
    return result


def _record(
    corpus_name: str,
    normalization_profile: str,
    graph: ProjectGraph,
    kind: str,
    record_key: str,
    payload: Mapping[str, Any],
    resolved: bool,
) -> CorpusRecord:
    return CorpusRecord(
        schema_version=1,
        normalization_profile=normalization_profile,
        corpus_name=corpus_name,
        project_id=graph.project_id,
        source_sha256=graph.source_sha256,
        kind=kind,
        record_key=record_key,
        payload=freeze(payload),
        resolved=resolved,
        verification_status="offline_extracted" if resolved else "unresolved",
    )


def derive_records(corpus_name: str, normalization_profile: str, graph: ProjectGraph) -> tuple[CorpusRecord, ...]:
    """Derive every training record from the normalized graph, never from source XML."""

    records: list[CorpusRecord] = []
    project_resolved = not any(warning.blocking for warning in graph.warnings)
    records.append(
        _record(
            corpus_name,
            normalization_profile,
            graph,
            "project",
            f"project:{graph.project_id}",
            {
                "name": graph.name,
                "pscad_version": graph.pscad_version,
                "target": graph.target,
                "dependency_hashes": json_safe(graph.dependency_hashes),
                "settings": json_safe(graph.settings),
                "canvases": [canvas.to_dict() for canvas in graph.canvases],
                "warnings": [warning.to_dict() for warning in graph.warnings],
            },
            project_resolved,
        )
    )
    for definition in graph.definitions:
        records.append(
            _record(corpus_name, normalization_profile, graph, "definition", definition.key, definition.to_dict(), True)
        )
        parameter_parts = _unique_key_parts(parameter.name for parameter in definition.parameters)
        for parameter in definition.parameters:
            records.append(
                _record(
                    corpus_name,
                    normalization_profile,
                    graph,
                    "parameter",
                    f"{definition.key}/parameter:{parameter_parts[parameter.name]}",
                    {"owner_kind": "definition", "owner_key": definition.key, **parameter.to_dict()},
                    True,
                )
            )
        for port in definition.ports:
            records.append(
                _record(
                    corpus_name,
                    normalization_profile,
                    graph,
                    "port",
                    port.key,
                    {"definition_key": definition.key, **port.to_dict()},
                    True,
                )
            )
    for component in graph.components:
        records.append(
            _record(corpus_name, normalization_profile, graph, "component", component.key, component.to_dict(), component.resolved)
        )
        parameter_parts = _unique_key_parts(component.parameters)
        for name, value in component.parameters.items():
            records.append(
                _record(
                    corpus_name,
                    normalization_profile,
                    graph,
                    "parameter",
                    f"{component.key}/parameter:{parameter_parts[name]}",
                    {"owner_kind": "component", "owner_key": component.key, "name": name, "value": value},
                    component.resolved,
                )
            )
    for connection in graph.connections:
        resolved = connection.resolution in {"explicit", "geometry_only"}
        records.append(
            _record(corpus_name, normalization_profile, graph, "connection", connection.key, connection.to_dict(), resolved)
        )
    setting_parts = _unique_key_parts(graph.settings)
    for name, value in graph.settings.items():
        records.append(
            _record(
                corpus_name,
                normalization_profile,
                graph,
                "project_setting",
                f"project:{graph.project_id}/setting:{setting_parts[name]}",
                {"name": name, "value": value},
                True,
            )
        )
    for channel in graph.output_channels:
        records.append(
            _record(
                corpus_name,
                normalization_profile,
                graph,
                "output_channel",
                channel.key,
                channel.to_dict(),
                channel.resolved,
            )
        )
    records.sort(key=lambda record: (KIND_ORDER[record.kind], record.record_key))
    keys = [(record.kind, record.record_key) for record in records]
    if len(set(keys)) != len(keys):
        raise _error("Derived record keys are not unique.")
    return tuple(records)


def _scan_privacy(value: Any, path: str = "artifact") -> None:
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error("Artifact contains a non-finite number.", path=path)
        return
    if isinstance(value, str):
        if _ABSOLUTE_PATH.search(value):
            raise _error("Artifact contains an absolute path.", path=path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_privacy(item, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _error("Artifact mapping keys must be strings.", path=path)
            if key.casefold() in _DENIED_FIELDS:
                raise _error("Artifact contains a denied field.", path=f"{path}.{key}")
            _scan_privacy(item, f"{path}.{key}")
        return
    raise _error("Artifact contains a non-JSON value.", path=path)


def _exact(value: Any, required: set[str], path: str, optional: set[str] | None = None) -> Mapping[str, Any]:
    allowed = required | (optional or set())
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise _error("Artifact object is invalid.", path=path)
    if not required.issubset(value) or not set(value).issubset(allowed):
        raise _error("Artifact fields are not exact.", path=path)
    return value


def _string(value: Any, path: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value):
        raise _error("Artifact field must be a string.", path=path)
    return value


def _optional_string(value: Any, path: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise _error("Artifact field must be a string or null.", path=path)
    return value


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise _error("Artifact field must be an integer.", path=path)
    return value


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise _error("Artifact field must be boolean.", path=path)
    return value


def _digest(value: Any, path: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise _error("Artifact field must be a SHA-256 digest.", path=path)
    return value


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise _error("Artifact field must be an object.", path=path)
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise _error("Artifact field must be an array.", path=path)
    return value


def _point(value: Any, path: str) -> tuple[int, int]:
    items = _array(value, path)
    if len(items) != 2:
        raise _error("Artifact point must contain two integers.", path=path)
    return (_integer(items[0], f"{path}[0]", minimum=-2**63), _integer(items[1], f"{path}[1]", minimum=-2**63))


def _parse_graph(value: Any) -> ProjectGraph:
    record = _exact(
        value,
        {
            "project_id", "source_sha256", "dependency_hashes", "name", "pscad_version", "target", "settings",
            "definitions", "canvases", "components", "connections", "output_channels", "warnings",
        },
        "graph",
    )
    definitions: list[CorpusDefinition] = []
    for index, item in enumerate(_array(record["definitions"], "graph.definitions")):
        path = f"graph.definitions[{index}]"
        parsed = _exact(item, {"key", "name", "class_id", "parameters", "ports", "canvas_key"}, path)
        parameters: list[DefinitionParameter] = []
        for parameter_index, parameter in enumerate(_array(parsed["parameters"], f"{path}.parameters")):
            parameter_path = f"{path}.parameters[{parameter_index}]"
            parameter_value = _exact(
                parameter,
                {"name", "type", "dimension", "units", "minimum", "maximum", "intent"},
                parameter_path,
                {"default"},
            )
            parameters.append(
                DefinitionParameter(
                    _string(parameter_value["name"], f"{parameter_path}.name"),
                    _string(parameter_value["type"], f"{parameter_path}.type", empty=True),
                    _string(parameter_value["dimension"], f"{parameter_path}.dimension"),
                    _string(parameter_value["units"], f"{parameter_path}.units", empty=True),
                    _optional_string(parameter_value["minimum"], f"{parameter_path}.minimum"),
                    _optional_string(parameter_value["maximum"], f"{parameter_path}.maximum"),
                    _string(parameter_value["intent"], f"{parameter_path}.intent", empty=True),
                    _optional_string(parameter_value.get("default"), f"{parameter_path}.default"),
                )
            )
        ports: list[DefinitionPort] = []
        for port_index, port in enumerate(_array(parsed["ports"], f"{path}.ports")):
            port_path = f"{path}.ports[{port_index}]"
            port_value = _exact(port, {"key", "name", "model", "dimension", "mode", "type", "offset"}, port_path)
            ports.append(
                DefinitionPort(
                    _string(port_value["key"], f"{port_path}.key"),
                    _string(port_value["name"], f"{port_path}.name"),
                    _string(port_value["model"], f"{port_path}.model", empty=True),
                    _string(port_value["dimension"], f"{port_path}.dimension"),
                    _string(port_value["mode"], f"{port_path}.mode", empty=True),
                    _string(port_value["type"], f"{port_path}.type", empty=True),
                    _point(port_value["offset"], f"{port_path}.offset"),
                )
            )
        canvas_key = parsed["canvas_key"]
        if canvas_key is not None:
            canvas_key = _string(canvas_key, f"{path}.canvas_key")
        definitions.append(
            CorpusDefinition(
                _string(parsed["key"], f"{path}.key"),
                _string(parsed["name"], f"{path}.name"),
                _string(parsed["class_id"], f"{path}.class_id", empty=True),
                tuple(parameters),
                tuple(ports),
                canvas_key,
            )
        )
    canvases: list[CorpusCanvas] = []
    for index, item in enumerate(_array(record["canvases"], "graph.canvases")):
        path = f"graph.canvases[{index}]"
        parsed = _exact(item, {"key", "name", "owner_definition", "class_id"}, path)
        canvases.append(
            CorpusCanvas(
                _string(parsed["key"], f"{path}.key"),
                _string(parsed["name"], f"{path}.name"),
                _string(parsed["owner_definition"], f"{path}.owner_definition"),
                _string(parsed["class_id"], f"{path}.class_id", empty=True),
            )
        )
    components: list[CorpusComponent] = []
    for index, item in enumerate(_array(record["components"], "graph.components")):
        path = f"graph.components[{index}]"
        parsed = _exact(
            item,
            {"key", "canvas_key", "definition_key", "name", "location", "orientation", "parameters", "resolved"},
            path,
        )
        components.append(
            CorpusComponent(
                _string(parsed["key"], f"{path}.key"),
                _string(parsed["canvas_key"], f"{path}.canvas_key"),
                _string(parsed["definition_key"], f"{path}.definition_key"),
                _string(parsed["name"], f"{path}.name"),
                _point(parsed["location"], f"{path}.location"),
                _integer(parsed["orientation"], f"{path}.orientation"),
                freeze(_mapping(parsed["parameters"], f"{path}.parameters")),
                _boolean(parsed["resolved"], f"{path}.resolved"),
            )
        )
    connections: list[CorpusConnection] = []
    for index, item in enumerate(_array(record["connections"], "graph.connections")):
        path = f"graph.connections[{index}]"
        parsed = _exact(
            item,
            {"key", "canvas_key", "kind", "vertices", "endpoints", "source_definition", "resolution"},
            path,
        )
        canvas_key = parsed["canvas_key"]
        if canvas_key is not None:
            canvas_key = _string(canvas_key, f"{path}.canvas_key")
        connections.append(
            CorpusConnection(
                _string(parsed["key"], f"{path}.key"),
                canvas_key,
                _string(parsed["kind"], f"{path}.kind"),
                tuple(_point(vertex, f"{path}.vertices") for vertex in _array(parsed["vertices"], f"{path}.vertices")),
                tuple(_string(endpoint, f"{path}.endpoints") for endpoint in _array(parsed["endpoints"], f"{path}.endpoints")),
                _optional_string(parsed["source_definition"], f"{path}.source_definition"),
                _string(parsed["resolution"], f"{path}.resolution"),
            )
        )
    output_channels: list[CorpusOutputChannel] = []
    for index, item in enumerate(_array(record["output_channels"], "graph.output_channels")):
        path = f"graph.output_channels[{index}]"
        parsed = _exact(
            item,
            {"key", "name", "label", "dimension", "units", "minimum", "maximum", "source_component", "source_port", "resolved"},
            path,
        )
        output_channels.append(
            CorpusOutputChannel(
                _string(parsed["key"], f"{path}.key"),
                _string(parsed["name"], f"{path}.name"),
                _string(parsed["label"], f"{path}.label", empty=True),
                _string(parsed["dimension"], f"{path}.dimension"),
                _string(parsed["units"], f"{path}.units", empty=True),
                _optional_string(parsed["minimum"], f"{path}.minimum"),
                _optional_string(parsed["maximum"], f"{path}.maximum"),
                _optional_string(parsed["source_component"], f"{path}.source_component"),
                _string(parsed["source_port"], f"{path}.source_port", empty=True),
                _boolean(parsed["resolved"], f"{path}.resolved"),
            )
        )
    warnings: list[CorpusWarning] = []
    for index, item in enumerate(_array(record["warnings"], "graph.warnings")):
        path = f"graph.warnings[{index}]"
        parsed = _exact(item, {"kind", "path", "count", "blocking"}, path)
        warnings.append(
            CorpusWarning(
                _string(parsed["kind"], f"{path}.kind"),
                _string(parsed["path"], f"{path}.path"),
                _integer(parsed["count"], f"{path}.count", minimum=1),
                _boolean(parsed["blocking"], f"{path}.blocking"),
            )
        )
    return ProjectGraph(
        project_id=_string(record["project_id"], "graph.project_id"),
        source_sha256=_digest(record["source_sha256"], "graph.source_sha256"),
        dependency_hashes=freeze(_mapping(record["dependency_hashes"], "graph.dependency_hashes")),
        name=_string(record["name"], "graph.name"),
        pscad_version=_string(record["pscad_version"], "graph.pscad_version"),
        target=_string(record["target"], "graph.target"),
        settings=freeze(_mapping(record["settings"], "graph.settings")),
        definitions=tuple(definitions),
        canvases=tuple(canvases),
        components=tuple(components),
        connections=tuple(connections),
        output_channels=tuple(output_channels),
        warnings=tuple(warnings),
    )


def parse_project_graph(value: Any) -> ProjectGraph:
    """Strictly reparse a committed normalized project graph."""

    return _parse_graph(value)


def _parse_record(value: Any) -> CorpusRecord:
    parsed = _exact(
        value,
        {
            "schema_version", "normalization_profile", "corpus_name", "project_id", "source_sha256", "kind",
            "record_key", "payload", "resolved", "verification_status",
        },
        "record",
    )
    if parsed["schema_version"] != 1 or parsed["kind"] not in KIND_ORDER:
        raise _error("Record schema or kind is unsupported.", path="record")
    return CorpusRecord(
        1,
        _string(parsed["normalization_profile"], "record.normalization_profile"),
        _string(parsed["corpus_name"], "record.corpus_name"),
        _string(parsed["project_id"], "record.project_id"),
        _digest(parsed["source_sha256"], "record.source_sha256"),
        _string(parsed["kind"], "record.kind"),
        _string(parsed["record_key"], "record.record_key"),
        freeze(_mapping(parsed["payload"], "record.payload")),
        _boolean(parsed["resolved"], "record.resolved"),
        _string(parsed["verification_status"], "record.verification_status"),
    )


def parse_corpus_record(value: Any) -> CorpusRecord:
    """Strictly reparse one committed corpus record."""

    return _parse_record(value)


def _parse_manifest(value: Any) -> CorpusManifest:
    parsed = _exact(
        value,
        {"schema_version", "normalization_profile", "name", "source_spec_sha256", "project_count", "projects"},
        "manifest",
    )
    if parsed["schema_version"] != 1:
        raise _error("Manifest schema version is unsupported.", path="manifest.schema_version")
    projects: list[CorpusProjectManifest] = []
    for index, item in enumerate(_array(parsed["projects"], "manifest.projects")):
        path = f"manifest.projects[{index}]"
        project = _exact(
            item,
            {
                "project_id", "source_sha256", "graph_path", "graph_sha256", "graph_byte_length", "graph_signature",
                "records_path", "records_sha256", "records_byte_length", "record_count", "record_counts",
            },
            path,
        )
        projects.append(
            CorpusProjectManifest(
                _string(project["project_id"], f"{path}.project_id"),
                _digest(project["source_sha256"], f"{path}.source_sha256"),
                _string(project["graph_path"], f"{path}.graph_path"),
                _digest(project["graph_sha256"], f"{path}.graph_sha256"),
                _integer(project["graph_byte_length"], f"{path}.graph_byte_length", minimum=1),
                _digest(project["graph_signature"], f"{path}.graph_signature"),
                _string(project["records_path"], f"{path}.records_path"),
                _digest(project["records_sha256"], f"{path}.records_sha256"),
                _integer(project["records_byte_length"], f"{path}.records_byte_length", minimum=1),
                _integer(project["record_count"], f"{path}.record_count", minimum=1),
                freeze(_mapping(project["record_counts"], f"{path}.record_counts")),
            )
        )
    return CorpusManifest(
        1,
        _string(parsed["normalization_profile"], "manifest.normalization_profile"),
        _string(parsed["name"], "manifest.name"),
        _digest(parsed["source_spec_sha256"], "manifest.source_spec_sha256"),
        _integer(parsed["project_count"], "manifest.project_count", minimum=1),
        tuple(projects),
    )


def parse_corpus_manifest(value: Any) -> CorpusManifest:
    """Strictly reparse a committed corpus manifest."""

    return _parse_manifest(value)


def _load_json(path: Path) -> tuple[Any, bytes]:
    try:
        content = path.read_bytes()
        value = json.loads(content.decode("ascii"), parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise _error("Artifact is not strict ASCII JSON.", path=path.name) from error
    return value, content


def _relative_file(root: Path, relative: str) -> Path:
    candidate_path = PurePosixPath(relative)
    if candidate_path.is_absolute() or ".." in candidate_path.parts:
        raise _error("Manifest artifact path is unsafe.", path=relative)
    candidate = root.joinpath(*candidate_path.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise _error("Manifest artifact is missing or linked.", path=relative)
    return candidate


def validate_candidate(root: str | Path, spec: CorpusSpec) -> CorpusManifest:
    """Reparse and cross-check a complete proposed corpus directory."""

    directory = Path(root)
    if directory.is_symlink() or not directory.is_dir():
        raise _error("Corpus candidate must be a regular directory.")
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise _error("Corpus candidate cannot contain links.", path=path.relative_to(directory).as_posix())
    expected_files = {"source-spec.json", "manifest.json"}
    for source in spec.entry_points:
        expected_files.add(f"graphs/{source.project_id}.json")
        expected_files.add(f"records/{source.project_id}.jsonl")
    observed_files = {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()}
    if observed_files != expected_files:
        raise _error("Corpus candidate file set does not match its specification.")

    source_value, source_bytes = _load_json(directory / "source-spec.json")
    _scan_privacy(source_value, "source_spec")
    parsed_spec = parse_corpus_spec(source_value)
    if parsed_spec != spec or source_bytes != canonical_json(spec.to_dict()):
        raise _error("Corpus source specification drifted.", path="source-spec.json")

    manifest_value, manifest_bytes = _load_json(directory / "manifest.json")
    _scan_privacy(manifest_value, "manifest")
    manifest = _parse_manifest(manifest_value)
    if manifest_bytes != canonical_json(manifest.to_dict()):
        raise _error("Manifest is not canonical.", path="manifest.json")
    if (
        manifest.name != spec.name
        or manifest.normalization_profile != spec.normalization_profile
        or manifest.source_spec_sha256 != _sha256(source_bytes)
        or manifest.project_count != len(spec.entry_points)
        or len(manifest.projects) != manifest.project_count
    ):
        raise _error("Manifest identity or project count does not match the source specification.")
    manifest_projects = {project.project_id: project for project in manifest.projects}
    if set(manifest_projects) != {source.project_id for source in spec.entry_points}:
        raise _error("Manifest project identities do not match the source specification.")

    for source in spec.entry_points:
        project = manifest_projects[source.project_id]
        if project.source_sha256 != source.sha256:
            raise _error("Manifest source hash does not match the source specification.", path=source.project_id)
        graph_path = _relative_file(directory, project.graph_path)
        graph_value, graph_bytes = _load_json(graph_path)
        _scan_privacy(graph_value, f"graph.{source.project_id}")
        graph = _parse_graph(graph_value)
        if graph_bytes != canonical_json(graph.to_dict()):
            raise _error("Project graph is not canonical.", path=project.graph_path)
        if (
            graph.project_id != source.project_id
            or graph.source_sha256 != source.sha256
            or _sha256(graph_bytes) != project.graph_sha256
            or len(graph_bytes) != project.graph_byte_length
            or graph_signature(graph) != project.graph_signature
        ):
            raise _error("Project graph evidence does not match its manifest.", path=project.graph_path)

        records_path = _relative_file(directory, project.records_path)
        record_bytes = records_path.read_bytes()
        records: list[CorpusRecord] = []
        try:
            for line in record_bytes.splitlines(keepends=True):
                if not line.endswith(b"\n"):
                    raise ValueError("record line lacks newline")
                value = json.loads(line.decode("ascii"), parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)))
                _scan_privacy(value, f"records.{source.project_id}")
                record = _parse_record(value)
                if line != canonical_json(record.to_dict()):
                    raise ValueError("record line is not canonical")
                records.append(record)
        except (UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise _error("Record file is not canonical JSONL.", path=project.records_path) from error
        expected_records = derive_records(spec.name, spec.normalization_profile, graph)
        observed_counts = dict(sorted(Counter(record.kind for record in records).items()))
        if (
            canonical_jsonl(records) != record_bytes
            or record_bytes != canonical_jsonl(expected_records)
            or _sha256(record_bytes) != project.records_sha256
            or len(record_bytes) != project.records_byte_length
            or len(records) != project.record_count
            or observed_counts != dict(project.record_counts)
        ):
            raise _error("Record content, count, or hash does not match its graph and manifest.", path=project.records_path)
    return manifest


def _write_candidate_files(directory: Path, spec: CorpusSpec, graphs: Sequence[ProjectGraph]) -> CorpusManifest:
    expected_ids = [source.project_id for source in spec.entry_points]
    graph_map = {graph.project_id: graph for graph in graphs}
    if len(graph_map) != len(graphs) or set(graph_map) != set(expected_ids):
        raise _error("Graphs must match the source specification exactly.")
    directory.mkdir(parents=True)
    (directory / "graphs").mkdir()
    (directory / "records").mkdir()
    source_bytes = canonical_json(spec.to_dict())
    (directory / "source-spec.json").write_bytes(source_bytes)
    projects: list[CorpusProjectManifest] = []
    for source in spec.entry_points:
        graph = graph_map[source.project_id]
        if graph.source_sha256 != source.sha256:
            raise _error("Graph source hash does not match the source specification.", path=source.project_id)
        graph_relative = f"graphs/{source.project_id}.json"
        records_relative = f"records/{source.project_id}.jsonl"
        graph_bytes = canonical_json(graph.to_dict())
        records = derive_records(spec.name, spec.normalization_profile, graph)
        records_bytes = canonical_jsonl(records)
        directory.joinpath(*PurePosixPath(graph_relative).parts).write_bytes(graph_bytes)
        directory.joinpath(*PurePosixPath(records_relative).parts).write_bytes(records_bytes)
        projects.append(
            CorpusProjectManifest(
                project_id=source.project_id,
                source_sha256=source.sha256,
                graph_path=graph_relative,
                graph_sha256=_sha256(graph_bytes),
                graph_byte_length=len(graph_bytes),
                graph_signature=graph_signature(graph),
                records_path=records_relative,
                records_sha256=_sha256(records_bytes),
                records_byte_length=len(records_bytes),
                record_count=len(records),
                record_counts=freeze(dict(sorted(Counter(record.kind for record in records).items()))),
            )
        )
    manifest = CorpusManifest(
        schema_version=1,
        normalization_profile=spec.normalization_profile,
        name=spec.name,
        source_spec_sha256=_sha256(source_bytes),
        project_count=len(projects),
        projects=tuple(projects),
    )
    (directory / "manifest.json").write_bytes(canonical_json(manifest.to_dict()))
    return manifest


def _owned_sibling(path: Path, destination: Path) -> bool:
    try:
        return path.parent.resolve() == destination.parent.resolve() and path.name.startswith(f".{destination.name}-")
    except OSError:
        return False


def _remove_owned(path: Path, destination: Path) -> None:
    if not path.exists() or not _owned_sibling(path, destination):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _promote(candidate: Path, destination: Path) -> None:
    backup: Path | None = None
    if destination.exists():
        backup = Path(tempfile.mkdtemp(prefix=f".{destination.name}-backup-", dir=destination.parent))
        backup.rmdir()
        destination.replace(backup)
    try:
        candidate.replace(destination)
    except Exception:
        if backup is not None and backup.exists() and not destination.exists():
            backup.replace(destination)
        raise
    if backup is not None:
        _remove_owned(backup, destination)


def write_corpus_candidate(
    spec: CorpusSpec,
    graphs: Sequence[ProjectGraph],
    destination: str | Path,
) -> CorpusManifest:
    """Build, validate, and promote a complete sibling candidate directory."""

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(tempfile.mkdtemp(prefix=f".{target.name}-candidate-", dir=target.parent))
    try:
        candidate.rmdir()
        _write_candidate_files(candidate, spec, graphs)
        manifest = validate_candidate(candidate, spec)
        _promote(candidate, target)
        return manifest
    except Exception:
        _remove_owned(candidate, target)
        raise
