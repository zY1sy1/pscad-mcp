"""Explicit, project-qualified HVDC command binding resolution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from ..core.backend.base import BackendError
from .models import HvdcProjectEvidence


_UNSAFE_COMMAND_PARAMETERS = {
    "caption",
    "comment",
    "description",
    "display",
    "enab",
    "group",
    "label",
    "max",
    "min",
    "mrun",
    "name",
    "pol",
    "scale",
    "title",
    "text",
    "units",
    "usesignalname",
}


def _binding_error(message: str, **details: Any) -> BackendError:
    return BackendError(
        "HVDC_MAPPING_MISSING",
        message,
        "hvdc",
        "resolve_command_binding",
        details,
    )


def _normalized_parameter_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _fingerprint_matches(evidence: HvdcProjectEvidence, fingerprint: Mapping[str, Any]) -> bool:
    project_stem = fingerprint.get("project_stem")
    if project_stem is not None and project_stem != evidence.project_name:
        return False
    pscad_version = fingerprint.get("pscad_version")
    if pscad_version is not None and pscad_version != evidence.pscad_version:
        return False
    definitions = fingerprint.get("definitions")
    return definitions is None or set(definitions).issubset(evidence.definitions)


def matching_fingerprints(
    evidence: HvdcProjectEvidence, profile: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Return every project fingerprint that matches scanned evidence.

    An empty fingerprint list deliberately acts as one unconstrained fingerprint
    for backwards-compatible direct resolver use. A populated fingerprint is
    always matched conjunctively.
    """

    configured = profile.get("project_fingerprints", [])
    fingerprints = configured or [{}]
    return [
        deepcopy(dict(fingerprint))
        for fingerprint in fingerprints
        if isinstance(fingerprint, Mapping) and _fingerprint_matches(evidence, fingerprint)
    ]


def _command_binding(profile: Mapping[str, Any], canonical: str) -> Mapping[str, Any]:
    bindings = profile.get("command_bindings", [])
    for binding in bindings:
        if isinstance(binding, Mapping) and binding.get("canonical") == canonical:
            return binding
    raise _binding_error(
        f"No explicit command binding is configured for '{canonical}'.",
        canonical=canonical,
        reason="command_binding_missing",
    )


def _matching_components(
    evidence: HvdcProjectEvidence, selector: Mapping[str, Any]
) -> list[Any]:
    return [
        component
        for component in evidence.components
        if (
            selector.get("component_id") is None
            or selector["component_id"] == component.component_id
        )
        and (
            selector.get("canvas") is None
            or selector["canvas"] == component.source.canvas_name
        )
        and (
            selector.get("definition") is None
            or selector["definition"] == component.definition
        )
    ]


def _allowed_value(value: Any, allowed_values: Sequence[Any]) -> bool:
    return any(type(value) is type(candidate) and value == candidate for candidate in allowed_values)


def resolve_command_binding(
    evidence: HvdcProjectEvidence,
    profile: Mapping[str, Any],
    canonical: str,
    value: Any,
) -> dict[str, Any]:
    """Resolve one confirmed command to one exact scanned component parameter."""

    fingerprints = matching_fingerprints(evidence, profile)
    if not fingerprints:
        raise _binding_error(
            f"No project fingerprint matched scanned evidence for '{canonical}'.",
            canonical=canonical,
            project_name=evidence.project_name,
            reason="project_fingerprint_mismatch",
        )
    binding = _command_binding(profile, canonical)
    allowed_values = binding.get("allowed_values", [])
    if not _allowed_value(value, allowed_values):
        raise _binding_error(
            f"Requested value for '{canonical}' is not in its allowed values.",
            canonical=canonical,
            requested_value=value,
            allowed_values=deepcopy(list(allowed_values)),
            reason="command_value_not_allowed",
        )
    selector = binding.get("component", {})
    components = _matching_components(evidence, selector)
    if not components:
        raise _binding_error(
            f"Command '{canonical}' must resolve to exactly one component; found none.",
            canonical=canonical,
            selector=deepcopy(dict(selector)),
            reason="component_selector_unresolved",
        )
    if len(components) != 1:
        raise _binding_error(
            f"Command '{canonical}' must resolve to exactly one component; found {len(components)}.",
            canonical=canonical,
            selector=deepcopy(dict(selector)),
            component_ids=[component.component_id for component in components],
            reason="component_selector_ambiguous",
        )
    component = components[0]
    parameter_name = binding.get("parameter_name")
    if not isinstance(parameter_name, str) or parameter_name not in component.parameters:
        raise _binding_error(
            f"Command '{canonical}' requires exact parameter '{parameter_name}'.",
            canonical=canonical,
            component_id=component.component_id,
            parameter_name=parameter_name,
            reason="command_parameter_missing",
        )
    if _normalized_parameter_name(parameter_name) in _UNSAFE_COMMAND_PARAMETERS:
        raise _binding_error(
            f"Command '{canonical}' resolves to unsafe display or identity parameter '{parameter_name}'.",
            canonical=canonical,
            component_id=component.component_id,
            parameter_name=parameter_name,
            reason="unsafe_command_parameter",
        )
    return {
        "canonical": canonical,
        "component_id": str(component.component_id),
        "parameter_name": parameter_name,
        "old_value": deepcopy(component.parameters[parameter_name]),
        "semantics": deepcopy(binding.get("semantics")),
        "read_back": binding.get("read_back", False),
        "matched_fingerprint": fingerprints[0],
    }


def resolve_requested_commands(
    evidence: HvdcProjectEvidence,
    profile: Mapping[str, Any],
    requests: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve command requests in their original request order."""

    resolved: list[dict[str, Any]] = []
    for index, request in enumerate(requests):
        canonical = request.get("canonical", request.get("target"))
        if not isinstance(canonical, str) or not canonical:
            raise _binding_error(
                "Each command request requires a non-empty canonical.",
                index=index,
                reason="command_canonical_missing",
            )
        resolved.append(resolve_command_binding(evidence, profile, canonical, request.get("value")))
    return resolved
