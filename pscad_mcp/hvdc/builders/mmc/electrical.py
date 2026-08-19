"""Finite, deterministic calculations for the MMC average-arm contract."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ....core.backend.base import BackendError


def _error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _finite(value: Any, context: str, *, code: str = "MMC_MODEL_UNSUPPORTED", nonnegative: bool = False, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(code, f"{context} must be a real number.", "mmc_electrical", context=context)
    number = float(value)
    if not math.isfinite(number):
        raise _error(code, f"{context} must be finite.", "mmc_electrical", context=context)
    if positive and number <= 0:
        raise _error(code, f"{context} must be positive.", "mmc_electrical", context=context)
    if nonnegative and number < 0:
        raise _error(code, f"{context} must be non-negative.", "mmc_electrical", context=context)
    return number


def arm_currents(i_dc: float, i_phase: float, i_circulating: float) -> tuple[float, float]:
    """Return upper and lower arm current from the declared sign convention."""

    dc = _finite(i_dc, "i_dc")
    phase = _finite(i_phase, "i_phase")
    circulating = _finite(i_circulating, "i_circulating")
    upper = dc / 3.0 + phase / 2.0 + circulating
    lower = dc / 3.0 - phase / 2.0 + circulating
    if not math.isfinite(upper) or not math.isfinite(lower):
        raise _error("MMC_MODEL_UNSUPPORTED", "arm current calculation is non-finite.", "arm_currents")
    return upper, lower


def arm_energy(capacitance_f: float, capacitor_voltage_v: float) -> float:
    """Return ``0.5 * C_eq * V_cap_eq²`` in joules."""

    capacitance = _finite(capacitance_f, "capacitance_f", code="MMC_ENERGY_INFEASIBLE", positive=True)
    voltage = _finite(capacitor_voltage_v, "capacitor_voltage_v", code="MMC_ENERGY_INFEASIBLE", nonnegative=True)
    energy = 0.5 * capacitance * voltage * voltage
    if not math.isfinite(energy) or energy < 0:
        raise _error("MMC_ENERGY_INFEASIBLE", "arm energy is invalid.", "arm_energy")
    return energy


def equivalent_capacitor_voltage(energy_j: float, capacitance_f: float) -> float:
    """Return the non-negative capacitor voltage equivalent to stored energy."""

    energy = _finite(energy_j, "energy_j", code="MMC_ENERGY_INFEASIBLE", nonnegative=True)
    capacitance = _finite(capacitance_f, "capacitance_f", code="MMC_ENERGY_INFEASIBLE", positive=True)
    voltage = math.sqrt(2.0 * energy / capacitance)
    if not math.isfinite(voltage):
        raise _error("MMC_ENERGY_INFEASIBLE", "equivalent capacitor voltage is non-finite.", "equivalent_capacitor_voltage")
    return voltage


def clip_modulation(value: float, lower: float = 0.0, upper: float = 1.0) -> tuple[float, float, float, bool]:
    """Return unclipped value, clipped value, remaining margin, and saturation flag."""

    unclipped = _finite(value, "modulation_request", code="MMC_MODULATION_INFEASIBLE")
    minimum = _finite(lower, "modulation_lower_bound", code="MMC_MODULATION_INFEASIBLE", nonnegative=True)
    maximum = _finite(upper, "modulation_upper_bound", code="MMC_MODULATION_INFEASIBLE", nonnegative=True)
    if minimum >= maximum:
        raise _error("MMC_MODULATION_INFEASIBLE", "modulation bounds must be increasing.", "clip_modulation")
    clipped = min(max(unclipped, minimum), maximum)
    margin = min(clipped - minimum, maximum - clipped)
    saturated = unclipped < minimum or unclipped > maximum
    return unclipped, clipped, margin, saturated


def conduction_loss(current_a: float, resistance_ohm: float, threshold_voltage_v: float = 0.0) -> float:
    """Return the explicit equivalent conduction loss ``I²R + |I|Vth``."""

    current = _finite(current_a, "current_a", code="MMC_ENERGY_INFEASIBLE")
    resistance = _finite(resistance_ohm, "resistance_ohm", code="MMC_ENERGY_INFEASIBLE", nonnegative=True)
    threshold = _finite(threshold_voltage_v, "threshold_voltage_v", code="MMC_ENERGY_INFEASIBLE", nonnegative=True)
    loss = current * current * resistance + abs(current) * threshold
    if not math.isfinite(loss):
        raise _error("MMC_ENERGY_INFEASIBLE", "conduction loss is non-finite.", "conduction_loss")
    return loss


def equivalent_switching_loss(current_a: float, switching_loss_coefficient_w_per_a: float) -> float:
    """Return the Stage A equivalent switching loss ``k_sw |I|``."""

    current = _finite(current_a, "current_a", code="MMC_ENERGY_INFEASIBLE")
    coefficient = _finite(switching_loss_coefficient_w_per_a, "switching_loss_coefficient_w_per_a", code="MMC_ENERGY_INFEASIBLE", nonnegative=True)
    loss = abs(current) * coefficient
    if not math.isfinite(loss):
        raise _error("MMC_ENERGY_INFEASIBLE", "equivalent switching loss is non-finite.", "equivalent_switching_loss")
    return loss


@dataclass(frozen=True)
class ArmLoss:
    conduction_w: float
    switching_w: float

    @property
    def total_w(self) -> float:
        return self.conduction_w + self.switching_w


def arm_losses(current_a: float, resistance_ohm: float, switching_loss_coefficient_w_per_a: float, threshold_voltage_v: float = 0.0) -> ArmLoss:
    """Return explicit conduction and equivalent switching losses."""

    return ArmLoss(
        conduction_w=conduction_loss(current_a, resistance_ohm, threshold_voltage_v),
        switching_w=equivalent_switching_loss(current_a, switching_loss_coefficient_w_per_a),
    )


def arm_energy_derivative(inserted_voltage_v: float, arm_current_a: float, loss_w: float) -> float:
    """Return ``v_inserted * i_arm - p_loss_arm`` with a strict loss guard."""

    voltage = _finite(inserted_voltage_v, "inserted_voltage_v", code="MMC_ENERGY_INFEASIBLE")
    current = _finite(arm_current_a, "arm_current_a", code="MMC_ENERGY_INFEASIBLE")
    loss = _finite(loss_w, "loss_w", code="MMC_ENERGY_INFEASIBLE", nonnegative=True)
    inserted_power = voltage * current
    if not math.isfinite(inserted_power):
        raise _error("MMC_ENERGY_INFEASIBLE", "inserted arm power is non-finite.", "arm_energy_derivative")
    if loss > inserted_power:
        raise _error("MMC_ENERGY_INFEASIBLE", "arm loss exceeds inserted arm power.", "arm_energy_derivative", inserted_power_w=inserted_power, loss_w=loss)
    derivative = inserted_power - loss
    if not math.isfinite(derivative):
        raise _error("MMC_ENERGY_INFEASIBLE", "arm energy derivative is non-finite.", "arm_energy_derivative")
    return derivative


@dataclass(frozen=True)
class ArmEnergyStep:
    energy_j: float
    derivative_w: float
    inserted_power_w: float
    loss_w: float
    dt_s: float


def arm_energy_step(initial_energy_j: float, inserted_voltage_v: float, arm_current_a: float, loss_w: float, dt_s: float) -> ArmEnergyStep:
    """Advance stored arm energy by one finite time step."""

    initial = _finite(initial_energy_j, "initial_energy_j", code="MMC_ENERGY_INFEASIBLE", nonnegative=True)
    dt = _finite(dt_s, "dt_s", code="MMC_ENERGY_INFEASIBLE", positive=True)
    derivative = arm_energy_derivative(inserted_voltage_v, arm_current_a, loss_w)
    inserted_power = _finite(inserted_voltage_v, "inserted_voltage_v", code="MMC_ENERGY_INFEASIBLE") * _finite(arm_current_a, "arm_current_a", code="MMC_ENERGY_INFEASIBLE")
    next_energy = initial + derivative * dt
    if not math.isfinite(next_energy) or next_energy < 0:
        raise _error("MMC_ENERGY_INFEASIBLE", "arm energy would become negative or non-finite.", "arm_energy_step", energy_j=next_energy)
    return ArmEnergyStep(energy_j=next_energy, derivative_w=derivative, inserted_power_w=inserted_power, loss_w=_finite(loss_w, "loss_w", code="MMC_ENERGY_INFEASIBLE", nonnegative=True), dt_s=dt)


@dataclass(frozen=True)
class SaturationDuration:
    last_time_s: float | None = None
    duration_s: float = 0.0


def accumulate_saturation_duration(state: SaturationDuration, time_s: float, saturated: bool) -> SaturationDuration:
    """Accumulate only saturated intervals while requiring monotonic time."""

    if not isinstance(state, SaturationDuration):
        raise _error("MMC_MODULATION_INFEASIBLE", "state must be SaturationDuration.", "accumulate_saturation_duration")
    if not isinstance(saturated, bool):
        raise _error("MMC_MODULATION_INFEASIBLE", "saturated must be boolean.", "accumulate_saturation_duration")
    current = _finite(time_s, "time_s", code="MMC_MODULATION_INFEASIBLE", nonnegative=True)
    duration = _finite(state.duration_s, "duration_s", code="MMC_MODULATION_INFEASIBLE", nonnegative=True)
    if state.last_time_s is None:
        return SaturationDuration(last_time_s=current, duration_s=duration)
    previous = _finite(state.last_time_s, "last_time_s", code="MMC_MODULATION_INFEASIBLE", nonnegative=True)
    if current < previous:
        raise _error("MMC_MODULATION_INFEASIBLE", "saturation time must be monotonic.", "accumulate_saturation_duration", previous_time_s=previous, time_s=current)
    increment = current - previous if saturated else 0.0
    total = duration + increment
    if not math.isfinite(total):
        raise _error("MMC_MODULATION_INFEASIBLE", "saturation duration is non-finite.", "accumulate_saturation_duration")
    return SaturationDuration(last_time_s=current, duration_s=total)


energy_derivative = arm_energy_derivative
advance_arm_energy = arm_energy_step
accumulate_modulation_saturation = accumulate_saturation_duration


__all__ = [
    "ArmEnergyStep",
    "ArmLoss",
    "SaturationDuration",
    "accumulate_modulation_saturation",
    "accumulate_saturation_duration",
    "advance_arm_energy",
    "arm_currents",
    "arm_energy",
    "arm_energy_derivative",
    "arm_energy_step",
    "arm_losses",
    "clip_modulation",
    "conduction_loss",
    "energy_derivative",
    "equivalent_capacitor_voltage",
    "equivalent_switching_loss",
]
