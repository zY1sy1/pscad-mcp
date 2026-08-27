"""Bounded, read-only extraction of admitted PSCAD project XML."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from ...core.backend.base import BackendError
from .corpus_models import CorpusDependency, CorpusSource, ProjectGraph
from .models import freeze


_ALLOWED_SETTINGS = {
    "time_duration",
    "time_step",
    "sample_step",
    "chatter_threshold",
    "branch_threshold",
    "StartType",
    "PlotType",
    "SnapType",
    "SnapTime",
    "MrunType",
    "Mruns",
    "Scenario",
    "Advanced",
    "Options",
    "Build",
    "Warn",
    "Check",
    "description",
}


@dataclass(frozen=True)
class ExtractionLimits:
    max_file_bytes: int = 8 * 1024 * 1024
    max_elements: int = 100_000
    max_text_chars: int = 4 * 1024 * 1024
    max_unknown_names: int = 128

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


def _error(code: str, message: str, project_id: str, **details: Any) -> BackendError:
    return BackendError(code, message, "corpus", "extract_project", {"project_id": project_id, **details})


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_child(root: Path, basename: str, project_id: str) -> Path:
    if not basename or Path(basename).name != basename or "/" in basename or "\\" in basename:
        raise _error("CORPUS_SOURCE_INVALID", "Admitted source name is not a simple basename.", project_id)
    candidate = root / basename
    if not candidate.exists():
        raise _error("CORPUS_SOURCE_MISSING", "An admitted source file is missing.", project_id, basename=basename)
    if candidate.is_symlink() or not candidate.is_file():
        raise _error("CORPUS_SOURCE_INVALID", "An admitted source must be a regular non-link file.", project_id, basename=basename)
    return candidate


def _verify_size(path: Path, expected: int, limits: ExtractionLimits, project_id: str, basename: str) -> None:
    observed = path.stat().st_size
    if observed > limits.max_file_bytes:
        raise _error(
            "CORPUS_SOURCE_TOO_LARGE",
            "An admitted source exceeds the extraction size limit.",
            project_id,
            basename=basename,
            byte_length=observed,
            max_file_bytes=limits.max_file_bytes,
        )
    if observed != expected:
        raise _error(
            "CORPUS_SOURCE_SIZE_MISMATCH",
            "An admitted source byte length does not match its specification.",
            project_id,
            basename=basename,
            expected_byte_length=expected,
            observed_byte_length=observed,
        )


def _verify_hash(path: Path, expected: str, project_id: str, basename: str) -> str:
    observed = sha256_file(path)
    if observed != expected:
        raise _error(
            "CORPUS_SOURCE_HASH_MISMATCH",
            "An admitted source hash does not match its specification.",
            project_id,
            basename=basename,
            expected_sha256=expected,
            observed_sha256=observed,
        )
    return observed


def _admit_file(
    root: Path,
    basename: str,
    byte_length: int,
    expected_hash: str,
    limits: ExtractionLimits,
    project_id: str,
) -> tuple[Path, str]:
    path = _regular_child(root, basename, project_id)
    _verify_size(path, byte_length, limits, project_id, basename)
    return path, _verify_hash(path, expected_hash, project_id, basename)


def _bounded_parse(content: bytes, limits: ExtractionLimits, project_id: str) -> ET.Element:
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise _error("CORPUS_XML_UNSAFE", "PSCAD corpus XML cannot contain DTD or entity declarations.", project_id)
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise _error("CORPUS_XML_MALFORMED", "PSCAD corpus XML is malformed.", project_id) from error
    elements = 0
    text_chars = 0
    for element in root.iter():
        elements += 1
        text_chars += len(element.text or "") + len(element.tail or "")
        if elements > limits.max_elements or text_chars > limits.max_text_chars:
            raise _error(
                "CORPUS_XML_TOO_COMPLEX",
                "PSCAD corpus XML exceeds configured complexity bounds.",
                project_id,
                elements=elements,
                text_chars=text_chars,
            )
    return root


def _project_settings(root: ET.Element) -> dict[str, str]:
    settings: dict[str, str] = {}
    for paramlist in root.findall("./paramlist"):
        if paramlist.get("name") != "Settings":
            continue
        for parameter in paramlist.findall("./param"):
            name = parameter.get("name")
            value = parameter.get("value")
            if name in _ALLOWED_SETTINGS and value is not None:
                settings[name] = value
    return dict(sorted(settings.items()))


def _dependency_values(source: CorpusSource) -> tuple[CorpusDependency, ...]:
    return tuple(sorted(source.dependencies, key=lambda dependency: dependency.basename))


def extract_project(
    source_root: str | Path,
    source: CorpusSource,
    limits: ExtractionLimits | None = None,
) -> ProjectGraph:
    """Extract a portable project header while proving admitted files did not change."""

    configured_limits = limits or ExtractionLimits()
    try:
        root_directory = Path(source_root).resolve(strict=True)
    except OSError as error:
        raise _error("CORPUS_SOURCE_MISSING", "The corpus source root is unavailable.", source.project_id) from error
    if not root_directory.is_dir():
        raise _error("CORPUS_SOURCE_INVALID", "The corpus source root must be a directory.", source.project_id)

    source_path, pre_hash = _admit_file(
        root_directory,
        source.basename,
        source.byte_length,
        source.sha256,
        configured_limits,
        source.project_id,
    )
    dependency_paths: list[tuple[CorpusDependency, Path]] = []
    dependency_hashes: dict[str, str] = {}
    for dependency in _dependency_values(source):
        dependency_path, dependency_hash = _admit_file(
            root_directory,
            dependency.basename,
            dependency.byte_length,
            dependency.sha256,
            configured_limits,
            source.project_id,
        )
        dependency_paths.append((dependency, dependency_path))
        dependency_hashes[dependency.basename] = dependency_hash

    content = source_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != pre_hash:
        raise _error("CORPUS_SOURCE_CHANGED", "Source changed while it was being read.", source.project_id)
    root = _bounded_parse(content, configured_limits, source.project_id)
    if root.tag != "project":
        raise _error("CORPUS_XML_UNSUPPORTED_ROOT", "PSCAD corpus XML root must be project.", source.project_id, root_tag=root.tag)
    name = root.get("name")
    pscad_version = root.get("version")
    target = root.get("Target")
    if not name or not pscad_version or not target:
        raise _error("CORPUS_XML_INVALID", "PSCAD project identity fields are incomplete.", source.project_id)
    if pscad_version not in source.pscad_versions:
        raise _error(
            "CORPUS_SOURCE_VERSION_MISMATCH",
            "Observed PSCAD version is not admitted by the source specification.",
            source.project_id,
            observed_version=pscad_version,
            expected_versions=list(source.pscad_versions),
        )

    post_hash = sha256_file(source_path)
    if post_hash != pre_hash or source_path.stat().st_size != source.byte_length:
        raise _error("CORPUS_SOURCE_CHANGED", "Source changed during extraction.", source.project_id)
    for dependency, dependency_path in dependency_paths:
        if sha256_file(dependency_path) != dependency.sha256 or dependency_path.stat().st_size != dependency.byte_length:
            raise _error(
                "CORPUS_SOURCE_CHANGED",
                "A dependency changed during extraction.",
                source.project_id,
                basename=dependency.basename,
            )

    return ProjectGraph(
        project_id=source.project_id,
        source_sha256=pre_hash,
        dependency_hashes=freeze(dependency_hashes),
        name=name,
        pscad_version=pscad_version,
        target=target,
        settings=freeze(_project_settings(root)),
    )
