"""Deterministic, versioned parameter derivation for both MMC engines."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ....core.backend.base import BackendError
from ..common.serialization import content_hash
from .electrical import arm_energy
from .native_sizing import periodic_native_envelope
from .parametric_models import (
    MmcCandidate,
    MmcConstraintResult,
    MmcDerivedParameters,
    MmcParametricRequest,
    parse_parametric_request,
)


EQUATION_VERSION = "mmc-parametric-v5"

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


_OVERRIDE_UNIT_FACTORS = {
    "stored_energy_mj": {"MJ": 1.0, "J": 1e-6},
    "equivalent_arm_capacitance_f": {"F": 1.0, "uF": 1e-6},
    "dc_voltage_control_kp": {"MW/kV": 1.0},
    "dc_voltage_control_ti_s": {"s": 1.0, "ms": 1e-3},
}
_CAPACITOR_VOLTAGE_TARGET = "equivalent_capacitor_voltage_target_kv"


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", "derive_mmc_parameters", details)


def _synchronize_arm_energy(
    parameters: dict[str, Any],
    target_voltage_kv: float,
    *,
    capacitance_supplied: bool = False,
    energy_supplied: bool = False,
) -> None:
    voltage_v = target_voltage_kv * 1000.0
    energy_mj = float(parameters["stored_energy_mj"])
    if capacitance_supplied:
        capacitance_f = float(parameters["equivalent_arm_capacitance_f"])
        energy_from_capacitance_mj = arm_energy(capacitance_f, voltage_v) / 1e6 * 12.0
        if energy_supplied and not math.isclose(
            energy_mj, energy_from_capacitance_mj, rel_tol=1e-9, abs_tol=0.0
        ):
            raise _error(
                "MMC_ENERGY_INFEASIBLE",
                "Stored-energy and capacitance overrides disagree at the capacitor-voltage target.",
                stored_energy_mj=energy_mj,
                energy_from_capacitance_mj=energy_from_capacitance_mj,
                equivalent_capacitor_voltage_target_kv=target_voltage_kv,
            )
        if not energy_supplied:
            energy_mj = energy_from_capacitance_mj
    capacitance_f = 2.0 * (energy_mj / 12.0 * 1e6) / voltage_v / voltage_v
    arm_energy(capacitance_f, voltage_v)
    parameters.update(
        {
            "stored_energy_mj": energy_mj,
            "equivalent_arm_capacitance_f": capacitance_f,
            _CAPACITOR_VOLTAGE_TARGET: target_voltage_kv,
        }
    )


def _grid(station: object, power_mw: float) -> tuple[float, float, float]:
    ac_voltage = float(getattr(station, "ac_voltage_kv"))
    scr = float(getattr(station, "short_circuit_ratio"))
    x_over_r = float(getattr(station, "x_over_r"))
    z_base_ohm = ac_voltage**2 / power_mw
    z_grid_ohm = z_base_ohm / scr
    r_grid_ohm = z_grid_ohm / math.sqrt(1.0 + x_over_r**2)
    return z_grid_ohm, r_grid_ohm, r_grid_ohm * x_over_r


def _constraint(name: str, passed: bool, value: float | int, limit: float | int | str, units: str, message: str) -> MmcConstraintResult:
    return MmcConstraintResult(name, passed, value, limit, units, None if passed else message)


def _native_cable_line_parameters(request: MmcParametricRequest, profile: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, Mapping):
        raise _error("MMC_AVM_CABLE_PROFILE_INVALID", "Native cable profile must be a structured record.")
    resistances = profile.get("core_dc_resistance_ohm_per_km", ())
    if (request.dc_link.kind != "cable" or profile.get("schema_version") != 1
            or profile.get("conductors") != 2 or not isinstance(resistances, (list, tuple))
            or len(resistances) != 2
            or any(isinstance(value, bool) or not isinstance(value, (float, int))
                   or not math.isfinite(value) or value <= 0 for value in resistances)):
        raise _error("MMC_AVM_CABLE_PROFILE_INVALID", "Native AVM requires a finite two-core DC cable profile.")
    resistance = math.fsum(resistances) * request.dc_link.length_km
    drop = request.active_power_mw / request.dc_voltage_kv * resistance
    result = {
        "line_resistance_ohm": resistance,
        "line_drop_kv": drop,
        "line_drop_pu": drop / request.dc_voltage_kv,
        "native_cable_profile_hash": content_hash(profile),
    }
    capacitances = profile.get("core_sheath_capacitance_f_per_km")
    if capacitances is not None:
        if (not isinstance(capacitances, (list, tuple)) or len(capacitances) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in capacitances)):
            raise _error("MMC_AVM_CABLE_PROFILE_INVALID", "Native cable capacitance must contain two positive physical values.")
        result["line_differential_capacitance_f"] = request.dc_link.length_km / math.fsum(1 / v for v in capacitances)
    return result


def _size_native_candidate(parameters: dict, request: MmcParametricRequest) -> None:
    energy_locked = bool({"stored_energy_mj", "equivalent_arm_capacitance_f"} & request.engineering_overrides.keys())
    modulations = (parameters["base_modulation_index"],) if "base_modulation_index" in request.engineering_overrides else (0.90, 0.85, 0.80, 0.75, 0.70)
    first = None
    for modulation in modulations:
        trial = {**parameters, "base_modulation_index": modulation}
        try:
            sizing = periodic_native_envelope(trial)
            if not energy_locked:
                quantum = 5 * trial["rated_power_mw"] / 1000
                trial["stored_energy_mj"] = max(trial["stored_energy_mj"], math.ceil(sizing["required_stored_energy_mj"] / quantum) * quantum)
                sizing = periodic_native_envelope(trial)
            trial["native_periodic_sizing"] = sizing
        except ValueError as error:
            trial["native_periodic_sizing"] = {"error": str(error), "energy_feasible": False, "modulation_feasible": False}
        if first is None:
            first = trial
        if trial["native_periodic_sizing"]["energy_feasible"] and trial["native_periodic_sizing"]["modulation_feasible"]:
            parameters.update(trial)
            return
    parameters.update(first)


def _native_sizing_constraints(parameters: dict) -> tuple[MmcConstraintResult, ...]:
    try:
        sizing = periodic_native_envelope(parameters)
        parameters["native_periodic_sizing"] = sizing
    except ValueError as error:
        return (_constraint("native_operating_point", False, 0, "physical AC/DC solution", "1", str(error)),)
    return (
        _constraint("native_valve_modulation", sizing["maximum_converter_modulation"] <= 0.98,
                    sizing["maximum_converter_modulation"], 0.98, "pu", "Valve-side voltage and arm impedance exceed the native controller's voltage range."),
        _constraint("native_insertion_margin", sizing["minimum_insertion_margin"] >= 0.05,
                    sizing["minimum_insertion_margin"], 0.05, "pu", "Native SVM insertion lacks the required margin after capacitor ripple and energy reserve."),
        _constraint("native_arm_energy", sizing["energy_feasible"], parameters["stored_energy_mj"],
                    sizing["required_stored_energy_mj"], "MJ", "Native arm energy is below the periodic power integral including mean-energy reserve."),
    )


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
        "loss_per_arm_mw": common["loss_budget_mw"] / 12.0,
    }
    if "native_cable_profile_hash" in common:
        base_parameters["native_cable_profile_hash"] = common["native_cable_profile_hash"]
        base_parameters["dc_grounding_resistance_ohm"] = 1e6
        base_parameters["valve_grounding_resistance_ohm"] = 1e6
        # This is a complete averaged arm, not one individual Master switch.
        # Preserve its validated off-state resistance; 1 Mohm would create
        # several MW of unintended stack and capacitor-clamp leakage.
        base_parameters["arm_off_state_resistance_ohm"] = 1e8
        base_parameters["base_modulation_index"] = 0.9
        base_parameters["dc_reactor_inductance_h"] = 0.05 * impedance_scale
        base_parameters["maximum_precharge_time_s"] = 1.0
        base_parameters["startup_charge_time_s"] = 0.5
        base_parameters["maximum_conditioning_time_s"] = 1.5
        if "line_differential_capacitance_f" in common:
            capacitance = float(common["line_differential_capacitance_f"])
            base_parameters["line_differential_capacitance_f"] = capacitance
            vdc = request.dc_voltage_kv
            line_r = common["line_resistance_ohm"]
            received = request.active_power_mw + common["loss_budget_mw"] / 2
            disc = vdc**2 - 4 * line_r * received
            if disc > 0:
                current = 2 * received / (vdc + math.sqrt(disc))
                negative_conductance = 2 * line_r * current**2 / (vdc - 2 * line_r * current)
                natural_frequency = 2 * math.pi * 2.0
                kp = 2 * 0.85 * natural_frequency * capacitance * vdc + negative_conductance
                base_parameters["dc_voltage_control_kp"] = kp
                base_parameters["dc_voltage_control_ti_s"] = kp / (capacitance * vdc * natural_frequency**2)
    for name, override in request.engineering_overrides.items():
        if name == _CAPACITOR_VOLTAGE_TARGET:
            raise _error(
                "MMC_REQUEST_INVALID",
                "The equivalent capacitor-voltage target is fixed at half the requested DC voltage.",
                field=f"engineering_overrides.{name}",
            )
        unit_factors = _OVERRIDE_UNIT_FACTORS.get(name)
        if unit_factors is None:
            base_parameters[name] = override["value"]
            continue
        unit = override["unit"]
        if unit not in unit_factors:
            raise _error(
                "MMC_REQUEST_INVALID",
                "The engineering override has an incompatible unit.",
                field=f"engineering_overrides.{name}",
                unit=unit,
                supported_units=sorted(unit_factors),
            )
        base_parameters[name] = override["value"] * unit_factors[unit]
    # Preserve the existing half-normalized capacitor-voltage convention.
    capacitor_voltage_target_kv = request.dc_voltage_kv / 2.0
    _synchronize_arm_energy(
        base_parameters,
        capacitor_voltage_target_kv,
        capacitance_supplied="equivalent_arm_capacitance_f" in request.engineering_overrides,
        energy_supplied="stored_energy_mj" in request.engineering_overrides,
    )
    if "native_cable_profile_hash" in common:
        _size_native_candidate(base_parameters, request)
        _synchronize_arm_energy(base_parameters, capacitor_voltage_target_kv)
        valve_voltage = float(base_parameters["base_modulation_index"]) * request.dc_voltage_kv * math.sqrt(3.0 / 8.0)
        ac_peak = math.sqrt(2.0) * math.hypot(request.active_power_mw, request.reactive_power_mvar) / (math.sqrt(3.0) * valve_voltage)
        base_parameters["precharge_current_limit_ka"] = 1.25 * (common["dc_current_ka"] / 3.0 + ac_peak / 2.0)
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
        if "native_cable_profile_hash" in common and purpose == "energy_balance" and {"stored_energy_mj", "equivalent_arm_capacitance_f"} & request.engineering_overrides.keys():
            parameter_changes = {}  # An explicit storage value is a constraint.
        parameters = {**base_parameters, **parameter_changes}
        _synchronize_arm_energy(parameters, capacitor_voltage_target_kv)
        settings = {**base_settings, **setting_changes}
        candidate_constraints = constraints + (_native_sizing_constraints(parameters) if "native_cable_profile_hash" in common else ())
        result.append(_candidate(engine, index, purpose, parameters, settings, candidate_constraints))
    return tuple(result)


def derive_mmc_parameters(
    request: MmcParametricRequest | Mapping[str, Any],
    *,
    pwm_reference: Mapping[str, Any] | None = None,
    avm_reference: Mapping[str, Any] | None = None,
    avm_cable_profile: Mapping[str, Any] | None = None,
) -> MmcDerivedParameters:
    parsed = parse_parametric_request(request)
    voltage_scale = parsed.dc_voltage_kv / 640.0
    power_scale = parsed.active_power_mw / 1000.0
    impedance_scale = voltage_scale**2 / power_scale
    dc_current_ka = parsed.active_power_mw / parsed.dc_voltage_kv
    p_z, p_r, p_x = _grid(parsed.station_p, parsed.active_power_mw)
    v_z, v_r, v_x = _grid(parsed.station_vdc, parsed.active_power_mw)
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
    engine_line_parameters: dict[str, dict[str, Any]] = {}
    all_constraints: list[MmcConstraintResult] = []
    for engine in requested_engines:
        reference = (pwm_reference or _PWM_REFERENCE) if engine == "detailed_pwm" else (avm_reference or _AVM_REFERENCE)
        engine_common = dict(common)
        engine_constraints = constraints
        if engine == "average_value" and avm_cable_profile is not None:
            engine_common.update(_native_cable_line_parameters(parsed, avm_cable_profile))
            drop = engine_common["line_drop_pu"]
            engine_constraints = tuple(
                _constraint("line_drop", drop <= 0.15, drop, 0.15, "pu", "Physical native cable DC line drop exceeds the bound.")
                if item.name == "line_drop" else item for item in constraints if item.name not in {"modulation_margin", "energy_ripple"}
            )
        engine_line_parameters[engine] = {
            name: engine_common[name] for name in ("line_resistance_ohm", "line_drop_kv", "line_drop_pu")
        }
        engine_candidates = _engine_candidates(engine, parsed, reference, engine_common, engine_constraints)
        candidates.extend(engine_candidates)
        engine_constraints = engine_candidates[0].constraints
        for item in engine_constraints:
            if item.name == "line_drop" and len(requested_engines) > 1 and avm_cable_profile is not None:
                all_constraints.append(replace(item, name=f"{engine}:line_drop"))
            elif item not in all_constraints:
                all_constraints.append(item)
    if avm_cable_profile is not None and "average_value" in requested_engines:
        if len(requested_engines) == 1:
            common.update(engine_line_parameters["average_value"])
            common.pop("modulation_index", None)
            common["native_periodic_sizing"] = candidates[0].parameters["native_periodic_sizing"]
        else:
            for name in ("line_resistance_ohm", "line_drop_kv", "line_drop_pu"):
                common.pop(name)
            common["engine_line_parameters"] = engine_line_parameters
    feasible = all(item.passed for item in all_constraints)
    return MmcDerivedParameters(
        equation_version=EQUATION_VERSION,
        model_fidelity=parsed.model_fidelity,
        request=parsed,
        common=common,
        candidates=tuple(candidates),
        constraints=tuple(all_constraints),
        feasible=feasible,
        diagnostics=tuple(item.message for item in all_constraints if item.message),
    )


__all__ = ["EQUATION_VERSION", "derive_mmc_parameters"]
