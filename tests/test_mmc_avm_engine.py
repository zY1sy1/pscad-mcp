import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.engines.avm import (
    AvmBlueprintEngine,
    _inventory_catalog,
    create_parametric_avm_plan,
    materialize_parametric_blueprint,
)
from pscad_mcp.hvdc.builders.mmc.parametric_models import parse_parametric_request
from pscad_mcp.hvdc.builders.mmc.parametric_planner import create_parametric_plan
from tests.mmc_parametric_fakes import (
    avm_assets,
    avm_parametric_plan,
    pwm_audit,
    valid_request,
)
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


def test_native_avm_engine_freezes_sources_and_materializes_candidate_values(
    tmp_path: Path,
) -> None:
    master = Path(r"C:\Program Files (x86)\PSCAD46\master.pslx")
    donor = Path(
        r"C:\Users\Public\Documents\PSCAD\4.6\Examples\hvdc_vsc\VSCTrans.pscx"
    )
    tline = master.parent / "bin" / "win" / "tline.exe"
    if not master.is_file() or not donor.is_file() or not tline.is_file():
        pytest.skip("Installed PSCAD 4.6.2 XML sources are required")
    engine = AvmBlueprintEngine(
        native_sources={
            "master": str(master),
            "cable_donor": str(donor),
            "tline": str(tline),
        }
    )
    request = parse_parametric_request(
        valid_request(
            model_fidelity="average_value",
            dc_voltage_kv=500.0,
            active_power_mw=750.0,
            station_p={
                "ac_voltage_kv": 180.0,
                "short_circuit_ratio": 5.0,
                "x_over_r": 10.0,
            },
            station_vdc={
                "ac_voltage_kv": 190.0,
                "short_circuit_ratio": 4.0,
                "x_over_r": 8.0,
            },
            dc_link={"kind": "cable", "length_km": 100.0},
        )
    )
    inputs = engine.planning_inputs(request)
    assert inputs["capabilities"]["native_physical_assembly"] is True
    assert inputs["source_hashes"]["master"] == hashlib.sha256(
        master.read_bytes()
    ).hexdigest()
    plan = create_parametric_plan(
        request,
        "PUBLIC_NATIVE",
        tmp_path,
        pwm_audit(),
        avm_assets(),
        avm_native_inputs=inputs,
    ).engine_plans[0]

    class Service:
        def __init__(self):
            self.calls = []

        async def load_projects(self, paths):
            self.calls.append(("load", tuple(paths)))
            return "loaded"

        async def save_project(self, name, *, confirm=False):
            self.calls.append(("save", name, confirm))
            return "saved"

        async def build_project(self, name):
            self.calls.append(("build", name))
            return "built"

        async def get_project_output(self, name, structured=False):
            self.calls.append(("output", name, structured))
            return {"messages": []}

    service = Service()
    result = asyncio.run(engine.execute_candidate(plan, service))
    assert result["state"] == "accepted"
    assert result["capability_level"] == "built"
    assert result["assembly_accepted"] is False
    assert result["model_accepted"] is False
    assert result["validation"]["scope"] == "native_physical_assembly_compile"
    assert result["source_hashes"] == dict(plan.source_hashes)
    candidate_name = "AVM_" + plan.plan_hash[:12] + "_avm_0"
    assert ("build", candidate_name) in service.calls
    assert result["publication_project_name"] == candidate_name
    assert len(candidate_name) <= 30
    root = ET.parse(result["project_path"]).getroot()
    users = root.findall("./definitions/Definition[@name='Main']/schematic/User")
    assert len(
        [item for item in users if item.get("defn", "").endswith(":MMCAverageArm")]
    ) == 12
    assert result["fixture"]["parameters"]["station_p_ac_voltage_kv"] == 180.0
    assert result["fixture"]["parameters"]["station_vdc_ac_voltage_kv"] == 190.0
    assert result["fixture"]["parameters"]["cable_length_km"] == 100.0


def test_native_avm_engine_rejects_unmodeled_overhead_link(tmp_path: Path) -> None:
    paths = {}
    for name in ("master", "cable_donor", "tline"):
        path = tmp_path / name
        path.write_bytes(name.encode("ascii"))
        paths[name] = str(path)
    engine = AvmBlueprintEngine(native_sources=paths)
    request = parse_parametric_request(
        valid_request(model_fidelity="average_value", dc_link={"kind": "overhead_line", "length_km": 100.0})
    )
    with pytest.raises(BackendError) as raised:
        engine.planning_inputs(request)
    assert raised.value.code == "MMC_AVM_LINK_UNSUPPORTED"
