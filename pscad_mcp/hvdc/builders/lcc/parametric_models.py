"""Immutable request and report records for parametric LCC modeling."""

from __future__ import annotations

import copy
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from ....core.backend.base import BackendError


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
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
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
    if isinstance(value, BackendError):
        return value.to_dict()
    raise TypeError(f"LCC record contains a non-JSON value: {type(value).__name__}")


class _FrozenDict(dict[str, Any]):
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


class _JsonRecord:
    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


def _require_number(value: Any, context: str, *, positive: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{context} must be a number")
    if not math.isfinite(float(value)):
        raise TypeError(f"{context} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{context} must be positive")
    return value


def _require_text(value: Any, context: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{context} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{context} must not be empty")
    return result


def _require_text_tuple(value: Any, context: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{context} must be a sequence of strings")
    return tuple(_require_text(item, context) for item in value)


@dataclass(frozen=True)
class LccRatings(_JsonRecord):
    rated_power_mw: float
    dc_voltage_kv: float
    dc_current_ka: float
    ac_voltage_kv: float
    frequency_hz: float
    scr: float
    escr: float | None = None

    def __post_init__(self) -> None:
        for field_name in ("rated_power_mw", "dc_voltage_kv", "dc_current_ka", "ac_voltage_kv", "frequency_hz", "scr"):
            value = getattr(self, field_name)
            _require_number(value, f"{type(self).__name__}.{field_name}", positive=True)
        if self.escr is not None:
            _require_number(self.escr, f"{type(self).__name__}.escr", positive=True)


@dataclass(frozen=True)
class LccParameterOverride(_JsonRecord):
    name: str
    value: Any
    units: str | None = None
    source: str = "user"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_text(self.name, f"{type(self).__name__}.name"))
        if self.units is not None:
            object.__setattr__(self, "units", _require_text(self.units, f"{type(self).__name__}.units"))
        if self.source is not None:
            object.__setattr__(self, "source", _require_text(self.source, f"{type(self).__name__}.source"))
        object.__setattr__(self, "value", _freeze(self.value))


@dataclass(frozen=True)
class LccModeEvent(_JsonRecord):
    event_id: str
    time_s: float
    target: str
    value: Any

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _require_text(self.event_id, f"{type(self).__name__}.event_id"))
        object.__setattr__(self, "target", _require_text(self.target, f"{type(self).__name__}.target"))
        _require_number(self.time_s, f"{type(self).__name__}.time_s")
        if self.time_s < 0:
            raise ValueError(f"{type(self).__name__}.time_s must be non-negative")
        object.__setattr__(self, "value", _freeze(self.value))


@dataclass(frozen=True)
class LccModeRequest(_JsonRecord):
    mode: str
    events: tuple[LccModeEvent, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _require_text(self.mode, f"{type(self).__name__}.mode"))
        events = self.events
        if isinstance(events, (str, bytes, bytearray)) or not isinstance(events, Sequence):
            raise TypeError(f"{type(self).__name__}.events must be a sequence of LccModeEvent")
        if not isinstance(events, tuple):
            events = tuple(
                item if isinstance(item, LccModeEvent) else LccModeEvent(**item)
                for item in events
            )
        previous_time: float | None = None
        for event in events:
            if not isinstance(event, LccModeEvent):
                event = LccModeEvent(**event)
            if previous_time is not None and event.time_s <= previous_time:
                raise ValueError(f"{type(self).__name__}.events must be strictly increasing")
            previous_time = event.time_s
        object.__setattr__(self, "events", events)


@dataclass(frozen=True)
class DerivedParameter(_JsonRecord):
    name: str
    value: Any
    source: str
    formula: str
    units: str | None = None
    constraints: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    asset: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_text(self.name, f"{type(self).__name__}.name"))
        object.__setattr__(self, "source", _require_text(self.source, f"{type(self).__name__}.source"))
        object.__setattr__(self, "formula", _require_text(self.formula, f"{type(self).__name__}.formula"))
        if self.units is not None:
            object.__setattr__(self, "units", _require_text(self.units, f"{type(self).__name__}.units"))
        object.__setattr__(self, "constraints", _freeze(self.constraints))
        object.__setattr__(self, "warnings", _freeze(self.warnings))
        object.__setattr__(self, "value", _freeze(self.value))
        if self.asset is not None:
            object.__setattr__(self, "asset", _require_text(self.asset, f"{type(self).__name__}.asset"))


