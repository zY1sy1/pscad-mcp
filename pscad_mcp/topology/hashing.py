from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import ProjectTopology


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def topology_sha256(topology: ProjectTopology) -> str:
    return canonical_sha256(_normalized_topology_payload(topology.confirmed_payload()))


def _normalized_topology_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for collection in (
        "canvases",
        "components",
        "conductors",
        "labels",
        "boundary_links",
        "nets",
    ):
        normalized[collection] = sorted(
            (_normalized_record(item) for item in normalized[collection]),
            key=lambda item: item["key"],
        )
    normalized["conflicts"] = sorted(
        (_normalized_record(item) for item in normalized["conflicts"]),
        key=lambda item: (item["object_key"], item["field"]),
    )
    normalized["unresolved"] = sorted(normalized["unresolved"])
    return normalized


def _normalized_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    if "ports" in normalized:
        normalized["ports"] = sorted(normalized["ports"], key=lambda port: port["key"])
    if "parameters" in normalized:
        normalized["parameters"] = sorted(
            normalized["parameters"],
            key=lambda pair: (pair[0], _stable_json(pair[1])),
        )
    for member_keys in ("port_keys", "conductor_keys", "label_keys"):
        if member_keys in normalized:
            normalized[member_keys] = sorted(normalized[member_keys])
    if "junctions" in normalized:
        normalized["junctions"] = sorted(
            normalized["junctions"],
            key=_stable_json,
        )
    return normalized


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
