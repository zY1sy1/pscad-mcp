"""Parameterized adapter for the repository-owned MMC average-value assets."""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .....core.backend.base import BackendError
from .....acceptance.project_finalization import (
    GENERATED_MODULE_POLICY,
    compare_project_finalization,
    snapshot_project_semantics,
)
from ..assets import load_packaged_asset_set
from ..avm_companion import AverageArmParameters
from ..cable_companion import DEFAULT_DONOR, DEFAULT_MASTER
from ...common.serialization import content_hash
from ..cable_constants import extract_cable_configuration, generate_public_cable_constants
from ..master_bindings import (
    context_from_inventory,
    load_mmc_master_registry,
    native_inventory_catalog,
)
from ..models import MmcBlueprint, MmcBuildState
from ..native_bundle import audit_native_avm_fixture, materialize_native_avm_fixture
from ..parametric_models import MmcCandidate, MmcEnginePlan

_LIMITATIONS = {
    "individual_cell_balance": "not_modeled",
    "device_stress": "not_modeled",
    "switching_harmonics": "not_modeled",
    "thermal": "not_modeled",
}
_NATIVE_SOURCE_KEYS = {"master", "cable_donor", "tline"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _native_producer_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parent.parent
    return {
        name: _sha256(root / name)
        for name in (
            "engines/avm.py", "native_bundle.py", "avm_companion.py",
            "cable_companion.py", "cable_constants.py",
            "derivation.py", "parametric_planner.py",
        )
    }


def discover_native_avm_sources(
    *,
    master_path: str | Path = DEFAULT_MASTER,
    source_project: str | Path = DEFAULT_DONOR,
    executable: str | Path | None = None,
) -> dict[str, str] | None:
    """Return installed immutable inputs when the native cable AVM is available."""

    master = Path(master_path).expanduser().resolve()
    donor = Path(source_project).expanduser().resolve()
    tline = Path(executable).expanduser().resolve() if executable else (
        master.parent / "bin" / "win" / "tline.exe"
    ).resolve()
    paths = {"master": master, "cable_donor": donor, "tline": tline}
    if any(path.is_symlink() or not path.is_file() for path in paths.values()):
        return None
    return {name: str(path) for name, path in paths.items()}


def _native_input_record(
    paths: Mapping[str, str], *, control_kind: str = "closed_loop"
) -> dict[str, object]:
    if set(paths) != _NATIVE_SOURCE_KEYS:
        raise _error(
            "MMC_AVM_NATIVE_INPUT_MISSING",
            "The native AVM requires Master, cable donor and tline inputs.",
            missing=sorted(_NATIVE_SOURCE_KEYS - set(paths)),
            unexpected=sorted(set(paths) - _NATIVE_SOURCE_KEYS),
        )
    resolved = {name: Path(value).expanduser().resolve() for name, value in paths.items()}
    for name, path in resolved.items():
        if path.is_symlink() or not path.is_file():
            raise _error(
                "MMC_AVM_NATIVE_INPUT_MISSING",
                "A native AVM source input is unavailable.",
                source=name,
                path=str(path),
            )
    source_hashes = {name: _sha256(path) for name, path in resolved.items()}
    configuration = extract_cable_configuration(resolved["cable_donor"], master_path=resolved["master"])
    if (configuration.project_sha256 != source_hashes["cable_donor"]
            or configuration.master_sha256 != source_hashes["master"]
            or source_hashes != {name: _sha256(path) for name, path in resolved.items()}):
        raise _error("MMC_SOURCE_CHANGED", "Native AVM sources changed while reading the cable geometry.")
    return {
        "source_paths": {name: str(path) for name, path in resolved.items()},
        "source_hashes": source_hashes,
        "capabilities": {
            "native_physical_assembly": True,
            "native_cable_constants": True,
            "control_kind": control_kind,
            "model_accepted": False,
            "native_producer_hashes": _native_producer_hashes(),
            "native_cable_profile": configuration.dc_profile(),
        },
    }


def _messages_have_errors(value: object) -> bool:
    if isinstance(value, Mapping):
        if str(value.get("severity", "")).casefold() in {"error", "fatal"}:
            return True
        return any(_messages_have_errors(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_messages_have_errors(item) for item in value)
    return False


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
        native_sources: Mapping[str, str] | None = None,
        native_required: bool = False,
        constants_generator: Any = generate_public_cable_constants,
        fixture_builder: Any = materialize_native_avm_fixture,
        fixture_auditor: Any = audit_native_avm_fixture,
        operation_timeout_s: float = 600.0,
        native_control_kind: str = "closed_loop",
    ) -> None:
        self.asset_set = load_packaged_asset_set() if asset_set is None else asset_set
        self.inventory = inventory
        self.allow_test_double = allow_test_double
        self.native_sources = (
            None if native_sources is None else dict(native_sources)
        )
        self.native_required = native_required
        self.constants_generator = constants_generator
        self.fixture_builder = fixture_builder
        self.fixture_auditor = fixture_auditor
        self.operation_timeout_s = float(operation_timeout_s)
        self.native_control_kind = native_control_kind
        if not math.isfinite(self.operation_timeout_s) or self.operation_timeout_s <= 0:
            raise ValueError("operation_timeout_s must be finite and positive")
        if self.native_control_kind not in {"scheduled_open_loop", "closed_loop"}:
            raise ValueError("native_control_kind is unsupported")

    def planning_inputs(self, request: object) -> dict[str, object] | None:
        link = getattr(request, "dc_link", None)
        kind = getattr(link, "kind", None)
        if self.native_sources is None:
            if self.native_required:
                raise _error(
                    "MMC_AVM_NATIVE_INPUT_MISSING",
                    "Installed native AVM source inputs are required for production builds.",
                )
            return None
        if kind != "cable":
            raise _error(
                "MMC_AVM_LINK_UNSUPPORTED",
                "The native average-value path currently requires a cable DC link.",
                dc_link_kind=kind,
            )
        return _native_input_record(
            self.native_sources, control_kind=self.native_control_kind
        )

    @staticmethod
    def _native_arm_parameters(values: Mapping[str, Any]) -> AverageArmParameters:
        dc_current = float(values["rated_power_mw"]) / float(
            values["rated_dc_voltage_kv"]
        )
        valve_voltage = float(values.get("base_modulation_index", 0.9)) * float(values["rated_dc_voltage_kv"]) * math.sqrt(3.0) / (2.0 * math.sqrt(2.0))
        phase_current = math.hypot(float(values["rated_power_mw"]), float(values["reactive_power_mvar"])) / (math.sqrt(3.0) * valve_voltage)
        arm_rms = math.hypot(dc_current / 3.0, phase_current / 2.0)
        ohmic_loss = float(values["arm_resistance_ohm"]) * arm_rms**2
        nonohmic_loss = max(0.0, float(values["loss_per_arm_mw"]) - ohmic_loss)
        return AverageArmParameters(
            C_eq_F=float(values["equivalent_arm_capacitance_f"]),
            L_arm_H=float(values["arm_inductance_h"]),
            R_arm_ohm=float(values["arm_resistance_ohm"]),
            P_nonohmic_MW=nonohmic_loss,
            R_off_ohm=float(values["arm_off_state_resistance_ohm"]),
        )

    @staticmethod
    def _native_control_parameters(values: Mapping[str, Any]) -> dict[str, float]:
        bandwidth = float(values["control_bandwidth_hz"])
        if not math.isfinite(bandwidth) or bandwidth <= 0:
            raise _error("MMC_CONTROL_INFEASIBLE", "Native control bandwidth must be finite and positive.")
        scale = bandwidth / 80.0
        power_scale = float(values["rated_power_mw"]) / 1000.0
        voltage_scale = float(values["rated_dc_voltage_kv"]) / 640.0
        return {
            "p_control_kp": 0.01 * scale / power_scale,
            "vdc_control_kp": 0.01 * scale / power_scale,
            "active_control_ti_s": 0.10 / scale,
            "reactive_control_kp": 0.00005 * scale / power_scale,
            "reactive_control_ti_s": 0.05 / scale,
            "dc_voltage_control_kp": 3.0 * scale * power_scale / voltage_scale,
            "dc_voltage_control_ti_s": 0.30 / scale,
            "energy_control_gain": 10.0 * scale,
            "circulating_control_bandwidth_hz": 60.0 * scale,
            "feedback_filter_s": 0.02 / scale,
            "energy_difference_filter_s": 0.05 / scale,
        }

    async def _execute_native_candidate(
        self,
        plan: MmcEnginePlan,
        service: object,
        *,
        candidate_id: str | None,
    ) -> dict[str, object]:
        selected = _candidate(plan, candidate_id)
        inputs = _native_input_record(
            plan.source_paths, control_kind=self.native_control_kind
        )
        if dict(plan.source_hashes) != inputs["source_hashes"]:
            raise _error(
                "MMC_SOURCE_CHANGED",
                "Native AVM source hashes differ from the immutable child plan.",
                expected=dict(plan.source_hashes),
                observed=inputs["source_hashes"],
            )
        if dict(plan.capabilities.get("native_producer_hashes", {})) != _native_producer_hashes():
            raise _error(
                "MMC_PLAN_STALE",
                "The native AVM producer changed after the immutable child plan was created.",
            )
        values = selected.parameters
        actual_profile = inputs["capabilities"]["native_cable_profile"]
        planned_profile = plan.capabilities.get("native_cable_profile")
        expected_resistance = math.fsum(actual_profile["core_dc_resistance_ohm_per_km"]) * float(values["dc_link_length_km"])
        if (content_hash(actual_profile) != content_hash(planned_profile)
                or values.get("native_cable_profile_hash") != content_hash(actual_profile)
                or not math.isclose(float(values["line_resistance_ohm"]), expected_resistance, rel_tol=1e-12)):
            raise _error("MMC_PLAN_STALE", "Native AVM candidate cable resistance differs from its frozen geometry.")
        if values.get("dc_link_kind") != "cable":
            raise _error(
                "MMC_AVM_LINK_UNSUPPORTED",
                "The native average-value candidate requires a cable DC link.",
                dc_link_kind=values.get("dc_link_kind"),
            )
        candidate_root = (
            Path(plan.workspace).resolve()
            / ".mmc-candidates"
            / plan.plan_hash
            / selected.candidate_id
        )
        candidate_root.mkdir(parents=True, exist_ok=False)
        source_paths = {name: Path(path) for name, path in plan.source_paths.items()}
        constants = await asyncio.to_thread(
            self.constants_generator,
            source_paths["cable_donor"],
            candidate_root / "line-constants",
            master_path=source_paths["master"],
            executable=source_paths["tline"],
            lengths_km=(float(values["dc_link_length_km"]),),
            reference_frequency_hz=float(values["frequency_hz"]),
            fitting_profile="dc_corrected_v1",
        )
        if len(constants) != 1:
            raise _error(
                "MMC_AVM_CONSTANTS_INVALID",
                "Native cable generation did not return exactly one artifact.",
                artifact_count=len(constants),
            )
        if (not math.isclose(constants[0].loop_dc_resistance_ohm, expected_resistance, rel_tol=1e-12)
                or not math.isclose(constants[0].length_km, float(values["dc_link_length_km"]), rel_tol=1e-12)
                or tuple(constants[0].core_dc_resistance_ohm_per_km) != tuple(actual_profile["core_dc_resistance_ohm_per_km"])):
            raise _error("MMC_AVM_CONSTANTS_INVALID", "Generated cable constants differ from the planned physical profile.",
                         expected_loop_resistance_ohm=expected_resistance,
                         observed_loop_resistance_ohm=constants[0].loop_dc_resistance_ohm)
        modulation_index = float(values["base_modulation_index"])
        valve_voltage = (
            modulation_index
            * float(values["rated_dc_voltage_kv"])
            * math.sqrt(3.0)
            / (2.0 * math.sqrt(2.0))
        )
        reversal_time = 1.0
        reversal_duration = float(values["power_reversal_time_s"])
        duration = reversal_time + reversal_duration + 1.0
        candidate_project_name = (
            "AVM_"
            + plan.plan_hash[:12]
            + "_"
            + selected.candidate_id.replace("-", "_")
        )
        if len(candidate_project_name) > 30:
            raise _error(
                "MMC_LAYOUT_INVALID",
                "The deterministic native AVM candidate identity exceeds the EMTDC limit.",
                candidate_project_name=candidate_project_name,
            )
        receipt = await asyncio.to_thread(
            self.fixture_builder,
            candidate_root / "model",
            constants_evidence=Path(constants[0].evidence_path),
            master_path=source_paths["master"],
            source_project=source_paths["cable_donor"],
            project_name=candidate_project_name,
            frequency_hz=float(values["frequency_hz"]),
            station_p_ac_voltage_kv=float(values["station_p_ac_voltage_kv"]),
            station_vdc_ac_voltage_kv=float(values["station_vdc_ac_voltage_kv"]),
            station_p_valve_voltage_kv=valve_voltage,
            station_vdc_valve_voltage_kv=valve_voltage,
            station_p_grid_r_ohm=float(values["station_p_grid_r_ohm"]),
            station_p_grid_x_ohm=float(values["station_p_grid_x_ohm"]),
            station_vdc_grid_r_ohm=float(values["station_vdc_grid_r_ohm"]),
            station_vdc_grid_x_ohm=float(values["station_vdc_grid_x_ohm"]),
            transformer_rating_mva=float(values["transformer_rating_mva"]),
            modulation_index=modulation_index,
            control_kind=self.native_control_kind,
            active_power_order_mw=float(values["rated_power_mw"]),
            reactive_power_order_mvar=float(values["reactive_power_mvar"]),
            vdc_order_kv=float(values["rated_dc_voltage_kv"]),
            cable_loss_mw=(
                float(values["rated_power_mw"]) / float(values["rated_dc_voltage_kv"])
            ) ** 2 * constants[0].loop_dc_resistance_ohm,
            converter_loss_mw=12 * float(values["loss_per_arm_mw"]),
            dc_grounding_resistance_ohm=float(values["dc_grounding_resistance_ohm"]),
            valve_grounding_resistance_ohm=float(values["valve_grounding_resistance_ohm"]),
            ramp_time_s=0.20,
            deblock_time_s=0.10,
            reversal_time_s=reversal_time,
            reversal_duration_s=reversal_duration,
            simulation_duration_s=duration,
            time_step_s=float(selected.settings["time_step_s"]),
            output_step_s=float(selected.settings["output_step_s"]),
            arm_parameters=self._native_arm_parameters(values),
            **self._native_control_parameters(values),
        )
        project = Path(receipt["project_path"])
        library = Path(receipt["library"]["library_path"])
        authored_models = {
            str(path): snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)
            for path in (project, library)
        }
        authored_directory = candidate_root / "authored-models"
        authored_directory.mkdir()
        for path in (project, library):
            with (authored_directory / path.name).open("xb") as target:
                target.write(path.read_bytes())

        async def bounded(awaitable: Any) -> Any:
            return await asyncio.wait_for(awaitable, self.operation_timeout_s)

        for name in (
            "load_projects",
            "save_project",
            "build_project",
            "get_project_output",
        ):
            if not callable(getattr(service, name, None)):
                raise _error(
                    "MMC_ENGINE_SERVICE_INVALID",
                    "The native AVM engine requires PSCAD load, save, build and output methods.",
                    missing=name,
                )
        await bounded(service.load_projects([str(library), str(project)]))
        await bounded(service.save_project(library.stem, confirm=True))
        await bounded(service.save_project(candidate_project_name, confirm=True))
        build_started = time.time()
        build_result = await bounded(service.build_project(candidate_project_name))
        build_messages = await bounded(
            service.get_project_output(candidate_project_name, structured=True)
        )
        if _messages_have_errors(build_messages):
            raise _error(
                "MMC_BUILD_FAILED",
                "The native AVM candidate compile produced error messages.",
                messages=build_messages,
            )
        await bounded(service.save_project(library.stem, confirm=True))
        await bounded(service.save_project(candidate_project_name, confirm=True))
        library_sha256 = _sha256(library)
        model_finalization = {
            path: compare_project_finalization(
                before, snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)
            )
            for path, before in authored_models.items()
        }
        topology = self.fixture_auditor(
            project,
            receipt,
            finalized_library_sha256=library_sha256,
        )
        source_hashes_after = {
            name: _sha256(path) for name, path in source_paths.items()
        }
        if source_hashes_after != dict(plan.source_hashes):
            raise _error(
                "MMC_SOURCE_CHANGED",
                "Native AVM source inputs changed during candidate construction.",
                expected=dict(plan.source_hashes),
                observed=source_hashes_after,
            )
        written = [project, library]
        written.extend(Path(path) for path in receipt["library"]["constants_artifacts"])
        return {
            "state": "built",
            "engine": self.name,
            "candidate_id": selected.candidate_id,
            "candidate_path": str(candidate_root),
            "project_path": str(project),
            "publication_project_name": candidate_project_name,
            "library_path": str(library),
            "library_sha256": library_sha256,
            "written_paths": tuple(str(path) for path in written),
            "source_hashes": source_hashes_after,
            "build_result": build_result,
            "build_messages": build_messages,
            "build_started_at": build_started,
            "topology": topology,
            "model_finalization": model_finalization,
            "fixture": receipt,
            "validation": {
                "verdict": "PASS",
                "scope": "native_physical_assembly_compile",
                "model_accepted": False,
            },
            "assembly_accepted": False,
            "model_accepted": False,
            "capability_level": "built",
        }

    async def execute_candidate(
        self,
        plan: MmcEnginePlan,
        service: object,
        *,
        candidate_id: str | None = None,
    ) -> dict[str, object]:
        if plan.source_paths:
            return await self._execute_native_candidate(
                plan, service, candidate_id=candidate_id
            )
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
            inventory = await get_inventory(native_inventory_catalog(_inventory_catalog(self.asset_set)), load_mmc_master_registry().to_dict())
            if context_from_inventory(inventory) is None:
                raise _error("MASTER_BINDING_MISSING", "The native AVM inventory must include source-hashed Master binding evidence.")
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
