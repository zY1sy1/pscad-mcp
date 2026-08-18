"""Deterministic, JSON-safe evidence for HVDC scenario audits."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


def file_evidence(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    size = 0
    with resolved.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return {"path": str(resolved), "size": size, "sha256": digest.hexdigest(), "modified_ns": int(resolved.stat().st_mtime_ns)}


def profile_evidence(name: str, profile: Mapping[str, Any]) -> dict[str, Any]:
    payload = json.dumps(profile, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return {
        "name": name,
        "version": profile.get("profile_version", 1),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
