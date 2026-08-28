from dataclasses import replace
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.engines.avm import (
    _inventory_catalog,
    create_parametric_avm_plan,
    materialize_parametric_blueprint,
)
from tests.mmc_parametric_fakes import avm_parametric_plan
from tests.test_mmc_planner import ASSET, INVENTORY


def test_avm_engine_applies_derived_parameters_to_twelve_visible_arms(
    tmp_path: Path,
) -> None:
    plan = avm_parametric_plan(
        tmp_path, dc_voltage_kv=500.0, active_power_mw=750.0
    )

    blueprint = materialize_parametric_blueprint(plan)

    arms = [component for component in blueprint.components if component.role == "arm"]
    assert len(arms) == 12
    assert {arm.parameters["rated_dc_voltage_kv"] for arm in arms} == {500.0}
    assert {arm.parameters["rated_power_mw"] for arm in arms} == {750.0}
    assert {arm.parameters["blocked_state_path"] for arm in arms} == {
        "half_bridge_diode_equivalent"
    }
    assert {
        arm.parameters["intrinsic_dc_fault_blocking"] for arm in arms
    } == {False}
    assert blueprint.settings["time_step_s"] == plan.settings["time_step_s"]
    assert blueprint.nominal_vdc_kv == 500.0
    assert blueprint.nominal_power_mw == 750.0
    assert blueprint.provenance["capabilities"]["intrinsic_dc_fault_blocking"] is False


def test_parametric_avm_plan_reuses_fixed_topology_with_derived_operations(
    tmp_path: Path,
) -> None:
    engine_plan = replace(
        avm_parametric_plan(tmp_path), asset_hashes=ASSET.hashes
    )

    build_plan = create_parametric_avm_plan(
        engine_plan, ASSET, INVENTORY, tmp_path
    )

    arm_operations = [
        operation
        for operation in build_plan.operations
        if operation.phase == "place_arm"
    ]
    assert len(arm_operations) == 12
    assert {
        operation.arguments["parameters"]["rated_dc_voltage_kv"]
        for operation in arm_operations
    } == {500.0}
    assert build_plan.metadata["parametric_engine_plan_hash"] == engine_plan.plan_hash
    assert build_plan.blueprint.provenance["model_limitations"] == {
        "individual_cell_balance": "not_modeled",
        "device_stress": "not_modeled",
        "switching_harmonics": "not_modeled",
        "thermal": "not_modeled",
    }


def test_parametric_avm_plan_rejects_asset_hash_drift(tmp_path: Path) -> None:
    engine_plan = replace(
        avm_parametric_plan(tmp_path),
        asset_hashes={**ASSET.hashes, "library/cigre_mmc_avm_v1.pslx": "b" * 64},
    )

    with pytest.raises(BackendError) as raised:
        create_parametric_avm_plan(engine_plan, ASSET, INVENTORY, tmp_path)

    assert raised.value.code == "MMC_ASSET_MISMATCH"
    assert list(tmp_path.iterdir()) == []


def test_avm_inventory_request_includes_live_master_dependencies() -> None:
    catalog = _inventory_catalog(ASSET)
    definitions = catalog["definitions"]
    assert "cigre_mmc_avm_v1:MMCAverageArm" in definitions
    assert "master:source3" in definitions
    assert "master:transformer" in definitions
