"""Immutable, JSON-safe records shared by the LCC builder stages."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class _FrozenDict(dict[str, Any]):
    """A deepcopy-compatible mapping used inside frozen records."""

    def __setitem__(self, key: str, value: Any) -> None:
        raise TypeError("LCC record mappings are immutable")

    def __delitem__(self, key: str) -> None:
        raise TypeError("LCC record mappings are immutable")

    def clear(self) -> None:
        raise TypeError("LCC record mappings are immutable")

    def pop(self, key: str, default: Any = None) -> Any:
        raise TypeError("LCC record mappings are immutable")

    def popitem(self) -> tuple[str, Any]:
        raise TypeError("LCC record mappings are immutable")

    def setdefault(self, key: str, default: Any = None) -> Any:
        raise TypeError("LCC record mappings are immutable")

    def update(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("LCC record mappings are immutable")

    def __ior__(self, other: Any) -> "_FrozenDict":
        raise TypeError("LCC record mappings are immutable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "_FrozenDict":
        copied = _FrozenDict()
        memo[id(self)] = copied
        for key, value in self.items():
            dict.__setitem__(copied, copy.deepcopy(key, memo), copy.deepcopy(value, memo))
        return copied


def _freeze(value: Any) -> Any:
    if isinstance(value, _FrozenDict):
        return value
    if isinstance(value, dict):
        frozen = _FrozenDict()
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("LCC record mapping keys must be strings")
            dict.__setitem__(frozen, key, _freeze(item))
        return frozen
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _json_safe(value: Any) -> Any:
    """Normalize nested records and enums without retaining runtime objects."""

    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise TypeError("LCC records cannot contain non-finite floats")
        return value
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("LCC record mapping keys must be strings")
            result[key] = _json_safe(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise TypeError(f"LCC record contains a non-JSON value: {type(value).__name__}")


class _JsonRecord:
    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class LccBuildState(str, Enum):
    VALIDATED = "validated"
    STAGING_CREATED = "staging_created"
    COMPONENTS_PLACED = "components_placed"
    PARAMETERS_VERIFIED = "parameters_verified"
    CONNECTIONS_VERIFIED = "connections_verified"
    STRUCTURE_VERIFIED = "structure_verified"
    STAGING_SAVED = "staging_saved"
    COMPILED = "compiled"
    SIMULATED = "simulated"
    ACCEPTANCE_PASSED = "acceptance_passed"
    PUBLISHED = "published"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class LccEndpoint(_JsonRecord):
    component: str
    port: str
    kind: str | None = None


@dataclass(frozen=True)
class LccRoute(_JsonRecord):
    vertices: tuple[tuple[int, int], ...]
    policy: str | None = None


@dataclass(frozen=True)
class LccNetSpec(_JsonRecord):
    logical_id: str
    kind: str
    endpoints: tuple[LccEndpoint, ...]
    route: LccRoute | None = None
    label: str | None = None


@dataclass(frozen=True)
class LccComponentSpec(_JsonRecord):
    logical_id: str
    definition: str
    location: tuple[int, int]
    orientation: int = 0
    parameters: dict[str, Any] = field(default_factory=dict)
    ports: tuple[str, ...] = ()
    port_contracts: tuple[dict[str, Any], ...] = ()
    canvas: str = "Main"
    bounding_box: tuple[int, int, int, int] | None = None
    role: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        object.__setattr__(self, "port_contracts", _freeze(self.port_contracts))


@dataclass(frozen=True)
class LccOutputSpec(_JsonRecord):
    logical_id: str
    path: str
    units: str
    role: str
    call_id: int | None = None
    location: str | None = None
    measurement: str | None = None


@dataclass(frozen=True)
class LccBlueprint(_JsonRecord):
    schema_version: int
    name: str
    topology: str
    poles: int
    terminals: int
    settings: dict[str, Any]
    components: tuple[LccComponentSpec, ...]
    nets: tuple[LccNetSpec, ...]
    outputs: tuple[LccOutputSpec, ...]
    canvases: tuple[dict[str, Any], ...] = ()
    measurements: tuple[dict[str, Any], ...] = ()
    structural_assertions: tuple[dict[str, Any], ...] = ()
    profile: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", _freeze(self.settings))
        object.__setattr__(self, "canvases", _freeze(self.canvases))
        object.__setattr__(self, "measurements", _freeze(self.measurements))
        object.__setattr__(self, "structural_assertions", _freeze(self.structural_assertions))


@dataclass(frozen=True)
class LccPlanOperation(_JsonRecord):
    sequence: int
    kind: str
    target: str
    arguments: dict[str, Any] = field(default_factory=dict)
    operation_id: str | None = None
    phase: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", _freeze(self.arguments))


@dataclass(frozen=True)
class LccAcceptanceCheck(_JsonRecord):
    name: str
    kind: str
    required: bool
    expected: dict[str, Any]
    units: str | None = None
    comparison_window: tuple[float, float] | None = None
    severity: str | None = None
    rationale: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected", _freeze(self.expected))


@dataclass(frozen=True)
class LccBuildPlan(_JsonRecord):
    blueprint: LccBlueprint
    operations: tuple[LccPlanOperation, ...]
    plan_hash: str
    acceptance_checks: tuple[LccAcceptanceCheck, ...] = ()
    target_path: str | None = None
    staging_path: str | None = None
    asset_hashes: dict[str, str] = field(default_factory=dict)
    pscad_version: str | None = None
    catalog_identity: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_hashes", _freeze(self.asset_hashes))
        object.__setattr__(self, "metadata", _freeze(self.metadata))


@dataclass(frozen=True)
class LccBuildRecord(_JsonRecord):
    build_id: str
    state: LccBuildState
    plan: LccBuildPlan | None = None
    history: tuple[dict[str, Any], ...] = ()
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    workspace: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "history", _freeze(self.history))
        object.__setattr__(self, "error", _freeze(self.error))
        object.__setattr__(self, "result", _freeze(self.result))