@dataclass(frozen=True)
class DerivedParameterReport(_JsonRecord):
    parameters: tuple[DerivedParameter, ...]
    feasible: bool = True
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", tuple(self.parameters))
        if not isinstance(self.feasible, bool):
            raise TypeError(f"{type(self).__name__}.feasible must be a boolean")
        object.__setattr__(self, "diagnostics", _freeze(self.diagnostics))


@dataclass(frozen=True)
class LccTemplateMapping(_JsonRecord):
    role: str
    definition: str
    ports: tuple[str, ...] = ()
    parameters: tuple[str, ...] = ()
    confidence: float = 1.0
    source: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _require_text(self.role, f"{type(self).__name__}.role"))
        object.__setattr__(self, "definition", _require_text(self.definition, f"{type(self).__name__}.definition"))
        object.__setattr__(self, "ports", _require_text_tuple(self.ports, f"{type(self).__name__}.ports"))
        object.__setattr__(self, "parameters", _require_text_tuple(self.parameters, f"{type(self).__name__}.parameters"))
        _require_number(self.confidence, f"{type(self).__name__}.confidence")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"{type(self).__name__}.confidence must be between 0 and 1")
        if self.source is not None:
            object.__setattr__(self, "source", _require_text(self.source, f"{type(self).__name__}.source"))


@dataclass(frozen=True)
class ParametricLccRequest(_JsonRecord):
    topology: str
    ratings: LccRatings | Mapping[str, Any]
    engineering_overrides: dict[str, Any] = field(default_factory=dict)
    operation_modes: tuple[str, ...] = ()
    mode_requests: tuple[LccModeRequest, ...] = ()
    template_mappings: tuple[LccTemplateMapping, ...] = ()
    return_path_assets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "topology", _require_text(self.topology, f"{type(self).__name__}.topology"))
        if isinstance(self.ratings, Mapping):
            object.__setattr__(self, "ratings", LccRatings(**self.ratings))
        if not isinstance(self.ratings, LccRatings):
            raise TypeError(f"{type(self).__name__}.ratings must be LccRatings")
        object.__setattr__(self, "engineering_overrides", _freeze(self.engineering_overrides))
        object.__setattr__(self, "operation_modes", _require_text_tuple(self.operation_modes, f"{type(self).__name__}.operation_modes"))
        object.__setattr__(self, "return_path_assets", _require_text_tuple(self.return_path_assets, f"{type(self).__name__}.return_path_assets"))
        if isinstance(self.mode_requests, (str, bytes, bytearray)) or not isinstance(self.mode_requests, Sequence):
            raise TypeError(f"{type(self).__name__}.mode_requests must be a sequence")
        parsed_requests: list[LccModeRequest] = []
        for request in self.mode_requests:
            parsed_requests.append(request if isinstance(request, LccModeRequest) else LccModeRequest(**request))
        object.__setattr__(self, "mode_requests", tuple(parsed_requests))
        if isinstance(self.template_mappings, (str, bytes, bytearray)) or not isinstance(self.template_mappings, Sequence):
            raise TypeError(f"{type(self).__name__}.template_mappings must be a sequence")
        parsed_mappings: list[LccTemplateMapping] = []
        for mapping in self.template_mappings:
            parsed_mappings.append(mapping if isinstance(mapping, LccTemplateMapping) else LccTemplateMapping(**mapping))
        object.__setattr__(self, "template_mappings", tuple(parsed_mappings))
