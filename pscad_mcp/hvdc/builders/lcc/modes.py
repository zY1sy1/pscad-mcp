"""Operating-mode copies and strict EMTDC-clock schedule validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any

from ....core.backend.base import BackendError
from ...bindings import resolve_requested_commands
from ...preflight import verify_exact_result_selectors
from ...timing import dispatch_timed_events, select_timing_mode
from .parametric_models import LccModeEvent

SUPPORTED_MODES = frozenset({"bipolar_run", "monopolar_earth_return", "monopolar_metallic_return", "metallic_return", "positive_pole_outage", "negative_pole_outage", "pole_outage", "scheduled_switching"})


@dataclass(frozen=True)
class ModeCopy:
    mode: str
    plan: Any


_TOKEN_SEAL = object()


@dataclass(frozen=True, init=False)
class LccSwitchingToken:
    """Immutable result of the final, write-free strict switching preflight."""

    project_name: str
    events: tuple[Mapping[str, Any], ...]
    timing_mode: str
    observed_time_s: float
    output_channels_verified: tuple[str, ...]
    _seal: object


def _switching_token(
    project_name: str,
    events: Sequence[Mapping[str, Any]],
    *,
    observed_time_s: float,
    output_channels_verified: Sequence[str],
) -> LccSwitchingToken:
    token = object.__new__(LccSwitchingToken)
    object.__setattr__(token, "project_name", project_name)
    object.__setattr__(token, "events", _freeze(tuple(events)))
    object.__setattr__(token, "timing_mode", "native")
    object.__setattr__(token, "observed_time_s", observed_time_s)
    object.__setattr__(token, "output_channels_verified", tuple(output_channels_verified))
    object.__setattr__(token, "_seal", _TOKEN_SEAL)
    return token


def _bounded_json(value: Any, *, depth: int = 0) -> Any:
    if depth >= 5:
        return "<depth-limit>"
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return value[:256]
    if isinstance(value, Mapping):
        return {
            str(key)[:128]: _bounded_json(item, depth=depth + 1)
            for key, item in list(value.items())[:64]
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_bounded_json(item, depth=depth + 1) for item in list(value)[:64]]
    return f"<{type(value).__name__}>"


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", "validate_lcc_schedule", _bounded_json(details))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return deepcopy(value)


def _mode_contract(base_plan: Mapping[str, Any], mode: str) -> Mapping[str, Any]:
    bindings = base_plan.get("mode_bindings")
    contract = bindings.get(mode) if isinstance(bindings, Mapping) else None
    if not isinstance(contract, Mapping):
        raise _error(
            "LCC_OPERATING_MODE_INVALID",
            "The base plan has no exact override contract for the requested mode.",
            mode=mode,
            reason="mode_binding_missing",
        )
    topology = contract.get("topology_overrides")
    controls = contract.get("control_overrides")
    if not isinstance(topology, Mapping) or not topology:
        raise _error(
            "LCC_OPERATING_MODE_INVALID",
            "A mode contract requires explicit topology overrides.",
            mode=mode,
            reason="topology_overrides_missing",
        )
    if (
        not isinstance(controls, Sequence)
        or isinstance(controls, (str, bytes, bytearray))
        or not controls
    ):
        raise _error(
            "LCC_OPERATING_MODE_INVALID",
            "A mode contract requires explicit control overrides.",
            mode=mode,
            reason="control_overrides_missing",
        )
    for index, control in enumerate(controls):
        if not isinstance(control, Mapping) or any(
            not isinstance(control.get(field), str) or not control[field].strip()
            for field in ("canonical", "component_id", "parameter_name")
        ) or "value" not in control:
            raise _error(
                "LCC_OPERATING_MODE_INVALID",
                "Each control override requires an exact canonical, component_id, parameter_name, and value.",
                mode=mode,
                index=index,
                reason="control_override_inexact",
            )
    return contract


def derive_mode_copies(base_plan: Any, modes: Sequence[str]) -> tuple[ModeCopy, ...]:
    if not isinstance(base_plan, Mapping):
        raise _error("LCC_OPERATING_MODE_INVALID", "base_plan must be an object.")
    if not modes:
        raise _error("LCC_OPERATING_MODE_INVALID", "At least one operating mode is required.")
    copies: list[ModeCopy] = []
    seen: set[str] = set()
    for mode in modes:
        if not isinstance(mode, str) or mode not in SUPPORTED_MODES:
            raise _error("LCC_OPERATING_MODE_INVALID", "Unsupported operating mode.", mode=mode)
        if mode in seen:
            raise _error("LCC_OPERATING_MODE_INVALID", "Duplicate operating mode.", mode=mode)
        seen.add(mode)
        contract = _mode_contract(base_plan, mode)
        plan = deepcopy(dict(base_plan))
        topology = plan.get("topology")
        if not isinstance(topology, Mapping):
            raise _error(
                "LCC_OPERATING_MODE_INVALID",
                "The base plan topology cannot receive explicit mode overrides.",
                mode=mode,
                reason="topology_contract_missing",
            )
        plan["topology"] = {**deepcopy(dict(topology)), **deepcopy(dict(contract["topology_overrides"]))}
        plan["control_commands"] = deepcopy(list(contract["control_overrides"]))
        plan["operating_mode"] = mode
        evidence_root = base_plan.get("evidence_root")
        if evidence_root is not None:
            if not isinstance(evidence_root, str) or not evidence_root.strip() or not evidence_root.startswith(("/", "\\")) and ":" not in evidence_root[:3]:
                raise _error(
                    "LCC_OPERATING_MODE_INVALID",
                    "evidence_root must be an absolute path when supplied.",
                    mode=mode,
                    reason="evidence_root_invalid",
                )
            plan["evidence_directory"] = f"{evidence_root.rstrip('/\\\\')}/{mode}"
        copies.append(ModeCopy(mode, _freeze(plan)))
    return tuple(copies)


def _exact_command_bindings(command_bindings: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    if not isinstance(command_bindings, Sequence) or isinstance(command_bindings, (str, bytes, bytearray)):
        raise _error("LCC_OPERATING_MODE_INVALID", "command_bindings must be an array.")
    result: dict[str, Mapping[str, Any]] = {}
    for index, binding in enumerate(command_bindings):
        component = binding.get("component") if isinstance(binding, Mapping) else None
        canonical = binding.get("canonical") if isinstance(binding, Mapping) else None
        if (
            not isinstance(canonical, str)
            or not canonical.strip()
            or not isinstance(component, Mapping)
            or any(not isinstance(component.get(field), str) or not component[field].strip() for field in ("canvas", "definition", "component_id"))
            or not isinstance(binding.get("parameter_name"), str)
            or not binding["parameter_name"].strip()
            or binding.get("read_back") is not True
        ):
            raise _error(
                "LCC_OPERATING_MODE_INVALID",
                "LCC switching requires an exact, read-back command binding.",
                index=index,
                reason="command_binding_inexact",
            )
        if canonical in result:
            raise _error(
                "LCC_OPERATING_MODE_INVALID",
                "LCC switching command bindings must be unique.",
                canonical=canonical,
                reason="command_binding_duplicated",
            )
        result[canonical] = binding
    return result


def validate_lcc_schedule(
    events: Sequence[Mapping[str, Any] | LccModeEvent],
    *,
    command_bindings: Sequence[Mapping[str, Any]] = (),
) -> tuple[LccModeEvent, ...]:
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes, bytearray)):
        raise _error("LCC_OPERATING_MODE_INVALID", "events must be an array.")
    bindings = _exact_command_bindings(command_bindings)
    result: list[LccModeEvent] = []
    seen: set[str] = set()
    previous = -1.0
    for index, raw in enumerate(events):
        if isinstance(raw, Mapping):
            wall_clock_fields = sorted(
                str(field)
                for field in raw
                if str(field).casefold() in {"timestamp", "wall_clock", "wall_clock_s", "datetime", "utc", "time"}
            )
            if wall_clock_fields:
                raise _error(
                    "LCC_OPERATING_MODE_INVALID",
                    "Wall-clock scheduling fields are forbidden; use EMTDC time_s only.",
                    index=index,
                    fields=wall_clock_fields,
                    reason="wall_clock_forbidden",
                )
        try:
            event = raw if isinstance(raw, LccModeEvent) else LccModeEvent(**raw)
        except (TypeError, ValueError) as error:
            raise _error("LCC_OPERATING_MODE_INVALID", str(error), index=index) from error
        if event.event_id in seen:
            raise _error("LCC_OPERATING_MODE_INVALID", "Duplicate event_id.", event_id=event.event_id)
        if event.time_s <= previous:
            raise _error("LCC_OPERATING_MODE_INVALID", "Event times must be strictly increasing.", event_id=event.event_id)
        binding = bindings.get(event.target)
        if binding is None:
            raise _error(
                "LCC_OPERATING_MODE_INVALID",
                "The event target has no exact writable command binding.",
                target=event.target,
                reason="command_binding_missing",
            )
        allowed_values = binding.get("allowed_values", ())
        if not any(type(event.value) is type(candidate) and event.value == candidate for candidate in allowed_values):
            raise _error(
                "LCC_OPERATING_MODE_INVALID",
                "The event value is not authorized by its exact command binding.",
                target=event.target,
                reason="command_value_not_allowed",
            )
        seen.add(event.event_id)
        previous = event.time_s
        result.append(event)
    return tuple(result)


def _switching_unavailable(message: str, *, reason: str, **details: Any) -> BackendError:
    return BackendError(
        "LCC_SWITCHING_UNAVAILABLE",
        message,
        "hvdc",
        "preflight_lcc_switching",
        _bounded_json({"reason": reason, **details}),
    )


async def preflight_lcc_switching(
    backend: Any,
    project_name: str,
    events: Sequence[Mapping[str, Any] | LccModeEvent],
    *,
    evidence: Any,
    profile: Mapping[str, Any],
    required_output_channels: Sequence[str],
) -> LccSwitchingToken:
    """Resolve all strict switching evidence without performing a write."""

    try:
        schedule = validate_lcc_schedule(events, command_bindings=profile.get("command_bindings", ()))
    except BackendError as error:
        raise _switching_unavailable(
            "The LCC schedule is not authorized by exact writable command bindings.",
            reason="schedule_binding_validation_failed",
            source_code=error.code,
        ) from error
    requests = [event.to_dict() for event in schedule]
    try:
        resolved = resolve_requested_commands(evidence, profile, requests)
    except BackendError as error:
        raise _switching_unavailable(
            "An LCC event did not resolve to one exact writable component parameter.",
            reason="command_binding_unresolved",
            source_code=error.code,
        ) from error
    capability_provider = getattr(backend, "get_timed_control_capabilities", None)
    if not callable(capability_provider):
        raise _switching_unavailable(
            "The backend does not expose strict timed-control capabilities.",
            reason="timing_capability_provider_missing",
        )
    try:
        capabilities = await capability_provider(project_name)
    except Exception as error:
        raise _switching_unavailable(
            "Timed-control capability inspection failed.",
            reason="timing_capability_inspection_failed",
            error_type=type(error).__name__,
        ) from error
    if (
        not isinstance(capabilities, Mapping)
        or capabilities.get("native_schedule") is not True
        or capabilities.get("simulation_clock") is not True
        or capabilities.get("time_basis") != "EMTDC"
    ):
        observed = dict(capabilities) if isinstance(capabilities, Mapping) else {}
        raise _switching_unavailable(
            "Strict LCC switching requires both a native EMTDC scheduler and a verified simulation clock.",
            reason="strict_emtdc_timing_unavailable",
            capabilities={
                "native_schedule": observed.get("native_schedule") is True,
                "simulation_clock": observed.get("simulation_clock") is True,
                "time_basis": observed.get("time_basis"),
            },
        )
    native_provider = getattr(backend, "schedule_timed_controls", None)
    clock_provider = getattr(backend, "get_simulation_time", None)
    if not callable(native_provider) or not callable(clock_provider):
        raise _switching_unavailable(
            "Declared strict LCC timing capabilities require callable native-schedule and simulation-clock providers.",
            reason="timing_provider_missing",
            providers={
                "native_schedule": callable(native_provider),
                "simulation_clock": callable(clock_provider),
            },
        )
    try:
        observed_time_s = float(await clock_provider(project_name))
    except Exception as error:
        raise _switching_unavailable(
            "The EMTDC simulation-clock provider could not be read during preflight.",
            reason="simulation_clock_read_failed",
            error_type=type(error).__name__,
        ) from error
    if not math.isfinite(observed_time_s) or observed_time_s < 0:
        raise _switching_unavailable(
            "The EMTDC simulation-clock provider returned an invalid value.",
            reason="simulation_clock_invalid",
        )
    past_events = [event.event_id for event in schedule if event.time_s < observed_time_s]
    if past_events:
        raise _switching_unavailable(
            "LCC event times must not precede the current EMTDC simulation time; equality is allowed.",
            reason="event_time_precedes_simulation_clock",
            observed_time_s=observed_time_s,
            event_ids=past_events,
        )
    try:
        timing_mode = await select_timing_mode(backend, project_name)
    except BackendError as error:
        raise _switching_unavailable(
            "The existing timing provider rejected strict EMTDC scheduling.",
            reason="timing_provider_rejected",
            source_code=error.code,
        ) from error
    if timing_mode != "native":
        raise _switching_unavailable(
            "Strict LCC switching requires native EMTDC-time registration.",
            reason="native_schedule_not_selected",
            timing_mode=timing_mode,
        )
    required = tuple(required_output_channels)
    if not required or len(set(required)) != len(required) or any(not isinstance(item, str) or not item.strip() for item in required):
        raise _switching_unavailable(
            "Strict LCC switching requires unique explicit output-channel canonicals.",
            reason="required_output_channels_invalid",
        )
    configured = [item for item in profile.get("result_channels", ()) if isinstance(item, Mapping)]
    selectors: list[dict[str, Any]] = []
    for canonical in required:
        matches = [dict(item) for item in configured if item.get("canonical") == canonical]
        if len(matches) != 1:
            raise _switching_unavailable(
                "A required LCC switching output selector is absent or ambiguous.",
                reason="output_selector_unresolved",
                canonical=canonical,
            )
        selectors.append(matches[0])
    try:
        await verify_exact_result_selectors(backend, project_name, selectors)
    except BackendError as error:
        raise _switching_unavailable(
            "Required LCC switching output channels are unavailable or ambiguous.",
            reason="required_output_channels_unavailable",
            source_code=error.code,
        ) from error
    bound_events = tuple({
        **event.to_dict(),
        "component_id": binding["component_id"],
        "parameter_name": binding["parameter_name"],
        "read_back": binding.get("read_back", False),
        "semantics": binding.get("semantics"),
    } for event, binding in zip(schedule, resolved))
    return _switching_token(
        project_name,
        bound_events,
        observed_time_s=observed_time_s,
        output_channels_verified=required,
    )


async def execute_lcc_schedule(
    backend: Any,
    project_name: str,
    token: LccSwitchingToken,
    *,
    confirm: bool,
) -> tuple[dict[str, Any], ...]:
    if confirm is not True:
        raise BackendError(
            "LCC_CONFIRMATION_REQUIRED",
            "LCC switching schedule registration requires explicit confirmation.",
            "hvdc",
            "execute_lcc_schedule",
            _bounded_json({"project_name": project_name}),
        )
    if (
        not isinstance(token, LccSwitchingToken)
        or getattr(token, "_seal", None) is not _TOKEN_SEAL
        or token.project_name != project_name
        or token.timing_mode != "native"
    ):
        raise _switching_unavailable(
            "Native LCC schedule dispatch requires the immutable token returned by final preflight.",
            reason="preflight_token_invalid",
        )
    try:
        dispatched = await dispatch_timed_events(
            backend,
            project_name,
            token.events,
            mode=token.timing_mode,
        )
    except BackendError as error:
        raise _switching_unavailable(
            "The native EMTDC scheduler did not accept the complete LCC schedule.",
            reason="native_schedule_registration_failed",
            source_code=error.code,
        ) from error
    return tuple(dict(item) for item in dispatched)


def mode_acceptance_contract(mode: str) -> dict[str, Any]:
    if mode not in SUPPORTED_MODES:
        raise _error("LCC_OPERATING_MODE_INVALID", "Unsupported operating mode.", mode=mode)
    earth_modes = {"monopolar_earth_return"}
    metallic_modes = {"monopolar_metallic_return", "metallic_return"}
    return_channels = (
        ["earth_return_current"]
        if mode in earth_modes
        else ["metallic_return_current"]
        if mode in metallic_modes
        else ["earth_return_current", "metallic_return_current"]
    )
    return {
        "mode": mode,
        "required_evidence": ["compile", "waveform", "return_current", "mode_transition"],
        "required_output_channels": [
            "positive_pole_current",
            "negative_pole_current",
            *return_channels,
            "mode_command",
            "mode_status",
            "dc_voltage",
        ],
        "required_metrics": [
            "return_current_closure_error",
            "pole_current_imbalance",
            "mode_transition_recovery_time_s",
            "mode_mismatch",
        ],
    }
