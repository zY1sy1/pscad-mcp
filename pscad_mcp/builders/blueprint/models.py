"""Immutable JSON-safe records for generic blueprint builds."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
import math
from typing import Any, Mapping


class FrozenDict(dict[str, Any]):
    """A deeply frozen dict that remains compatible with dataclass serialization."""

    @staticmethod
    def _immutable() -> None:
        raise TypeError("blueprint record mappings are immutable")

    __setitem__ = lambda self, key, value: self._immutable()
    __delitem__ = lambda self, key: self._immutable()
    clear = lambda self: self._immutable()
    pop = lambda self, key, default=None: self._immutable()
    popitem = lambda self: self._immutable()
    setdefault = lambda self, key, default=None: self._immutable()
    update = lambda self, *args, **kwargs: self._immutable()
    __ior__ = lambda self, other: self._immutable()

    def __deepcopy__(self, memo: dict[int, Any]) -> "FrozenDict":
        copied = FrozenDict()
        memo[id(self)] = copied
        for key, value in self.items():
            dict.__setitem__(copied, copy.deepcopy(key, memo), copy.deepcopy(value, memo))
        return copied


def freeze(value: Any) -> Any:
    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, Mapping):
        frozen = FrozenDict()
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("blueprint mapping keys must be strings")
            dict.__setitem__(frozen, key, freeze(item))
        return frozen
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("blueprint records cannot contain non-finite floats")
        return value
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    raise TypeError(f"blueprint record contains a non-JSON value: {type(value).__name__}")


class BlueprintBuildState(str, Enum):
    PLANNED = "planned"
    STAGING_CREATED = "staging_created"
    MUTATIONS_APPLIED = "mutations_applied"
    STRUCTURE_VERIFIED = "structure_verified"
    SAVED = "saved"
    RELOADED = "reloaded"
    PARAMETERS_VERIFIED = "parameters_verified"
    COMPILED = "compiled"
    SIMULATED = "simulated"
    ACCEPTANCE_PASSED = "acceptance_passed"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class BlueprintIdentity:
    schema_version: int
    name: str
    supported_pscad_versions: tuple[str, ...]
    inspection_profile: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "name": self.name,
            "supported_pscad_versions": list(self.supported_pscad_versions),
        }
        if self.inspection_profile is not None:
            result["inspection_profile"] = self.inspection_profile
        return result


@dataclass(frozen=True)
class BlueprintOperation:
    sequence: int
    kind: str
    target: str
    arguments: FrozenDict
    operation_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "target": self.target,
            "arguments": json_safe(self.arguments),
            "operation_id": self.operation_id,
        }


@dataclass(frozen=True)
class PublicationSpec:
    delivery_package: bool
    evidence_files: tuple[str, ...]
    scope: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "delivery_package": self.delivery_package,
            "evidence_files": list(self.evidence_files),
            "scope": self.scope,
        }


@dataclass(frozen=True)
class Blueprint:
    identity: BlueprintIdentity
    source_package: FrozenDict
    operations: tuple[BlueprintOperation, ...]
    acceptance: FrozenDict
    publication: PublicationSpec

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "source_package": json_safe(self.source_package),
            "operations": [operation.to_dict() for operation in self.operations],
            "acceptance": json_safe(self.acceptance),
            "publication": self.publication.to_dict(),
        }


@dataclass(frozen=True)
class BlueprintPlan:
    plan_hash: str
    blueprint: Blueprint
    blueprint_hash: str
    asset_hashes: FrozenDict
    source_path: str
    source_entry_point: str
    source_manifest: FrozenDict
    source_package_hash: str
    inventory_hash: str
    pscad_version: str
    target_name: str
    staging_path: str
    resolved_selectors: FrozenDict
    operations: tuple[BlueprintOperation, ...]
    warnings: tuple[str, ...]
    parameter_overrides: FrozenDict

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "blueprint": self.blueprint.to_dict(),
            "blueprint_hash": self.blueprint_hash,
            "asset_hashes": json_safe(self.asset_hashes),
            "source_path": self.source_path,
            "source_entry_point": self.source_entry_point,
            "source_manifest": json_safe(self.source_manifest),
            "source_package_hash": self.source_package_hash,
            "inventory_hash": self.inventory_hash,
            "pscad_version": self.pscad_version,
            "target_name": self.target_name,
            "staging_path": self.staging_path,
            "resolved_selectors": json_safe(self.resolved_selectors),
            "operations": [operation.to_dict() for operation in self.operations],
            "warnings": list(self.warnings),
            "parameter_overrides": json_safe(self.parameter_overrides),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"plan_hash": self.plan_hash, **self.unsigned_dict()}
