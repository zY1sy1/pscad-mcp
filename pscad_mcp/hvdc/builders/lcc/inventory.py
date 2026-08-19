"""Canonical live PSCAD definition-inventory evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from ....core.backend.base import BackendError


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "lcc", "definition_inventory", details)


def _scalar(value: Any, field: str) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise _error(
        "INVALID_ARGUMENT",
        f"Definition inventory field '{field}' contains a non-JSON scalar.",
        field=field,
    )


def _canonical_value(value: Any, field: str) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item, f"{field}.{key}")
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_value(item, field) for item in value]
    return _scalar(value, field)


def _port_sort_key(port: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(port.get("name", "")),
        int(port.get("x", 0)),
        int(port.get("y", 0)),
        str(port.get("kind", "")),
        int(port.get("dimension", 0) or 0),
    )


def canonicalize_inventory(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Validate, sort, and hash a provider-backed definition snapshot."""

    if not isinstance(snapshot, Mapping):
        raise _error("INVALID_ARGUMENT", "Definition inventory must be an object.")
    source = snapshot.get("source")
    if source not in {"live", "packaged_catalog"}:
        raise _error(
            "INVALID_ARGUMENT",
            "Definition inventory source must be 'live' or 'packaged_catalog'.",
            source=source,
        )
    raw_definitions = snapshot.get("definitions")
    if not isinstance(raw_definitions, Sequence) or isinstance(
        raw_definitions, (str, bytes, bytearray)
    ):
        raise _error("INVALID_ARGUMENT", "definitions must be a list.")
    definitions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_definitions):
        if not isinstance(raw, Mapping):
            raise _error(
                "INVALID_ARGUMENT", f"definitions[{index}] must be an object."
            )
        scoped_name = raw.get("scoped_name")
        if not isinstance(scoped_name, str) or ":" not in scoped_name:
            raise _error(
                "INVALID_ARGUMENT",
                f"definitions[{index}].scoped_name must be library-qualified.",
            )
        if scoped_name in seen:
            raise _error(
                "INVALID_ARGUMENT",
                "Definition inventory contains a duplicate scoped name.",
                scoped_name=scoped_name,
            )
        seen.add(scoped_name)
        raw_ports = raw.get("ports", [])
        if not isinstance(raw_ports, Sequence) or isinstance(
            raw_ports, (str, bytes, bytearray)
        ) or any(not isinstance(port, Mapping) for port in raw_ports):
            raise _error(
                "INVALID_ARGUMENT", f"definitions[{index}].ports must be a list."
            )
        ports = [
            _canonical_value(dict(port), f"definitions[{index}].ports")
            for port in raw_ports
        ]
        ports.sort(key=_port_sort_key)
        parameters = _canonical_value(
            raw.get("parameters", {}), f"definitions[{index}].parameters"
        )
        bounding_box = _canonical_value(
            raw.get("bounding_box", {}), f"definitions[{index}].bounding_box"
        )
        definitions.append(
            {
                "scoped_name": scoped_name,
                "ports": ports,
                "parameters": parameters,
                "bounding_box": bounding_box,
            }
        )
    definitions.sort(key=lambda item: item["scoped_name"])
    canonical = {"source": source, "definitions": definitions}
    encoded = json.dumps(
        {"definitions": definitions},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return {**canonical, "sha256": hashlib.sha256(encoded).hexdigest()}


def require_live_inventory(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    normalized = canonicalize_inventory(snapshot)
    if normalized["source"] != "live":
        raise _error(
            "DEFINITION_INVENTORY_REQUIRED",
            "Acceptance requires a live PSCAD definition inventory; packaged catalog data is planning evidence only.",
            source=normalized["source"],
        )
    return normalized
