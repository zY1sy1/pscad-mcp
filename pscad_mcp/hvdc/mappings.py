"""Resolve configured semantic aliases against observed project labels."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .models import HvdcComponentRecord, HvdcMapping, HvdcProjectEvidence, HvdcSourceRef


@dataclass(frozen=True)
class MappingResolution:
    mappings: tuple[HvdcMapping, ...]
    unresolved: tuple[str, ...]
    warnings: tuple[str, ...]
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ObservedSource:
    texts: tuple[str, ...]
    source: HvdcSourceRef
    kinds: frozenset[str]


def _normalize(value: str) -> str:
    return re.sub(r"[\W_]+", " ", value.casefold()).strip()


def _alias_matches(text: str, alias: str) -> bool:
    normalized_text = _normalize(text)
    normalized_alias = _normalize(alias)
    if not normalized_alias:
        return False
    if len(normalized_alias) == 1:
        return normalized_text == normalized_alias
    return normalized_text == normalized_alias or re.search(
        rf"(?<!\w){re.escape(normalized_alias)}(?!\w)", normalized_text
    ) is not None


def _component_kinds(component: HvdcComponentRecord) -> frozenset[str]:
    value = f"{component.name} {component.definition}".casefold()
    kinds = {"parameter"}
    if "ammeter" in value:
        kinds.add("ammeter")
    if "voltmeter" in value:
        kinds.add("voltmeter")
    if "multimeter" in value:
        kinds.add("multimeter")
    if "master:pgb" in value:
        kinds.add("graph")
    if any(token in value for token in ("ammeter", "voltmeter", "multimeter", "meter", "master:pgb")):
        kinds.update(("meter", "measurement"))
    if any(token in value for token in ("controller", "control", "ctrl", "command", "order", "master:const", "master:import", "master:export")):
        kinds.add("control")
    return frozenset(kinds)


def _observed_sources(evidence: HvdcProjectEvidence) -> list[_ObservedSource]:
    observed: list[_ObservedSource] = []
    for component in evidence.components:
        kinds = _component_kinds(component)
        for parameter_name, value in component.parameters.items():
            source = HvdcSourceRef(
                component.source.project_path,
                component.source.canvas_name,
                component.source.component_id,
                component.source.definition,
                parameter_name,
            )
            texts = tuple(dict.fromkeys(item for item in (parameter_name, value, f"{parameter_name} {value}".strip()) if item))
            observed.append(_ObservedSource(texts, source, kinds))
    for label in evidence.labels:
        kind = label.kind.casefold()
        kinds = {kind}
        if kind in {"label", "annotation", "datalabel", "nodelabel", "text", "component"}:
            kinds.add("label")
        observed.append(_ObservedSource((label.text,), label.source, frozenset(kinds)))
    return observed


def _has_unit_conflict(unit_family: str, source: _ObservedSource) -> bool:
    lower = " ".join(source.texts).casefold()
    if unit_family == "current":
        return any(token in lower for token in ("kv", "mv", "volt"))
    if unit_family == "voltage":
        return any(token in lower for token in ("ka", "ma", "amp"))
    return False


def resolve_mappings(evidence: HvdcProjectEvidence, profile: dict) -> MappingResolution:
    observed = _observed_sources(evidence)
    candidates: dict[str, list[_ObservedSource]] = {}
    items = list(profile.get("mappings", []))
    for item in items:
        canonical = str(item["canonical"])
        aliases = tuple(str(alias) for alias in item.get("aliases", []))
        allowed_kinds = {str(kind).casefold() for kind in item.get("source_kinds", [])}
        by_source: dict[HvdcSourceRef, _ObservedSource] = {}
        for source in observed:
            if allowed_kinds and source.kinds.isdisjoint(allowed_kinds):
                continue
            if any(_alias_matches(text, alias) for text in source.texts for alias in aliases):
                by_source[source.source] = source
        candidates[canonical] = list(by_source.values())

    source_users: dict[HvdcSourceRef, set[str]] = {}
    for canonical, matches in candidates.items():
        for match in matches:
            source_users.setdefault(match.source, set()).add(canonical)
    reused = {
        canonical
        for canonicals in source_users.values()
        if len(canonicals) > 1
        for canonical in canonicals
    }

    mappings: list[HvdcMapping] = []
    unresolved: list[str] = []
    warnings: list[str] = []
    conflicts: list[str] = []
    for item in items:
        canonical = str(item["canonical"])
        aliases = tuple(str(alias) for alias in item.get("aliases", []))
        matches = candidates[canonical]
        if len(matches) > 1:
            warnings.append(
                f"Multiple observed sources matched mapping '{canonical}': "
                f"{[source.source.component_id or source.source.label for source in matches]}"
            )
        expected_family = str(item.get("unit_family") or "")
        unit_conflict = any(_has_unit_conflict(expected_family, source) for source in matches)
        if unit_conflict:
            warnings.append(f"Unit conflict for '{canonical}': observed source is incompatible with {expected_family}.")
        if canonical in reused:
            warnings.append(f"Observed source for '{canonical}' also matched another canonical mapping.")
        conflict = len(matches) > 1 or unit_conflict or canonical in reused
        if conflict:
            mappings.append(HvdcMapping(canonical, aliases, None, item.get("units"), item.get("unit_family"), item.get("direction", "measurement"), "conflict", 0.0))
            conflicts.append(canonical)
            unresolved.append(canonical)
        elif matches:
            mappings.append(HvdcMapping(canonical, aliases, matches[0].source, item.get("units"), item.get("unit_family"), item.get("direction", "measurement"), "observed", 1.0))
        else:
            mappings.append(HvdcMapping(canonical, aliases, None, item.get("units"), item.get("unit_family"), item.get("direction", "measurement"), "unresolved", 0.0))
            unresolved.append(canonical)
    return MappingResolution(tuple(mappings), tuple(unresolved), tuple(warnings), tuple(conflicts))
