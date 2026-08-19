"""Immutable dataclass record helpers shared by HVDC builders."""

from __future__ import annotations

import copy
from dataclasses import asdict
from typing import Any

from .serialization import json_safe


class _FrozenDict(dict[str, Any]):
    """A deepcopy-compatible mapping used inside frozen records."""

    def __setitem__(self, key: str, value: Any) -> None:
        raise TypeError("Builder record mappings are immutable")

    def __delitem__(self, key: str) -> None:
        raise TypeError("Builder record mappings are immutable")

    def clear(self) -> None:
        raise TypeError("Builder record mappings are immutable")

    def pop(self, key: str, default: Any = None) -> Any:
        raise TypeError("Builder record mappings are immutable")

    def popitem(self) -> tuple[str, Any]:
        raise TypeError("Builder record mappings are immutable")

    def setdefault(self, key: str, default: Any = None) -> Any:
        raise TypeError("Builder record mappings are immutable")

    def update(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("Builder record mappings are immutable")

    def __ior__(self, other: Any) -> "_FrozenDict":
        raise TypeError("Builder record mappings are immutable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "_FrozenDict":
        copied = _FrozenDict()
        memo[id(self)] = copied
        for key, value in self.items():
            dict.__setitem__(copied, copy.deepcopy(key, memo), copy.deepcopy(value, memo))
        return copied


def freeze(value: Any) -> Any:
    if isinstance(value, _FrozenDict):
        return value
    if isinstance(value, dict):
        frozen = _FrozenDict()
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Builder record mapping keys must be strings")
            dict.__setitem__(frozen, key, freeze(item))
        return frozen
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze(item) for item in value)
    return value


class JsonRecord:
    """Base class for frozen dataclasses with JSON-safe ``to_dict`` output."""

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))


_JsonRecord = JsonRecord
_freeze = freeze
_json_safe = json_safe

__all__ = ["JsonRecord", "freeze"]
