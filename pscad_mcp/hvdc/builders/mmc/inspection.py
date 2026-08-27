"""Structure-backed MMC interpretation for generic PSCAD evidence."""

from __future__ import annotations

import re

from ...models import HvdcComponentRecord, HvdcProjectEvidence


def _description(component: HvdcComponentRecord) -> str:
    return f"{component.name} {component.definition} {' '.join(component.labels)}".casefold()


def _items(evidence: HvdcProjectEvidence, terms: tuple[str, ...]) -> list[HvdcComponentRecord]:
    return [component for component in evidence.components if any(term in _description(component) for term in terms)]


def _component_record(component: HvdcComponentRecord) -> dict[str, object]:
    text = _description(component)
    station = "STATION_P" if "station_p" in text or re.search(r"\bp\b", component.name.casefold()) else "STATION_VDC" if "station_vdc" in text or " v " in f" {component.name.casefold()} " else None
    phase = next((phase.upper() for phase in ("a", "b", "c") if re.search(rf"\b{phase}\b", component.name.casefold())), None)
    position = "upper" if "upper" in text else "lower" if "lower" in text else None
    return {
        "component_id": component.component_id,
        "name": component.name,
        "definition": component.definition,
        "station": station,
        "phase": phase,
        "position": position,
    }


def _conductor_endpoints(evidence: HvdcProjectEvidence, polarity: str) -> set[tuple[str, str]]:
    endpoints: set[tuple[str, str]] = set()
    for connection in evidence.connections:
        text = " ".join((connection.connection_id, connection.source_port, connection.target_port)).casefold()
        if polarity not in text:
            continue
        endpoints.add(tuple(sorted((connection.source_component_id, connection.target_component_id))))
    return endpoints


def inspect_mmc_evidence(evidence: HvdcProjectEvidence) -> dict[str, object]:
    stations = sorted(
        [
            component
            for component in evidence.components
            if component.definition.rsplit(":", 1)[-1].casefold() == "mmcstation"
        ],
        key=lambda item: (0 if item.name.casefold() == "station_p" else 1, item.name),
    )
    arms = [
        component
        for component in evidence.components
        if component.definition.rsplit(":", 1)[-1].casefold().endswith("arm")
        and not any(term in component.definition.casefold() for term in ("measurement", "current", "control"))
    ]
    controls = _items(evidence, ("control", "carrier", "firing"))
    protection = _items(evidence, ("protection", "breaker", "fault"))
    measurements = _items(evidence, ("measurement", "meter"))
    structural_text = " ".join(
        [*evidence.definitions, *(f"{item.name} {item.definition}" for item in evidence.components)]
    ).casefold()

    has_cells = "cell" in structural_text or "submodule" in structural_text
    has_carrier = "carrier" in structural_text
    has_firing = "firing" in structural_text or "pulse" in structural_text
    has_average_arm = "averagearm" in structural_text or "average arm" in structural_text
    model_fidelity = (
        "detailed_pwm"
        if has_cells and has_carrier and has_firing
        else "average_value"
        if has_average_arm
        else "unknown"
    )
    converter = "half_bridge" if "halfbridge" in structural_text or "half bridge" in structural_text else "unknown"

    positive = _conductor_endpoints(evidence, "positive")
    negative = _conductor_endpoints(evidence, "negative")
    station_ids = {station.component_id for station in stations}
    shared_pair = next((pair for pair in positive & negative if set(pair) == station_ids and len(pair) == 2), None)
    topology = "two_terminal_symmetrical_monopole" if shared_pair is not None else "unknown"

    unresolved: list[str] = []
    if len(stations) != 2:
        unresolved.append("MMC inspection requires exactly two explicit station instances.")
    if topology == "unknown":
        unresolved.append("MMC positive and negative conductors do not prove one shared two-station link.")
    if len(arms) != 12:
        unresolved.append(f"MMC inspection found {len(arms)} of 12 required station arms.")
    arm_measurements = [item for item in measurements if "armcurrent" in _description(item) or "arm current" in _description(item)]
    if len(arm_measurements) != 12:
        unresolved.append(f"MMC inspection found {len(arm_measurements)} of 12 required arm-current measurements.")
    if model_fidelity == "unknown":
        unresolved.append("MMC model fidelity requires explicit PWM cell/carrier/firing or average-arm structure.")
    if not controls:
        unresolved.append("MMC control structure is incomplete.")
    if not protection:
        unresolved.append("MMC protection structure is incomplete.")

    evidence_items = [
        {"kind": "positive_conductor", "station_pairs": sorted(positive)},
        {"kind": "negative_conductor", "station_pairs": sorted(negative)},
        {"kind": "fidelity", "cell": has_cells, "carrier": has_carrier, "firing": has_firing, "average_arm": has_average_arm},
    ]
    completeness = 1.0 - min(1.0, len(unresolved) / 6.0)
    return {
        "family": "mmc",
        "topology": topology,
        "terminal_count": len(stations),
        "converter": converter,
        "model_fidelity": model_fidelity,
        "stations": [station.name for station in stations],
        "arms": [_component_record(item) for item in arms],
        "controls": [_component_record(item) for item in controls],
        "protection": [_component_record(item) for item in protection],
        "measurements": [_component_record(item) for item in measurements],
        "confidence": round(completeness, 6),
        "evidence": evidence_items,
        "unresolved_questions": unresolved,
    }


__all__ = ["inspect_mmc_evidence"]
