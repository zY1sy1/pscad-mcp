"""Deterministic evidence scoring for common HVDC topology families."""

from __future__ import annotations

import re

from .models import HvdcAsset, HvdcProjectEvidence, HvdcSourceRef, HvdcTopologySummary


def _tokens(values: list[str] | tuple[str, ...]) -> set[str]:
    return {token for value in values for token in re.findall(r"[a-z0-9]+", value.lower())}


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    normalized = text.lower()
    return any(term in normalized for term in terms)


def classify_topology(evidence: HvdcProjectEvidence) -> HvdcTopologySummary:
    names = list(evidence.definitions) + [component.definition for component in evidence.components]
    labels = [label.text for label in evidence.labels]
    joined = " ".join(names + labels)
    scores = {
        "lcc": sum(_contains(name, ("rectcc", "rectpole", "inverterpole", "invctrl", "rectifier_ac")) for name in names),
        "vsc_2level": sum(_contains(name, ("vsc", "igbt", "pll", "dq", "twolevel", "2level")) for name in names),
        "mmc": sum(_contains(name, ("mmc", "submodule", "sub_module", "arm", "sm")) for name in names),
    }
    best_family, best_score = max(scores.items(), key=lambda pair: pair[1])
    explicit_family = None
    for label in labels:
        normalized = label.lower()
        if "topology" in normalized or "technology" in normalized:
            if "vsc" in normalized:
                explicit_family = "vsc_2level" if "2" in normalized or "two" in normalized else "vsc_2level"
            elif "mmc" in normalized:
                explicit_family = "mmc"
            elif "lcc" in normalized:
                explicit_family = "lcc"
    if explicit_family:
        family = explicit_family
        confidence = 1.0
    elif best_score < 2 or list(scores.values()).count(best_score) > 1:
        family = "unknown"
        confidence = 0.0
    else:
        family = best_family
        confidence = min(1.0, best_score / 5)
    pole_tokens = sum(_contains(name, ("pole", "bipolar", "positive", "negative")) for name in names + labels)
    polarity = "bipolar" if pole_tokens >= 2 else "monopolar" if pole_tokens == 1 else "unknown"
    breaker = _contains(joined, ("breaker", "loadbreaker", "protection", "diff"))
    line = _contains(joined, ("transline", "trans_line", "dc_line", "line", "tl1", "tl2"))
    unresolved = []
    if family == "unknown":
        unresolved.append("HVDC topology family needs explicit profile evidence or additional component definitions.")
    if polarity == "unknown":
        unresolved.append("Pole polarity could not be established from project evidence.")
    return HvdcTopologySummary(
        family=family,
        polarity=polarity,
        terminal_count=None,
        breaker_protection_present=breaker,
        dc_line_present=line,
        confidence=confidence,
        evidence=tuple(sorted({name for name in names if _contains(name, ("rect", "inverter", "vsc", "mmc", "breaker", "line", "tl"))} | ({f"explicit topology override: {explicit_family}"} if explicit_family else set()))),
        unresolved_questions=tuple(unresolved),
    )


def extract_assets(evidence: HvdcProjectEvidence) -> list[HvdcAsset]:
    assets: list[HvdcAsset] = []
    records = list(evidence.components)
    for definition in evidence.definitions:
        records.append(type("DefinitionRecord", (), {"name": definition, "definition": definition, "source": HvdcSourceRef(evidence.project_path, definition=definition)})())
    for item in records:
        value = f"{item.name} {item.definition}"
        lowered = value.lower()
        kinds: list[str] = []
        if "pole" in lowered:
            kinds.append("pole")
        if "rect" in lowered:
            kinds.append("rectifier")
        if "inverter" in lowered:
            kinds.append("inverter")
        if "invctrl" in lowered or any(token in lowered for token in ("pll", "control", "ctrl")):
            kinds.append("controller")
        if "breaker" in lowered:
            kinds.append("breaker")
        if any(token in lowered for token in ("transline", "dc_line", "line", "tl1", "tl2")):
            kinds.append("dc_line")
        if any(token in lowered for token in ("measure", "meter", "datalabel")):
            kinds.append("measurement")
        for kind in dict.fromkeys(kinds):
            assets.append(HvdcAsset(kind, item.name, item.source, 0.8, (item.definition,)))
    return assets
