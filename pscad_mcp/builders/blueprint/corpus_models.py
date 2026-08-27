"""Immutable records for deterministic PSCAD blueprint corpora."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CorpusDependency:
    basename: str
    byte_length: int
    sha256: str
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "basename": self.basename,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class CorpusSource:
    project_id: str
    basename: str
    byte_length: int
    sha256: str
    pscad_versions: tuple[str, ...]
    dependencies: tuple[CorpusDependency, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "basename": self.basename,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "pscad_versions": list(self.pscad_versions),
            "dependencies": [dependency.to_dict() for dependency in self.dependencies],
        }


@dataclass(frozen=True)
class CorpusSpec:
    schema_version: int
    normalization_profile: str
    name: str
    inclusion_policy: str
    exclusion_policy: str
    entry_points: tuple[CorpusSource, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "normalization_profile": self.normalization_profile,
            "name": self.name,
            "inclusion_policy": self.inclusion_policy,
            "exclusion_policy": self.exclusion_policy,
            "entry_points": [entry.to_dict() for entry in self.entry_points],
        }
