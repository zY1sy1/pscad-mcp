"""Resolve raw PSCAD result-channel records to profile canonical names."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


def _key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _source_keys(source: str) -> set[str]:
    normalized = source.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    return {_key(source), *(_key(part) for part in parts)} - {""}


def resolve_result_channels(
    samples: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve list-record PSOUT channels using exact normalized profile evidence."""
    raw_channels = samples.get("channels")
    if not isinstance(raw_channels, list):
        return {
            "samples": dict(samples),
            "resolved_channels": [],
            "warnings": [],
        }

    aliases: dict[str, set[str]] = {}
    metadata: dict[str, Mapping[str, Any]] = {}
    for mapping in profile.get("mappings", []):
        if not isinstance(mapping, Mapping):
            continue
        canonical = mapping.get("canonical")
        if not isinstance(canonical, str) or not canonical:
            continue
        aliases[canonical] = {
            _key(canonical),
            *(
                _key(alias)
                for alias in mapping.get("aliases", [])
                if isinstance(alias, str)
            ),
        } - {""}
        metadata[canonical] = mapping

    candidates: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    warnings: list[dict[str, Any]] = []
    for index, channel in enumerate(raw_channels[:10_000]):
        if not isinstance(channel, Mapping):
            warnings.append(
                {
                    "code": "HVDC_RESULT_CHANNEL_INVALID",
                    "message": f"PSOUT channel record {index} is not an object.",
                }
            )
            continue
        source = channel.get("path") or channel.get("name")
        if not isinstance(source, str) or not source.strip():
            warnings.append(
                {
                    "code": "HVDC_RESULT_CHANNEL_UNNAMED",
                    "message": f"PSOUT channel record {index} has no path or name.",
                }
            )
            continue
        source_evidence = _source_keys(source)
        matched = [
            canonical
            for canonical, accepted in aliases.items()
            if source_evidence & accepted
        ]
        if len(matched) > 1:
            warnings.append(
                {
                    "code": "HVDC_RESULT_MAPPING_CONFLICT",
                    "message": f"PSOUT channel '{source}' matches multiple canonical mappings.",
                    "source": source,
                    "canonicals": sorted(matched),
                }
            )
            continue
        if len(matched) == 1:
            candidates.setdefault(matched[0], []).append((source, channel))

    normalized_channels: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    for canonical in sorted(candidates):
        matches = candidates[canonical]
        if len(matches) != 1:
            warnings.append(
                {
                    "code": "HVDC_RESULT_MAPPING_CONFLICT",
                    "message": f"Multiple PSOUT channels map to canonical '{canonical}'.",
                    "canonical": canonical,
                    "sources": sorted(source for source, _ in matches),
                }
            )
            continue
        source, channel = matches[0]
        normalized_channels.append(
            {
                "name": canonical,
                "values": channel.get("values"),
                "domain": channel.get("domain"),
            }
        )
        mapping = metadata[canonical]
        resolved.append(
            {
                "canonical": canonical,
                "source": source,
                "units": mapping.get("units"),
                "direction": mapping.get("direction", "measurement"),
            }
        )

    normalized = dict(samples)
    normalized["channels"] = normalized_channels
    return {
        "samples": normalized,
        "resolved_channels": resolved,
        "warnings": warnings,
    }
