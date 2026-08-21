"""Operating-mode copies and strict EMTDC-clock schedule validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ....core.backend.base import BackendError
from .parametric_models import LccModeEvent

SUPPORTED_MODES = frozenset({"bipolar_run", "monopolar_earth_return", "monopolar_metallic_return", "metallic_return", "positive_pole_outage", "negative_pole_outage", "pole_outage", "scheduled_switching"})


@dataclass(frozen=True)
class ModeCopy:
    mode: str
    plan: Any


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", "validate_lcc_schedule", details)


def derive_mode_copies(base_plan: Any, modes: Sequence[str]) -> tuple[ModeCopy, ...]:
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
        copies.append(ModeCopy(mode, base_plan))
    return tuple(copies)


def validate_lcc_schedule(events: Sequence[Mapping[str, Any] | LccModeEvent], *, allowed_modes: Sequence[str] = SUPPORTED_MODES) -> tuple[LccModeEvent, ...]:
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes, bytearray)):
        raise _error("LCC_OPERATING_MODE_INVALID", "events must be an array.")
    allowed = set(allowed_modes)
    result: list[LccModeEvent] = []
    seen: set[str] = set()
    previous = -1.0
    for index, raw in enumerate(events):
        try:
            event = raw if isinstance(raw, LccModeEvent) else LccModeEvent(**raw)
        except (TypeError, ValueError) as error:
            raise _error("LCC_OPERATING_MODE_INVALID", str(error), index=index) from error
        if event.event_id in seen:
            raise _error("LCC_OPERATING_MODE_INVALID", "Duplicate event_id.", event_id=event.event_id)
        if event.time_s <= previous:
            raise _error("LCC_OPERATING_MODE_INVALID", "Event times must be strictly increasing.", event_id=event.event_id)
        if event.target not in allowed:
            raise _error("LCC_OPERATING_MODE_INVALID", "Unknown event target or mode binding.", target=event.target)
        seen.add(event.event_id)
        previous = event.time_s
        result.append(event)
    return tuple(result)


def mode_acceptance_contract(mode: str) -> dict[str, Any]:
    if mode not in SUPPORTED_MODES:
        raise _error("LCC_OPERATING_MODE_INVALID", "Unsupported operating mode.", mode=mode)
    return {"mode": mode, "required_evidence": ["compile", "waveform", "return_current", "mode_transition"]}
