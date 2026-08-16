"""Resolve configured semantic aliases against observed project labels."""

from __future__ import annotations

from dataclasses import dataclass

from .models import HvdcMapping, HvdcProjectEvidence, HvdcSourceRef


@dataclass(frozen=True)
class MappingResolution:
    mappings: tuple[HvdcMapping, ...]
    unresolved: tuple[str, ...]
    warnings: tuple[str, ...]


def resolve_mappings(evidence: HvdcProjectEvidence, profile: dict) -> MappingResolution:
    observed: list[tuple[str, HvdcSourceRef]] = []
    for component in evidence.components:
        for parameter_name, value in component.parameters.items():
            observed.append((parameter_name, HvdcSourceRef(component.source.project_path, component.source.canvas_name, component.source.component_id, component.source.definition, parameter_name)))
            if value:
                observed.append((f"{parameter_name} {value}", HvdcSourceRef(component.source.project_path, component.source.canvas_name, component.source.component_id, component.source.definition, parameter_name)))
    observed.extend((label.text, label.source) for label in evidence.labels)
    mappings: list[HvdcMapping] = []
    unresolved: list[str] = []
    warnings: list[str] = []
    for item in profile.get("mappings", []):
        canonical = str(item["canonical"])
        aliases = tuple(str(alias) for alias in item.get("aliases", []))
        matched: tuple[str, HvdcSourceRef] | None = None
        matches: list[tuple[str, HvdcSourceRef]] = []
        for text, source in observed:
            normalized = text.strip().lower()
            if normalized in {alias.lower() for alias in aliases} or any(alias.lower() in normalized for alias in aliases):
                matches.append((text, source))
        if matches:
            matched = matches[0]
        if len(matches) > 1:
            warnings.append(f"Multiple observed sources matched mapping '{canonical}': {[item[0] for item in matches]}")
        expected_family = str(item.get("unit_family") or "")
        for text, _source in matches:
            lower = text.lower()
            if expected_family == "current" and any(token in lower for token in ("kv", "mv", "volt")):
                warnings.append(f"Unit conflict for '{canonical}': observed source '{text}' looks like voltage.")
            if expected_family == "voltage" and any(token in lower for token in ("ka", "ma", "amp")):
                warnings.append(f"Unit conflict for '{canonical}': observed source '{text}' looks like current.")
        if matched:
            mappings.append(HvdcMapping(canonical, aliases, matched[1], item.get("units"), item.get("unit_family"), item.get("direction", "measurement"), "observed", 1.0))
        else:
            mappings.append(HvdcMapping(canonical, aliases, None, item.get("units"), item.get("unit_family"), item.get("direction", "measurement"), "unresolved", 0.0))
            unresolved.append(canonical)
    return MappingResolution(tuple(mappings), tuple(unresolved), tuple(warnings))
