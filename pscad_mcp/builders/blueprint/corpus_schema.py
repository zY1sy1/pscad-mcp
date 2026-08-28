"""Strict parsing for repository-owned PSCAD corpus specifications."""

from __future__ import annotations

from pathlib import PurePath
import re
from typing import Any, Mapping

from ...core.backend.base import BackendError
from .corpus_models import CorpusDependency, CorpusSource, CorpusSpec


_SHA256 = re.compile(r"[0-9a-f]{64}")
_PORTABLE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
_DEPENDENCY_SUFFIXES = {".pscx", ".pslx", ".psmx"}


def _error(code: str, message: str, path: str) -> BackendError:
    return BackendError(code, message, "corpus", "parse_corpus_spec", {"path": path})


def _exact(value: Any, fields: set[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise _error("CORPUS_SPEC_INVALID", f"{path} must be an object.", path)
    if set(value) != fields:
        raise _error("CORPUS_SPEC_INVALID", f"{path} fields must be exact.", path)
    return value


def _portable_name(value: Any, path: str) -> str:
    if not isinstance(value, str) or _PORTABLE_NAME.fullmatch(value) is None:
        raise _error("CORPUS_SPEC_INVALID", f"{path} must be a portable name.", path)
    return value


def _basename(value: Any, path: str, suffixes: set[str]) -> str:
    if not isinstance(value, str) or not value or PurePath(value).name != value:
        raise _error("CORPUS_SPEC_INVALID", f"{path} must be a simple basename.", path)
    if "/" in value or "\\" in value or PurePath(value).suffix.lower() not in suffixes:
        raise _error("CORPUS_SPEC_INVALID", f"{path} has an unsupported suffix or path separator.", path)
    return value


def _positive_int(value: Any, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _error("CORPUS_SPEC_INVALID", f"{path} must be a positive integer.", path)
    return value


def _sha256(value: Any, path: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise _error("CORPUS_SPEC_INVALID", f"{path} must be a lowercase SHA-256 digest.", path)
    return value


def _versions(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise _error("CORPUS_SPEC_INVALID", f"{path} must be a non-empty array.", path)
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise _error("CORPUS_SPEC_INVALID", f"{path} values must be non-empty strings.", path)
    if len(set(value)) != len(value):
        raise _error("CORPUS_SPEC_INVALID", f"{path} values must be unique.", path)
    return tuple(value)


def _dependency(value: Any, index: int, source_index: int) -> CorpusDependency:
    path = f"corpus_spec.entry_points[{source_index}].dependencies[{index}]"
    record = _exact(value, {"basename", "byte_length", "sha256", "kind"}, path)
    if record["kind"] != "file":
        raise _error("CORPUS_SPEC_INVALID", f"{path}.kind must be file.", f"{path}.kind")
    return CorpusDependency(
        basename=_basename(record["basename"], f"{path}.basename", _DEPENDENCY_SUFFIXES),
        byte_length=_positive_int(record["byte_length"], f"{path}.byte_length"),
        sha256=_sha256(record["sha256"], f"{path}.sha256"),
        kind="file",
    )


def _source(value: Any, index: int) -> CorpusSource:
    path = f"corpus_spec.entry_points[{index}]"
    record = _exact(
        value,
        {"project_id", "basename", "byte_length", "sha256", "pscad_versions", "dependencies"},
        path,
    )
    dependency_values = record["dependencies"]
    if not isinstance(dependency_values, list):
        raise _error("CORPUS_SPEC_INVALID", f"{path}.dependencies must be an array.", f"{path}.dependencies")
    dependencies = tuple(_dependency(item, dependency_index, index) for dependency_index, item in enumerate(dependency_values))
    dependency_names = [item.basename for item in dependencies]
    if len(set(dependency_names)) != len(dependency_names):
        raise _error("CORPUS_SPEC_INVALID", f"{path}.dependencies basenames must be unique.", f"{path}.dependencies")
    return CorpusSource(
        project_id=_portable_name(record["project_id"], f"{path}.project_id"),
        basename=_basename(record["basename"], f"{path}.basename", {".pscx"}),
        byte_length=_positive_int(record["byte_length"], f"{path}.byte_length"),
        sha256=_sha256(record["sha256"], f"{path}.sha256"),
        pscad_versions=_versions(record["pscad_versions"], f"{path}.pscad_versions"),
        dependencies=dependencies,
    )


def parse_corpus_spec(value: Any) -> CorpusSpec:
    """Parse schema version 1 and reject non-portable or ambiguous fields."""

    record = _exact(
        value,
        {"schema_version", "normalization_profile", "name", "inclusion_policy", "exclusion_policy", "entry_points"},
        "corpus_spec",
    )
    version = record["schema_version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _error("CORPUS_SPEC_INVALID", "schema_version must be a positive integer.", "corpus_spec.schema_version")
    if version != 1:
        raise _error("CORPUS_SPEC_UNSUPPORTED", "Only corpus schema version 1 is supported.", "corpus_spec.schema_version")
    entry_values = record["entry_points"]
    if not isinstance(entry_values, list) or not entry_values:
        raise _error("CORPUS_SPEC_INVALID", "entry_points must be a non-empty array.", "corpus_spec.entry_points")
    entries = tuple(_source(item, index) for index, item in enumerate(entry_values))
    project_ids = [item.project_id for item in entries]
    basenames = [item.basename for item in entries]
    if len(set(project_ids)) != len(project_ids) or len(set(basenames)) != len(basenames):
        raise _error("CORPUS_SPEC_INVALID", "Entry-point project IDs and basenames must be unique.", "corpus_spec.entry_points")
    return CorpusSpec(
        schema_version=1,
        normalization_profile=_portable_name(record["normalization_profile"], "corpus_spec.normalization_profile"),
        name=_portable_name(record["name"], "corpus_spec.name"),
        inclusion_policy=_portable_name(record["inclusion_policy"], "corpus_spec.inclusion_policy"),
        exclusion_policy=_portable_name(record["exclusion_policy"], "corpus_spec.exclusion_policy"),
        entry_points=entries,
    )
