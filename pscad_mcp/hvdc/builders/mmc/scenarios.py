"""Deterministic executable normal and fault recommendations for MMC plans."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from ...profiles import bind_profile_project, load_profile
from .parametric_models import MmcDerivedParameters, MmcScenarioRecommendation


_SCENARIOS = (
    "startup",
    "forward_steady",
    "active_power_step",
    "reactive_power_step",
    "power_reversal",
    "reverse_steady",
    "ac_three_phase_fault",
    "ac_single_line_ground_fault",
    "dc_pole_to_pole_fault",
    "dc_pole_to_ground_fault",
    "post_fault_recovery",
)

_UNITS = {
    "station_p_active_power": "MW",
    "station_vdc_active_power": "MW",
    "station_p_reactive_power": "MVAr",
    "station_vdc_reactive_power": "MVAr",
    "ac_voltage": "kV",
    "ac_current": "kA",
    "dc_voltage": "kV",
    "dc_current": "kA",
    "arm_current": "kA",
    "equivalent_capacitor_voltage": "kV",
    "circulating_current": "kA",
    "modulation_margin": "pu",
    "block_status": "1",
    "ac_breaker_status": "1",
    "dc_breaker_status": "1",
    "diode_equivalent_current": "kA",
}


def _error(message: str, **details: object) -> BackendError:
    return BackendError(
        "MMC_PLAN_INVALID", message, "hvdc", "recommend_mmc_simulation", details
    )


def _engine(design: MmcDerivedParameters) -> tuple[str, Mapping[str, Any]]:
    engines = {candidate.engine for candidate in design.candidates}
    if len(engines) != 1:
        raise _error(
            "Scenario recommendations require one model fidelity.",
            engines=sorted(engines),
        )
    engine = engines.pop()
    if engine not in {"detailed_pwm", "average_value"}:
        raise _error("The derived MMC model fidelity is unsupported.", engine=engine)
    return engine, design.candidates[0].to_dict()


def _timing(
    design: MmcDerivedParameters, engine: str, candidate: Mapping[str, Any]
) -> tuple[float, float]:
    settings = candidate["settings"]
    control_sample = float(settings["control_sample_time_s"])
    if engine == "detailed_pwm":
        switching = float(settings["switching_frequency_hz"])
        time_step = min(control_sample / 5.0, 1.0 / switching / 40.0)
    else:
        length_km = design.request.dc_link.length_km
        propagation_s = max(length_km / 300_000.0, 1e-5)
        time_step = min(control_sample / 2.0, propagation_s / 20.0)
    return time_step, max(time_step, control_sample)


def _event(time_s: float, target: str, value: int | float) -> dict[str, Any]:
    return {"time_s": time_s, "target": target, "value": value}


def _events(name: str, reversal_time_s: float) -> tuple[list[dict[str, Any]], float]:
    if name == "startup":
        return [
            _event(0.02, "reset_command", 1),
            _event(0.05, "reset_command", 0),
            _event(0.10, "ac_breaker_command", 1),
            _event(0.15, "dc_breaker_command", 1),
            _event(0.20, "block_command", 0),
        ], 0.8
    if name == "forward_steady":
        return [_event(0.10, "active_power_order", 1.0)], 1.0
    if name == "active_power_step":
        return [
            _event(0.10, "active_power_order", 0.8),
            _event(0.50, "active_power_order", 1.0),
        ], 1.2
    if name == "reactive_power_step":
        return [
            _event(0.10, "reactive_power_order", 0.0),
            _event(0.50, "reactive_power_order", 0.1),
        ], 1.2
    if name == "power_reversal":
        return [
            _event(0.10, "active_power_order", 1.0),
            _event(0.60, "active_power_order", -1.0),
        ], max(1.4, 0.8 + reversal_time_s)
    if name == "reverse_steady":
        return [_event(0.10, "active_power_order", -1.0)], 1.0
    if name in {"ac_three_phase_fault", "ac_single_line_ground_fault"}:
        return [
            _event(0.30, "ac_fault_command", 1),
            _event(0.36, "block_command", 1),
            _event(0.40, "ac_breaker_command", 0),
            _event(0.50, "ac_fault_command", 0),
            _event(0.65, "ac_breaker_command", 1),
            _event(0.72, "block_command", 0),
        ], 1.2
    if name in {"dc_pole_to_pole_fault", "dc_pole_to_ground_fault"}:
        return [
            _event(0.30, "dc_fault_command", 1),
            _event(0.34, "block_command", 1),
            _event(0.38, "dc_breaker_command", 0),
            _event(0.50, "dc_fault_command", 0),
            _event(0.65, "dc_breaker_command", 1),
            _event(0.75, "block_command", 0),
        ], 1.3
    if name == "post_fault_recovery":
        return [
            _event(0.05, "reset_command", 1),
            _event(0.10, "reset_command", 0),
            _event(0.20, "ac_breaker_command", 1),
            _event(0.25, "dc_breaker_command", 1),
            _event(0.35, "block_command", 0),
            _event(0.45, "active_power_order", 0.8),
        ], 1.3
    raise _error("Unknown standard MMC scenario.", scenario=name)


def _metric_roles(name: str) -> tuple[str, ...]:
    common = (
        "station_p_active_power",
        "station_vdc_active_power",
        "dc_voltage",
        "dc_current",
        "arm_current",
        "equivalent_capacitor_voltage",
        "modulation_margin",
        "block_status",
    )
    if name.startswith("ac_"):
        return (*common, "ac_voltage", "ac_current", "ac_breaker_status")
    if name.startswith("dc_"):
        return (
            *common,
            "dc_breaker_status",
            "diode_equivalent_current",
        )
    return common


def recommend_scenarios(
    design: MmcDerivedParameters,
    *,
    derived_project: str | None = None,
) -> tuple[MmcScenarioRecommendation, ...]:
    if not isinstance(design, MmcDerivedParameters) or not design.feasible:
        raise _error("Scenario recommendations require a feasible derived design.")
    engine, candidate = _engine(design)
    time_step, output_step = _timing(design, engine, candidate)
    profile = (
        "mmc_detailed_pwm_v2"
        if engine == "detailed_pwm"
        else "mmc_average_value_v2"
    )
    default_project = "MMC_CASE_pwm" if engine == "detailed_pwm" else "MMC_CASE_avm"
    target_project = default_project if derived_project is None else derived_project
    target_path = Path(target_project).expanduser()
    if (
        target_path.is_absolute()
        or target_path.suffix.casefold() == ".pscx"
        or "/" in target_project
        or "\\" in target_project
    ):
        source_project = str(
            target_path.with_name(f"{target_path.stem}_scenario_source.pscx")
        )
    else:
        source_project = f"{target_project}_scenario_source"
    profile_data = bind_profile_project(load_profile(profile), target_project)
    result_selectors = {
        item["canonical"]: item["path"]
        for item in profile_data["result_channels"]
    }
    limitations = (
        "half_bridge_intrinsic_dc_fault_blocking=false",
        "dc_fault_acceptance_requires_diode_equivalent_current_and_breaker_evidence",
    )
    if engine == "average_value":
        limitations += (
            "individual_cell_balance_not_modeled",
            "device_stress_not_modeled",
            "switching_harmonics_not_modeled",
            "thermal_not_modeled",
        )
    result: list[MmcScenarioRecommendation] = []
    for name in _SCENARIOS:
        events, duration = _events(name, design.request.power_reversal_time_s)
        roles = _metric_roles(name)
        metrics = tuple(
            {
                "role": role,
                "selector": result_selectors[role],
                "units": _UNITS[role],
            }
            for role in roles
        )
        thresholds = {
            "finite_outputs": True,
            "dc_voltage_deviation_pu": 0.10,
            "dc_current_peak_pu": 2.0 if name.startswith("dc_") else 1.25,
            "modulation_margin_min_pu": 0.02,
            "recovery_time_s": 0.5,
        }
        scenario = {
            "name": name,
            "profile": profile,
            "project": source_project,
            "derived_project": target_project,
            "parameter_changes": [],
            "events": events,
            "time_step_s": time_step,
            "output_step_s": output_step,
            "duration_s": duration,
            "run": {"timeout_s": max(300.0, duration * 20.0)},
            "output_files": [],
            "analysis": {
                "metrics": list(roles),
                "thresholds": thresholds,
                "required_units": {role: _UNITS[role] for role in roles},
            },
            "preconditions": [
                "source_project_copy_is_preexisting_and_distinct",
                "derived_project_is_preexisting",
                "saved_project_matches_plan_hash",
                "project_output_is_enabled",
                "exact_profile_bindings_are_present",
            ],
            "model_fidelity": engine,
            "capabilities": {"intrinsic_dc_fault_blocking": False},
        }
        result.append(
            MmcScenarioRecommendation(
                name=name,
                engine=engine,
                scenario=scenario,
                time_step_s=time_step,
                duration_s=duration,
                capabilities={"intrinsic_dc_fault_blocking": False},
                preconditions=tuple(scenario["preconditions"]),
                metrics=metrics,
                thresholds=thresholds,
                limitations=limitations,
            )
        )
    return tuple(result)


__all__ = ["recommend_scenarios"]
