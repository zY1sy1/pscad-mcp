"""Finite JSON normalization and deterministic content serialization."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any


class SerializationError(TypeError):
    """A JSON value is not representable by the builder contracts."""

    def __init__(self, message: str, *, path: str | None = None, type_name: str | None = None, key_type: str | None = None) -> None:
        super().__init__(message)
        self.path = path
        self.type_name = type_name
        self.key_type = key_type


def json_safe(value: Any, path: str = "payload") -> Any:
    """Return a JSON-only copy and reject non-finite or runtime values."""

    if hasattr(value, "to_dict") and callable(value.to_dict):
        return json_safe(value.to_dict(), path)
    if isinstance(value, Enum):
        return json_safe(value.value, path)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SerializationError(f"{path} must be a finite number.", path=path)
        return value
    if isinstance(value, (Path, BaseException)):
        raise SerializationError(
            f"{path} is not JSON-safe: {type(value).__name__}",
            path=path,
            type_name=type(value).__name__,
        )
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise SerializationError(
                    f"{path} contains a non-string mapping key.",
                    path=path,
                    key_type=type(key).__name__,
                )
            result[key] = json_safe(item, f"{path}.{key}")
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [json_safe(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise SerializationError(
        f"{path} is not JSON-safe: {type(value).__name__}",
        path=path,
        type_name=type(value).__name__,
    )


def canonical_json(value: Any) -> bytes:
    """Serialize finite JSON with stable ASCII encoding and sorted keys."""

    normalized = json_safe(value)
    return json.dumps(
        normalized,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def content_hash(value: Any) -> str:
    """Return the SHA-256 digest of :func:`canonical_json`."""

    return hashlib.sha256(canonical_json(value)).hexdigest()


__all__ = ["SerializationError", "canonical_json", "content_hash", "json_safe"]
