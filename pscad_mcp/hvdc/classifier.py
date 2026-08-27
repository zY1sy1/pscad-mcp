"""Deterministic evidence scoring for common HVDC topology families."""

from __future__ import annotations

import re

from .models import HvdcAsset, HvdcProjectEvidence, HvdcSourceRef, HvdcTopologySummary
from .return_paths import analyze_return_paths
from .builders.mmc.inspection import inspect_mmc_evidence


def _tokens(values: list[str] | tuple[str, ...]) -> set[str]:
    return {token for value in values for token in re.findall(r"[a-z0-9]+", value.lower())}


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    normalized = text.lower()
    return any(term in normalized for term in terms)


def _score(values: list[str], terms: tuple[str, ...]) -> int:
    return sum(1 for value in values for term in terms if _contains(value, (term,)))


def classify_topology(evidence: HvdcProjectEvidence) -> HvdcTopologySummary:
    names = list(evidence.definitions) + [component.definition for component in evidence.components]
    labels = [label.text for label in evidence.labels]
    joined = " ".join(names + labels)
    evidence_terms = names + labels
    scores = {
        "lcc": _score(evidence_terms, ("rectcc", "rectpole", "inverterpole", "invctrl", "rectifier_ac", "rectifier", "inverter")),
        "vsc_2level": _score(evidence_terms, ("vsc", "igbt", "pll", "dq", "twolevel", "2level")),
        "mmc": _score(evidence_terms, ("mmc", "submodule", "sub_module", "arm", "sm", "circulating")),
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
    pole_roles: dict[str, HvdcSourceRef] = {}
    neutral_assets: list[HvdcSourceRef] = []
    for component in evidence.components:
        value = f"{component.name} {component.definition} {' '.join(component.labels)}".casefold()
        if re.search(r"positive|pole[ _-]?1|pole[ _-]?p", value):
            pole_roles.setdefault("positive", component.source)
        if re.search(r"negative|pole[ _-]?2|pole[ _-]?n", value):
            pole_roles.setdefault("negative", component.source)
        if re.search(r"neutral|midpoint|groundbus", value):
            neutral_assets.append(component.source)
    pole_tokens = len(pole_roles)
    generic_poles = sum(1 for value in names + labels if re.search(r"pole", value, re.IGNORECASE))
    polarity = "bipolar" if pole_tokens >= 2 or generic_poles >= 2 else "monopolar" if pole_tokens == 1 or generic_poles == 1 else "unknown"
    breaker = _contains(joined, ("breaker", "loadbreaker", "protection", "diff"))
    line = _contains(joined, ("transline", "trans_line", "dc_line", "line", "tl1", "tl2"))
    mmc_report = inspect_mmc_evidence(evidence) if family == "mmc" else None
    if mmc_report is not None:
        polarity = "symmetrical_monopole" if mmc_report["topology"] == "two_terminal_symmetrical_monopole" else "unknown"
    paths = () if family in {"mmc", "vsc_2level"} else analyze_return_paths(evidence)
    verified = [path for path in paths if path.closed]
    if family in {"mmc", "vsc_2level"}:
        return_mode = "not_applicable"
        path_status = "not_applicable"
    elif len(verified) == 1:
        return_mode = verified[0].mode
        path_status = "verified"
    elif len(verified) > 1:
        return_mode = "unknown"
        path_status = "ambiguous"
    elif any(path.evidence for path in paths):
        return_mode = "unknown"
        path_status = "ambiguous" if all(path.evidence for path in paths) else "incomplete"
    else:
        return_mode = "unknown"
        path_status = "incomplete"
    unresolved = []
    if family == "unknown":
        unresolved.append("HVDC topology family needs explicit profile evidence or additional component definitions.")
    if polarity == "unknown":
        unresolved.append("Pole polarity could not be established from project evidence.")
    if path_status != "verified" and family not in {"mmc", "vsc_2level"}:
        unresolved.append("LCC return path could not be verified from explicit connection and switch evidence.")
    if mmc_report is not None:
        unresolved.extend(str(item) for item in mmc_report["unresolved_questions"])
    return HvdcTopologySummary(
        family=family,
        polarity=polarity,
        terminal_count=int(mmc_report["terminal_count"]) if mmc_report is not None else None,
        breaker_protection_present=breaker,
        dc_line_present=line,
        confidence=confidence,
        return_mode=return_mode,
        return_path_status=path_status,
        return_path=tuple(paths),
        pole_roles=pole_roles,
        neutral_assets=tuple(neutral_assets),
        mode_evidence=tuple(item for path in paths for item in path.evidence),
        evidence=tuple(sorted({name for name in names if _contains(name, ("rect", "inverter", "vsc", "mmc", "breaker", "line", "tl"))} | ({f"explicit topology override: {explicit_family}"} if explicit_family else set()))),
        unresolved_questions=tuple(unresolved),
    )


def extract_assets(evidence: HvdcProjectEvidence) -> list[HvdcAsset]:
    assets: list[HvdcAsset] = []
    for item in evidence.components:
        value = f"{item.name} {item.definition}"
        lowered = value.lower()
        kinds: list[str] = []
        if "pole" in lowered:
            kinds.append("pole")
        if "positive" in lowered and "pole" in lowered:
            kinds.append("positive_pole")
        if "negative" in lowered and "pole" in lowered:
            kinds.append("negative_pole")
        if "neutral" in lowered:
            kinds.append("neutral_bus")
        if any(token in lowered for token in ("earth electrode", "earthelectrode", "ground electrode")):
            kinds.append("earth_electrode")
        if "earth return" in lowered or "earthreturn" in lowered:
            kinds.append("earth_return")
        if "metallic return" in lowered or "metallicreturn" in lowered:
            kinds.append("metallic_return")
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
