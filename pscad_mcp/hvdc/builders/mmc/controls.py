"""Fixed MMC control contracts and a pure operating-sequence reducer."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ....core.backend.base import BackendError
from ..common.records import JsonRecord, freeze


def _error(message: str, operation: str = "mmc_controls", **details: Any) -> BackendError:
    return BackendError("MMC_CONTROL_INFEASIBLE", message, "hvdc", operation, details)


def _finite(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise _error(f"{context} must be finite.", context=context)
    result = float(value)
    if result <= 0:
        raise _error(f"{context} must be positive.", context=context)
    return result


class MmcSequencePhaseName(str, Enum):
    BLOCKED_PRECHARGE = "blocked_precharge"
    READY_TO_DEBLOCK = "ready_to_deblock"
    FORWARD_RAMP = "forward_ramp"
    FORWARD_STEADY = "forward_steady"
    POWER_REVERSAL = "power_reversal"
    REVERSE_STEADY = "reverse_steady"
    FAILED = "failed"


_RUNNING_PHASES = tuple(
    phase.value for phase in (
        MmcSequencePhaseName.BLOCKED_PRECHARGE,
        MmcSequencePhaseName.READY_TO_DEBLOCK,
        MmcSequencePhaseName.FORWARD_RAMP,
        MmcSequencePhaseName.FORWARD_STEADY,
        MmcSequencePhaseName.POWER_REVERSAL,
        MmcSequencePhaseName.REVERSE_STEADY,
    )
)


@dataclass(frozen=True)
class MmcBandwidthConfig(JsonRecord):
    pll_hz: float
    outer_hz: float
    energy_hz: float
    circulating_hz: float
    inner_hz: float

    def __post_init__(self) -> None:
        values = tuple(_finite(value, name) for name, value in (
            ("pll_hz", self.pll_hz),
            ("outer_hz", self.outer_hz),
            ("energy_hz", self.energy_hz),
            ("circulating_hz", self.circulating_hz),
            ("inner_hz", self.inner_hz),
        ))
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise _error("PLL, outer, energy, circulating, and inner bandwidths must be strictly separated.", context="bandwidths")
        object.__setattr__(self, "pll_hz", values[0])
        object.__setattr__(self, "outer_hz", values[1])
        object.__setattr__(self, "energy_hz", values[2])
        object.__setattr__(self, "circulating_hz", values[3])
        object.__setattr__(self, "inner_hz", values[4])

    def as_tuple(self) -> tuple[float, ...]:
        return (self.pll_hz, self.outer_hz, self.energy_hz, self.circulating_hz, self.inner_hz)


@dataclass(frozen=True)
class MmcStationControl(JsonRecord):
    station_id: str
    active_control: str | None
    reactive_control: str
    dc_voltage_control: str | None
    bandwidths: MmcBandwidthConfig
    anti_windup_limits: dict[str, float]
    current_limit_ka: float = 2.0
    energy_min_j: float = 0.0
    energy_max_j: float = 1.0e9
    modulation_margin_min: float = 0.05

    def __post_init__(self) -> None:
        if self.station_id not in {"STATION_P", "STATION_VDC"}:
            raise _error("station_id must be STATION_P or STATION_VDC.", context="station_id")
        expected = self.station_id == "STATION_P"
        if (self.active_control is not None) != expected or (self.dc_voltage_control is not None) == expected:
            raise _error("station control assignment does not match the fixed P/VDC roles.", context=self.station_id)
        if self.reactive_control != "Q":
            raise _error("both stations must use Q control for reactive power.", context=self.station_id)
        object.__setattr__(self, "anti_windup_limits", freeze(self.anti_windup_limits))
        for name, value in self.anti_windup_limits.items():
            _finite(value, f"anti_windup_limits.{name}")
        for name, value in (("current_limit_ka", self.current_limit_ka), ("energy_max_j", self.energy_max_j), ("modulation_margin_min", self.modulation_margin_min)):
            _finite(value, name)
        if isinstance(self.energy_min_j, bool) or not isinstance(self.energy_min_j, (int, float)) or not math.isfinite(float(self.energy_min_j)) or self.energy_min_j < 0 or self.energy_min_j >= self.energy_max_j:
            raise _error("energy limits must be finite, non-negative, and increasing.", context=self.station_id)


@dataclass(frozen=True)
class MmcControlSet(JsonRecord):
    stations: tuple[MmcStationControl, ...]
    bandwidths: MmcBandwidthConfig
    sequence: tuple[MmcSequencePhaseName, ...] = tuple(MmcSequencePhaseName(value) for value in _RUNNING_PHASES)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stations", tuple(self.stations))
        object.__setattr__(self, "sequence", tuple(self.sequence))
        if {station.station_id for station in self.stations} != {"STATION_P", "STATION_VDC"}:
            raise _error("fixed control set requires STATION_P and STATION_VDC.", context="stations")
        if any(station.bandwidths != self.bandwidths for station in self.stations):
            raise _error("station bandwidths must match the fixed control set.", context="bandwidths")
        if tuple(phase.value for phase in self.sequence) != _RUNNING_PHASES:
            raise _error("fixed control set sequence is not the declared six-phase sequence.", context="sequence")


def fixed_control_set() -> MmcControlSet:
    """Return the immutable Stage A control contract."""

    bandwidths = MmcBandwidthConfig(pll_hz=10.0, outer_hz=20.0, energy_hz=40.0, circulating_hz=60.0, inner_hz=120.0)
    return MmcControlSet(
        stations=(
            MmcStationControl(
                station_id="STATION_P",
                active_control="P",
                reactive_control="Q",
                dc_voltage_control=None,
                bandwidths=bandwidths,
                anti_windup_limits={"active_power": 1000.0, "reactive_power": 500.0, "current": 2.0, "energy": 1.0e9},
                current_limit_ka=2.0,
                energy_min_j=0.0,
                energy_max_j=1.0e9,
                modulation_margin_min=0.05,
            ),
            MmcStationControl(
                station_id="STATION_VDC",
                active_control=None,
                reactive_control="Q",
                dc_voltage_control="Vdc",
                bandwidths=bandwidths,
                anti_windup_limits={"dc_voltage": 640.0, "reactive_power": 500.0, "current": 2.0, "energy": 1.0e9},
                current_limit_ka=2.0,
                energy_min_j=0.0,
                energy_max_j=1.0e9,
                modulation_margin_min=0.05,
            ),
        ),
        bandwidths=bandwidths,
    )


load_fixed_controls = fixed_control_set


@dataclass(frozen=True)
class MmcSequenceObservation(JsonRecord):
    ready: bool = False
    deblock: bool = False
    ramp_complete: bool = False
    power_reversal: bool = False
    reverse_settled: bool = False
    reverse_steady: bool = False
    pll_locked: bool = True
    energy_ok: bool = True
    current_ok: bool = True
    modulation_ok: bool = True
    protection_active: bool = False

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if not isinstance(getattr(self, name), bool):
                raise _error(f"{name} must be boolean.", context=name)


@dataclass(frozen=True)
class MmcTransitionResult(JsonRecord):
    phase: str
    accepted: bool
    observed: dict[str, Any]
    failure_code: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed", freeze(self.observed))


def _observation(value: MmcSequenceObservation | Mapping[str, Any]) -> MmcSequenceObservation:
    if isinstance(value, MmcSequenceObservation):
        return value
    if not isinstance(value, Mapping):
        raise _error("sequence observation must be an object.", context="observation")
    allowed = set(MmcSequenceObservation.__dataclass_fields__)
    if any(not isinstance(key, str) for key in value):
        raise _error("sequence observation keys must be strings.", context="observation")
    unknown = sorted(key for key in value if key not in allowed)
    if unknown:
        raise _error("sequence observation contains unknown fields.", context="observation", unknown=unknown)
    return MmcSequenceObservation(**dict(value))


def _failed(observation: MmcSequenceObservation, reason: str) -> MmcTransitionResult:
    return MmcTransitionResult(phase=MmcSequencePhaseName.FAILED.value, accepted=False, observed=observation.to_dict(), failure_code="MMC_CONTROL_INFEASIBLE", reason=reason)


def reduce_sequence(current_phase: str | MmcSequencePhaseName, observation: MmcSequenceObservation | Mapping[str, Any]) -> MmcTransitionResult:
    """Apply one observed-condition reduction without reading or mutating time."""

    phase = current_phase.value if isinstance(current_phase, MmcSequencePhaseName) else current_phase
    if phase not in _RUNNING_PHASES and phase != MmcSequencePhaseName.FAILED.value:
        raise _error("unknown sequence phase.", context="current_phase", phase=phase)
    observed = _observation(observation)
    if phase == MmcSequencePhaseName.FAILED.value:
        return MmcTransitionResult(phase=phase, accepted=False, observed=observed.to_dict(), reason="already_failed")
    if observed.protection_active or not observed.pll_locked or not observed.energy_ok or not observed.current_ok or not observed.modulation_ok:
        return _failed(observed, "protection, PLL, energy, current, or modulation condition failed")
    if phase == MmcSequencePhaseName.BLOCKED_PRECHARGE.value:
        if observed.deblock and not observed.ready:
            return _failed(observed, "deblock requested before readiness")
        if observed.ready:
            return MmcTransitionResult(MmcSequencePhaseName.READY_TO_DEBLOCK.value, True, observed.to_dict(), reason="ready")
    elif phase == MmcSequencePhaseName.READY_TO_DEBLOCK.value:
        if observed.deblock:
            if not observed.ready:
                return _failed(observed, "deblock requested before readiness")
            return MmcTransitionResult(MmcSequencePhaseName.FORWARD_RAMP.value, True, observed.to_dict(), reason="deblocked")
    elif phase == MmcSequencePhaseName.FORWARD_RAMP.value:
        if observed.ramp_complete:
            return MmcTransitionResult(MmcSequencePhaseName.FORWARD_STEADY.value, True, observed.to_dict(), reason="forward ramp complete")
    elif phase == MmcSequencePhaseName.FORWARD_STEADY.value:
        if observed.reverse_steady and not observed.power_reversal:
            return _failed(observed, "reverse steady requested before power reversal")
        if observed.power_reversal:
            return MmcTransitionResult(MmcSequencePhaseName.POWER_REVERSAL.value, True, observed.to_dict(), reason="power reversal started")
    elif phase == MmcSequencePhaseName.POWER_REVERSAL.value:
        if observed.reverse_steady and not observed.reverse_settled:
            return _failed(observed, "reverse steady requested before reverse settling")
        if observed.reverse_settled:
            return MmcTransitionResult(MmcSequencePhaseName.REVERSE_STEADY.value, True, observed.to_dict(), reason="reverse settled")
    return MmcTransitionResult(phase=phase, accepted=False, observed=observed.to_dict(), reason="condition_not_met")


transition_sequence = reduce_sequence


__all__ = [
    "MmcBandwidthConfig",
    "MmcControlSet",
    "MmcSequenceObservation",
    "MmcSequencePhaseName",
    "MmcStationControl",
    "MmcTransitionResult",
    "fixed_control_set",
    "load_fixed_controls",
    "reduce_sequence",
    "transition_sequence",
]
