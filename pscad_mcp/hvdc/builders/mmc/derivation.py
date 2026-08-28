"""Deterministic, versioned parameter derivation for both MMC engines."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ..common.serialization import content_hash
from .parametric_models import (
    MmcCandidate,
    MmcConstraintResult,
    MmcDerivedParameters,
    MmcParametricRequest,
    parse_parametric_request,
)


EQUATION_VERSION = "mmc-parametric-v1"

_PWM_REFERENCE: dict[str, Any] = {
    "evidence": "audited-template-reference-v1",
    "reference_cells_per_arm": 400,
    "arm_inductance_h": 0.05,
    "arm_resistance_ohm": 0.15,
    "stored_energy_mj": 40.0,
    "switching_frequency_hz": 1350.0,
    "control_sample_time_s": 50e-6,
    "control_bandwidth_hz": 100.0,
}

_AVM_REFERENCE: dict[str, Any] = {
    "evidence": "repository-avm-asset-v1",
    "reference_cells_per_arm": 400,
    "arm_inductance_h": 0.05,
    "arm_resistance_ohm": 0.15,
    "stored_energy_mj": 40.0,
    "control_sample_time_s": 100e-6,
    "control_bandwidth_hz": 80.0,
}


def _grid(station: object, power_mw: float, voltage_scale: float) -> tuple[float, float, float]:
    ac_voltage = float(getattr(station, "ac_voltage_kv"))
    scr = float(getattr(station, "short_circuit_ratio"))
    x_over_r = float(getattr(station, "x_over_r"))
    z_base_ohm = ac_voltage**2 / power_mw
    z_grid_ohm = z_base_ohm / scr * voltage_scale**2
    r_grid_ohm = z_grid_ohm / math.sqrt(1.0 + x_over_r**2)
    return z_grid_ohm, r_grid_ohm, r_grid_ohm * x_over_r


def _constraint(name: str, passed: bool, value: float | int, limit: float | int | str, units: str, message: str) -> MmcConstraintResult:
    return MmcConstraintResult(name, passed, value, limit, units, None if passed else message)


def _candidate(
    engine: str,
    index: int,
    purpose: str,
    parameters: dict[str, Any],
    settings: dict[str, Any],
    constraints: tuple[MmcConstraintResult, ...],
) -> MmcCandidate:
    payload = {"parameters": parameters, "settings": settings, "purpose": purpose, "engine": engine}
    prefix = "pwm" if engine == "detailed_pwm" else "avm"
    return MmcCandidate(
        candidate_id=f"{prefix}-{index}",
        engine=engine,
        purpose=purpose,
        parameters=parameters,
        settings=settings,
        constraints=constraints,
        parameter_hash=content_hash(payload),
    )


def _engine_candidates(
    engine: str,
    request: MmcParametricRequest,
    reference: Mapping[str, Any],
    common: dict[str, Any],
    constraints: tuple[MmcConstraintResult, ...],
) -> tuple[MmcCandidate, ...]:
    voltage_scale = common["voltage_scale"]
    power_scale = common["power_scale"]
    impedance_scale = common["impedance_scale"]
    cell_count = math.ceil(float(reference["reference_cells_per_arm"]) * voltage_scale)
    base_parameters: dict[str, Any] = {
        "requested_dc_voltage_kv": request.dc_voltage_kv,
        "requested_active_power_mw": request.active_power_mw,
        "rated_dc_voltage_kv": request.dc_voltage_kv,
        "rated_power_mw": request.active_power_mw,
        "reactive_power_mvar": request.reactive_power_mvar,
        "frequency_hz": request.frequency_hz,
        "station_p_ac_voltage_kv": request.station_p.ac_voltage_kv,
        "station_vdc_ac_voltage_kv": request.station_vdc.ac_voltage_kv,
        "dc_link_kind": request.dc_link.kind,
        "dc_link_length_km": request.dc_link.length_km,
        "power_reversal_time_s": request.power_reversal_time_s,
        "cell_count_per_arm": cell_count,
        "arm_inductance_h": float(reference["arm_inductance_h"]) * impedance_scale,
        "arm_resistance_ohm": float(reference["arm_resistance_ohm"]) * impedance_scale,
        "stored_energy_mj": float(reference["stored_energy_mj"]) * power_scale,
        "control_bandwidth_hz": float(reference["control_bandwidth_hz"]),
        "reference_evidence": str(reference["evidence"]),
        "transformer_rating_mva": common["transformer_rating_mva"],
        "station_p_grid_r_ohm": common["station_p_grid_r_ohm"],
        "station_p_grid_x_ohm": common["station_p_grid_x_ohm"],
        "station_vdc_grid_r_ohm": common["station_vdc_grid_r_ohm"],
        "station_vdc_grid_x_ohm": common["station_vdc_grid_x_ohm"],
        "line_resistance_ohm": common["line_resistance_ohm"],
        "equivalent_arm_capacitance_f": (
            2.0
            * float(reference["stored_energy_mj"])
            * power_scale
            * 1_000_000.0
            / 12.0
            / ((request.dc_voltage_kv * 1_000.0 / 2.0) ** 2)
        ),
        "loss_per_arm_mw": common["loss_budget_mw"] / 12.0,
    }
    for name, override in request.engineering_overrides.items():
        base_parameters[name] = override["value"]
    switching_frequency = float(reference.get("switching_frequency_hz", 0.0))
    control_sample = float(reference["control_sample_time_s"])
    nominal_step = min(control_sample / 5.0, 1.0 / switching_frequency / 40.0) if switching_frequency else control_sample / 2.0
    base_settings = {
        "time_step_s": nominal_step,
        "output_step_s": max(nominal_step, control_sample),
        "control_sample_time_s": control_sample,
        "switching_frequency_hz": switching_frequency,
    }
    variants = (
        ("nominal", {}, {}),
        ("numerical_stability", {"arm_inductance_h": base_parameters["arm_inductance_h"] * 1.10}, {"time_step_s": nominal_step * 0.5}),
        ("control_stability", {"control_bandwidth_hz": base_parameters["control_bandwidth_hz"] * 0.80}, {"time_step_s": nominal_step * 0.75}),
        ("energy_balance", {"stored_energy_mj": base_parameters["stored_energy_mj"] * 1.20}, {"time_step_s": nominal_step * 0.75}),
    )
    result: list[MmcCandidate] = []
    for index, (purpose, parameter_changes, setting_changes) in enumerate(variants):
        parameters = {**base_parameters, **parameter_changes}
        settings = {**base_settings, **setting_changes}
        result.append(_candidate(engine, index, purpose, parameters, settings, constraints))
    return tuple(result)


def derive_mmc_parameters(
    request: MmcParametricRequest | Mapping[str, Any],
    *,
    pwm_reference: Mapping[str, Any] | None = None,
    avm_reference: Mapping[str, Any] | None = None,
) -> MmcDerivedParameters:
    parsed = parse_parametric_request(request)
    voltage_scale = parsed.dc_voltage_kv / 640.0
    power_scale = parsed.active_power_mw / 1000.0
    impedance_scale = voltage_scale**2 / power_scale
    dc_current_ka = parsed.active_power_mw / parsed.dc_voltage_kv
    p_z, p_r, p_x = _grid(parsed.station_p, parsed.active_power_mw, voltage_scale)
    v_z, v_r, v_x = _grid(parsed.station_vdc, parsed.active_power_mw, voltage_scale)
    line_resistance = (0.015 if parsed.dc_link.kind == "overhead_line" else 0.01) * parsed.dc_link.length_km * impedance_scale
    line_drop_kv = dc_current_ka * line_resistance
    line_drop_pu = line_drop_kv / parsed.dc_voltage_kv
    transformer_rating = math.hypot(parsed.active_power_mw, parsed.reactive_power_mvar) * 1.10
    reversal_slope = 2.0 * parsed.active_power_mw / parsed.power_reversal_time_s
    modulation_index = 2.0 * math.sqrt(2.0) * max(parsed.station_p.ac_voltage_kv, parsed.station_vdc.ac_voltage_kv) / parsed.dc_voltage_kv
    reference_cells = math.ceil(400 * voltage_scale)
    resource_count = 12 * reference_cells
    common = {
        "dc_current_ka": dc_current_ka,
        "station_p_grid_impedance_ohm": p_z,
        "station_p_grid_r_ohm": p_r,
        "station_p_grid_x_ohm": p_x,
        "station_vdc_grid_impedance_ohm": v_z,
        "station_vdc_grid_r_ohm": v_r,
        "station_vdc_grid_x_ohm": v_x,
        "line_resistance_ohm": line_resistance,
        "line_drop_kv": line_drop_kv,
        "line_drop_pu": line_drop_pu,
        "transformer_rating_mva": transformer_rating,
        "requested_reversal_slope_mw_per_s": reversal_slope,
        "loss_budget_mw": parsed.active_power_mw * 0.015,
        "modulation_index": modulation_index,
        "voltage_scale": voltage_scale,
        "power_scale": power_scale,
        "impedance_scale": impedance_scale,
    }
    constraints = (
        _constraint("modulation_margin", modulation_index <= 1.15, modulation_index, 1.15, "pu", "Requested AC/DC voltage ratio exceeds modulation margin."),
        _constraint("energy_ripple", dc_current_ka / max(reference_cells, 1) <= 0.02, dc_current_ka / max(reference_cells, 1), 0.02, "pu", "Estimated arm-energy ripple exceeds the bound."),
        _constraint("dc_current", dc_current_ka <= 5.0, dc_current_ka, 5.0, "kA", "Requested DC current exceeds the supported reference envelope."),
        _constraint("line_drop", line_drop_pu <= 0.15, line_drop_pu, 0.15, "pu", "Estimated DC line drop exceeds the bound."),
        _constraint("grid_strength", min(parsed.station_p.short_circuit_ratio, parsed.station_vdc.short_circuit_ratio) >= 2.0, min(parsed.station_p.short_circuit_ratio, parsed.station_vdc.short_circuit_ratio), 2.0, "SCR", "Station grid strength is below the supported bound."),
        _constraint("control_bandwidth", parsed.power_reversal_time_s >= 0.05, parsed.power_reversal_time_s, 0.05, "s", "Requested reversal is faster than the control envelope."),
        _constraint("cell_count", reference_cells > 0, reference_cells, "> 0", "count", "Derived cell count is not positive."),
        _constraint("resource_limit", resource_count <= 20000, resource_count, 20000, "instances", "Detailed model resource limit is exceeded."),
    )
    requested_engines = (
        ("detailed_pwm", "average_value")
        if parsed.model_fidelity == "both"
        else (parsed.model_fidelity,)
    )
    candidates: list[MmcCandidate] = []
    for engine in requested_engines:
        reference = (pwm_reference or _PWM_REFERENCE) if engine == "detailed_pwm" else (avm_reference or _AVM_REFERENCE)
        candidates.extend(_engine_candidates(engine, parsed, reference, common, constraints))
    feasible = all(item.passed for item in constraints)
    return MmcDerivedParameters(
        equation_version=EQUATION_VERSION,
        model_fidelity=parsed.model_fidelity,
        request=parsed,
        common=common,
        candidates=tuple(candidates),
        constraints=constraints,
        feasible=feasible,
        diagnostics=tuple(item.message for item in constraints if item.message),
    )


__all__ = ["EQUATION_VERSION", "derive_mmc_parameters"]
