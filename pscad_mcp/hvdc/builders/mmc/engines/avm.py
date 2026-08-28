"""Parameterized adapter for the repository-owned MMC average-value assets."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from .....core.backend.base import BackendError
from ..assets import load_packaged_asset_set
from ..models import MmcBlueprint, MmcBuildState
from ..parametric_models import MmcCandidate, MmcEnginePlan


_LIMITATIONS = {
    "individual_cell_balance": "not_modeled",
    "device_stress": "not_modeled",
    "switching_harmonics": "not_modeled",
    "thermal": "not_modeled",
}


def _error(code: str, message: str, **details: object) -> BackendError:
    return BackendError(code, message, "hvdc", "materialize_parametric_avm", details)


def _candidate(plan: MmcEnginePlan, candidate_id: str | None) -> MmcCandidate:
    if plan.engine != "average_value":
        raise _error("MMC_PLAN_INVALID", "The AVM engine requires an average_value plan.")
    if not plan.candidates:
        raise _error("MMC_PLAN_INVALID", "The AVM plan contains no candidates.")
    if candidate_id is None:
        return plan.candidates[0]
    for item in plan.candidates:
        if item.candidate_id == candidate_id:
            return item
    raise _error(
        "MMC_PLAN_INVALID",
        "The requested AVM candidate is not in the immutable child plan.",
        candidate_id=candidate_id,
    )


def _arm_parameters(candidate: MmcCandidate) -> dict[str, Any]:
    values = candidate.parameters
    required = {
        "rated_dc_voltage_kv",
        "rated_power_mw",
        "arm_inductance_h",
        "arm_resistance_ohm",
        "stored_energy_mj",
        "equivalent_arm_capacitance_f",
        "loss_per_arm_mw",
    }
    missing = sorted(required - set(values))
    if missing:
        raise _error(
            "MMC_PLAN_INVALID",
            "The AVM candidate lacks required derived arm parameters.",
            missing=missing,
        )
    return {
        "C_eq_F": values["equivalent_arm_capacitance_f"],
        "L_arm_H": values["arm_inductance_h"],
        "R_arm_ohm": values["arm_resistance_ohm"],
        "rated_dc_voltage_kv": values["rated_dc_voltage_kv"],
        "rated_power_mw": values["rated_power_mw"],
        "stored_energy_mj": values["stored_energy_mj"] / 12.0,
        "loss_mw": values["loss_per_arm_mw"],
        "blocked_state_path": "half_bridge_diode_equivalent",
        "intrinsic_dc_fault_blocking": False,
    }


def _component_parameters(component: Any, candidate: MmcCandidate) -> dict[str, Any]:
    values = candidate.parameters
    parameters = dict(component.parameters)
    if component.definition.endswith(":MMCAverageArm"):
        return _arm_parameters(candidate)
    if component.definition == "master:source3":
        station = "station_p" if component.logical_id.startswith("STATION_P") else "station_vdc"
        parameters.update(
            {
                "Amplitude": values[f"{station}_ac_voltage_kv"],
                "Frequency": values["frequency_hz"],
                "GridR": values[f"{station}_grid_r_ohm"],
                "GridX": values[f"{station}_grid_x_ohm"],
            }
        )
    elif component.definition == "master:transformer":
        parameters.update(
            {
                "rated_power_mva": values["transformer_rating_mva"],
                "rated_dc_voltage_kv": values["rated_dc_voltage_kv"],
            }
        )
    elif component.definition == "master:dc_cable":
        parameters.update(
            {
                "length_km": values["dc_link_length_km"],
                "resistance_ohm": values["line_resistance_ohm"] / 2.0,
            }
        )
    elif "Control" in component.definition or "control" in (component.role or "").casefold():
        parameters.update(
            {
                "active_power_order_mw": values["rated_power_mw"],
                "reactive_power_order_mvar": values["reactive_power_mvar"],
                "control_bandwidth_hz": values["control_bandwidth_hz"],
            }
        )
    return parameters


def _inventory_catalog(asset_set: Any) -> dict[str, Any]:
    """Request live metadata for every Master definition used by the AVM asset."""

    catalog = dict(asset_set.catalog)
    definitions = dict(catalog.get("definitions", {}))
    for component in asset_set.blueprint.components:
        definition = str(component.definition)
        if definition.startswith("master:"):
            definitions.setdefault(definition, {})
    catalog["definitions"] = definitions
    return catalog


def materialize_parametric_blueprint(
    plan: MmcEnginePlan,
    *,
    asset_set: Any | None = None,
    candidate_id: str | None = None,
) -> MmcBlueprint:
    """Clone the owned immutable blueprint with one preplanned AVM candidate."""

    assets = load_packaged_asset_set() if asset_set is None else asset_set
    if dict(plan.asset_hashes) != dict(assets.hashes):
        raise _error(
            "MMC_ASSET_MISMATCH",
            "The loaded AVM assets differ from the immutable child plan.",
            expected=dict(plan.asset_hashes),
            observed=dict(assets.hashes),
        )
    selected = _candidate(plan, candidate_id)
    values = selected.parameters
    arm_parameters = _arm_parameters(selected)
    components = tuple(
        replace(
            component,
            parameters=_component_parameters(component, selected),
            role=(
                "arm"
                if component.definition.endswith(":MMCAverageArm")
                else component.role
            ),
        )
        for component in assets.blueprint.components
    )
    stations = tuple(
        replace(
            station,
            arms=tuple(
                replace(arm, parameters=arm_parameters, role="arm")
                for arm in station.arms
            ),
            parameters={
                **dict(station.parameters),
                "rated_dc_voltage_kv": values["rated_dc_voltage_kv"],
                "rated_power_mw": values["rated_power_mw"],
                "reactive_power_mvar": values["reactive_power_mvar"],
            },
        )
        for station in assets.blueprint.stations
    )
    checks = []
    for check in assets.blueprint.acceptance_checks:
        expected = dict(check.expected)
        if check.name == "forward_steady" and "power_mw" in expected:
            expected["power_mw"] = values["rated_power_mw"]
        if check.name == "reverse_steady" and "power_mw" in expected:
            expected["power_mw"] = -values["rated_power_mw"]
        checks.append(replace(check, expected=expected))
    sequence = tuple(
        replace(
            phase,
            duration_s=(
                values["power_reversal_time_s"]
                if phase.name == "power_reversal"
                else phase.duration_s
            ),
        )
        for phase in assets.blueprint.sequence
    )
    return replace(
        assets.blueprint,
        nominal_vdc_kv=values["rated_dc_voltage_kv"],
        nominal_power_mw=values["rated_power_mw"],
        settings={
            **dict(assets.blueprint.settings),
            **dict(selected.settings),
            "frequency_hz": values["frequency_hz"],
        },
        stations=stations,
        components=components,
        sequence=sequence,
        acceptance_checks=tuple(checks),
        provenance={
            **dict(assets.blueprint.provenance),
            "parametric_candidate_id": selected.candidate_id,
            "parametric_parameter_hash": selected.parameter_hash,
            "capabilities": {
                "blocked_state_path": "half_bridge_diode_equivalent",
                "intrinsic_dc_fault_blocking": False,
            },
            "model_limitations": _LIMITATIONS,
        },
    )


def create_parametric_avm_plan(*args: Any, **kwargs: Any):
    from ..planner import create_parametric_avm_plan as create

    return create(*args, **kwargs)


class AvmBlueprintEngine:
    name = "average_value"

    def __init__(
        self,
        *,
        asset_set: Any | None = None,
        inventory: Any | None = None,
        allow_test_double: bool = False,
    ) -> None:
        self.asset_set = load_packaged_asset_set() if asset_set is None else asset_set
        self.inventory = inventory
        self.allow_test_double = allow_test_double

    async def execute_candidate(
        self,
        plan: MmcEnginePlan,
        service: object,
        *,
        candidate_id: str | None = None,
    ) -> dict[str, object]:
        from ..executor import execute_build

        inventory = self.inventory
        if inventory is None:
            get_inventory = getattr(service, "get_mmc_inventory", None)
            if not callable(get_inventory):
                get_inventory = getattr(service, "get_lcc_inventory", None)
            if not callable(get_inventory):
                raise _error(
                    "MMC_ENGINE_SERVICE_INVALID",
                    "The AVM engine requires a public definition-inventory method.",
                )
            inventory = await get_inventory(_inventory_catalog(self.asset_set))
        selected = _candidate(plan, candidate_id)
        candidate_root = (
            Path(plan.workspace).resolve()
            / ".mmc-candidates"
            / plan.plan_hash
            / selected.candidate_id
        )
        candidate_target = candidate_root / f"{plan.target_name}.pscx"
        candidate_plan = replace(
            plan,
            workspace=str(candidate_root),
            target_path=str(candidate_target),
        )
        build_plan = create_parametric_avm_plan(
            candidate_plan,
            self.asset_set,
            inventory,
            candidate_root,
            candidate_id=selected.candidate_id,
        )
        record = await execute_build(
            build_plan,
            service,
            candidate_root,
            asset_set=self.asset_set,
            build_id=f"avm-{selected.candidate_id}",
            allow_test_double=self.allow_test_double,
        )
        payload = record.to_dict()
        validation = self.validate(candidate_plan, candidate_target, payload)
        return {
            "state": "accepted",
            "engine": self.name,
            "candidate_id": selected.candidate_id,
            "candidate_path": str(candidate_root),
            "project_path": str(candidate_target),
            "written_paths": (str(candidate_target),),
            "record": payload,
            "validation": validation,
            "capability_level": "accepted",
        }

    def validate(
        self,
        plan: MmcEnginePlan,
        project_path: Path,
        outputs: dict[str, object],
    ) -> dict[str, object]:
        state = str(outputs.get("state", ""))
        if state != MmcBuildState.PUBLISHED.value or not project_path.is_file():
            raise _error(
                "MMC_ACCEPTANCE_FAILED",
                "The average-value candidate was not published by the fixed builder.",
                state=state,
                project_path=str(project_path),
            )
        return {
            "verdict": "PASS",
            "model_fidelity": self.name,
            "intrinsic_dc_fault_blocking": False,
            "model_limitations": _LIMITATIONS,
            "plan_hash": plan.plan_hash,
        }


__all__ = [
    "AvmBlueprintEngine",
    "create_parametric_avm_plan",
    "materialize_parametric_blueprint",
]
