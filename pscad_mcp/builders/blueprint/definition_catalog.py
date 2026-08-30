"""Hash-bound definition metadata for offline corpus relationship extraction."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from xml.etree import ElementTree as ET

from ...core.backend.base import BackendError
from ...core.definition_metadata import (
    DefinitionMetadata,
    parse_definition_metadata_source,
)
from ...topology.hashing import canonical_sha256
from .corpus_models import CorpusDefinitionSource


def _catalog_error(
    code: str,
    message: str,
    namespace: str | None = None,
    version: str | None = None,
    definition: str | None = None,
) -> BackendError:
    details = {
        key: value
        for key, value in {
            "namespace": namespace,
            "pscad_version": version,
            "definition": definition,
        }.items()
        if value is not None
    }
    return BackendError(code, message, "corpus", "definition_catalog", details)


@dataclass(frozen=True)
class CatalogDefinition:
    namespace: str
    pscad_version: str
    physical_name: str
    source_sha256: str
    metadata: DefinitionMetadata


@dataclass(frozen=True)
class DefinitionCatalog:
    definitions: Mapping[tuple[str, str, str], tuple[CatalogDefinition, ...]]
    source_fingerprints: tuple[tuple[str, str, str], ...]
    source_read_counts: tuple[tuple[str, str, int], ...]
    catalog_signature: str
    _bindings: Mapping[tuple[str, str], Path] = field(compare=False, repr=False)
    _integrity_sources: tuple[tuple[Path, str], ...] = field(
        compare=False,
        repr=False,
    )

    def require(
        self,
        namespace: str,
        version: str,
        name: str,
    ) -> CatalogDefinition:
        matches = self.definitions.get((namespace, version, name), ())
        if not matches:
            raise _catalog_error(
                "CORPUS_DEFINITION_UNRESOLVED",
                "Exact definition is absent.",
                namespace,
                version,
                name,
            )
        if len(matches) != 1:
            raise _catalog_error(
                "CORPUS_DEFINITION_AMBIGUOUS",
                "Exact definition is duplicated.",
                namespace,
                version,
                name,
            )
        return matches[0]

    def verify_unchanged(self) -> None:
        for path, expected in self._integrity_sources:
            if path.is_symlink() or not path.is_file():
                raise _catalog_error(
                    "CORPUS_DEFINITION_SOURCE_MISMATCH",
                    "Definition source is no longer a regular file.",
                )
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as error:
                raise _catalog_error(
                    "CORPUS_DEFINITION_SOURCE_MISMATCH",
                    "Definition source is no longer readable.",
                ) from error
            if actual != expected:
                raise _catalog_error(
                    "CORPUS_DEFINITION_SOURCE_MISMATCH",
                    "Definition source changed during generation.",
                )


def load_definition_catalog(
    sources: Sequence[CorpusDefinitionSource],
    bindings: Mapping[tuple[str, str], Path],
) -> DefinitionCatalog:
    expected = {key for source in sources for key in source.keys}
    if set(bindings) != expected:
        raise _catalog_error(
            "CORPUS_DEFINITION_SOURCE_MISMATCH",
            "Definition-source bindings do not match the specification.",
        )

    definitions: dict[
        tuple[str, str, str],
        tuple[CatalogDefinition, ...],
    ] = {}
    fingerprints: list[tuple[str, str, str]] = []
    normalized_bindings: dict[tuple[str, str], Path] = {}
    integrity_sources: list[tuple[Path, str]] = []
    seen_sources: set[tuple[Path, str]] = set()

    for source in sources:
        raw_paths = {Path(bindings[key]) for key in source.keys}
        if len(raw_paths) != 1:
            raise _catalog_error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "One definition declaration must resolve to one file.",
                source.namespace,
            )
        raw_path = raw_paths.pop()
        if (
            not raw_path.is_absolute()
            or raw_path.is_symlink()
            or not raw_path.is_file()
            or raw_path.name != source.basename
        ):
            raise _catalog_error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition source is missing or unsafe.",
                source.namespace,
            )
        path = raw_path.resolve()
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise _catalog_error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition source is unreadable.",
                source.namespace,
            ) from error
        digest = hashlib.sha256(payload).hexdigest()
        if len(payload) != source.byte_length or digest != source.sha256:
            raise _catalog_error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition source does not match its admitted bytes.",
                source.namespace,
            )
        try:
            parsed = parse_definition_metadata_source(payload)
        except (ET.ParseError, TypeError, ValueError) as error:
            raise _catalog_error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition source is not valid metadata XML.",
                source.namespace,
            ) from error
        if parsed.version not in source.pscad_versions:
            raise _catalog_error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition source PSCAD version is not admitted.",
                source.namespace,
            )

        for namespace, version in source.keys:
            for name, matches in parsed.definitions.items():
                definitions[(namespace, version, name)] = tuple(
                    CatalogDefinition(
                        namespace,
                        version,
                        name,
                        digest,
                        metadata,
                    )
                    for metadata in matches
                )
            fingerprints.append((namespace, version, digest))
            normalized_bindings[(namespace, version)] = path

        identity = (raw_path, digest)
        if identity not in seen_sources:
            seen_sources.add(identity)
            integrity_sources.append(identity)

    sorted_fingerprints = tuple(sorted(fingerprints))
    return DefinitionCatalog(
        definitions=MappingProxyType(definitions),
        source_fingerprints=sorted_fingerprints,
        source_read_counts=tuple(
            (namespace, version, 1)
            for namespace, version in sorted(expected)
        ),
        catalog_signature=canonical_sha256(sorted_fingerprints),
        _bindings=MappingProxyType(normalized_bindings),
        _integrity_sources=tuple(integrity_sources),
    )
