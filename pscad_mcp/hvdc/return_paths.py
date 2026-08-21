"""Conservative graph analysis for LCC earth and metallic return paths."""

from __future__ import annotations

import re

from .models import HvdcProjectEvidence, HvdcReturnPath, HvdcSourceRef

RETURN_MODES = {"earth_return", "metallic_return", "mixed_transition", "unknown"}
RETURN_STATUSES = {"verified", "incomplete", "ambiguous"}


def _text(component) -> str:
    return " ".join((component.name, component.definition, *component.labels, *component.parameters.values())).casefold()


def _connected_components(evidence: HvdcProjectEvidence) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for connection in evidence.connections:
        graph.setdefault(connection.source_component_id, set()).add(connection.target_component_id)
        graph.setdefault(connection.target_component_id, set()).add(connection.source_component_id)
    return graph


def _path_between(graph: dict[str, set[str]], start: str, end: str) -> list[str] | None:
    queue = [(start, [start])]
    seen = {start}
    while queue:
        node, path = queue.pop(0)
        if node == end:
            return path
        for nxt in graph.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, [*path, nxt]))
    return None


def _path_for_mode(graph, components, start: str, end: str, mode: str) -> list[str] | None:
    queue = [(start, [start])]
    seen: set[tuple[str, frozenset[str]]] = set()
    token = re.compile(r"earth|electrode|ground" if mode == "earth_return" else r"metallic|metal")
    while queue:
        node, path = queue.pop(0)
        texts = " ".join(_text(components[item]) for item in path if item in components)
        if node == end and token.search(texts):
            return path
        key = (node, frozenset(path))
        if key in seen or len(path) > len(components):
            continue
        seen.add(key)
        for nxt in graph.get(node, ()):
            if nxt not in path:
                queue.append((nxt, [*path, nxt]))
    return None


def _candidate_path(evidence: HvdcProjectEvidence, mode: str) -> HvdcReturnPath:
    components = {component.component_id: component for component in evidence.components}
    graph = _connected_components(evidence)
    neutrals = [component for component in evidence.components if re.search(r"neutral|midpoint|groundbus", _text(component))]
    if len(neutrals) < 2:
        return HvdcReturnPath(mode, unresolved_questions=("Two neutral endpoints are required.",))
    path_ids = _path_for_mode(graph, components, neutrals[0].component_id, neutrals[1].component_id, mode)
    if not path_ids:
        return HvdcReturnPath(mode, endpoints=tuple(item.source for item in neutrals[:2]), unresolved_questions=("No closed connection chain joins the neutral endpoints.",))
    path_components = [components[item] for item in path_ids if item in components]
    texts = [_text(item) for item in path_components]
    if mode == "earth_return":
        asset_ok = any(re.search(r"earth|electrode|ground", value) for value in texts)
        switch_ok = any(re.search(r"switch", value) and re.search(r"closed|on|1|true", value) for value in texts)
    else:
        asset_ok = any(re.search(r"metallic|metal", value) for value in texts)
        switch_ok = any(re.search(r"switch", value) and re.search(r"closed|on|1|true", value) for value in texts)
    segments = tuple(item.source for item in path_components)
    endpoints = tuple(item.source for item in neutrals[:2])
    evidence_terms = tuple(sorted({item.definition for item in path_components} | {"explicit connection chain"}))
    if asset_ok and switch_ok:
        return HvdcReturnPath(mode, segments, endpoints, True, 1.0, evidence_terms)
    question = "Return asset or closed switch evidence is missing."
    return HvdcReturnPath(mode, segments, endpoints, False, 0.4 if asset_ok else 0.2, evidence_terms, (question,))


def analyze_return_paths(evidence: HvdcProjectEvidence) -> tuple[HvdcReturnPath, ...]:
    """Return earth and metallic candidates without inventing connectivity."""
    return tuple(_candidate_path(evidence, mode) for mode in ("earth_return", "metallic_return"))
