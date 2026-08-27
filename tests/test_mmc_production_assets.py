from __future__ import annotations

import json
import shutil
from pathlib import Path

from pscad_mcp.hvdc.builders.mmc.schema import parse_blueprint
from scripts.audit_mmc_assets import audit_asset_root


ASSET_ROOT = Path(__file__).parents[1] / "pscad_mcp" / "assets" / "mmc" / "cigre_b4_p2p_avm_v1"


def test_production_mmc_asset_set_is_exact_and_audited():
    report = audit_asset_root(ASSET_ROOT)
    assert report["valid"] is True, report
    assert report["pscad_version"] == "4.6.2"
    assert report["definitions"] == [
        "cigre_mmc_avm_v1:MMCAverageArm",
        "cigre_mmc_avm_v1:MMCDimensionedSignal",
        "cigre_mmc_avm_v1:MMCEnergyControl",
        "cigre_mmc_avm_v1:MMCInitialization",
        "cigre_mmc_avm_v1:MMCSequenceSignal",
        "cigre_mmc_avm_v1:MMCStationControl",
    ]
    assert set(report["manifest_files"]) == {
        "PROVENANCE.md", "acceptance.json", "blueprint.json", "catalog-pscad-4.6.2.json",
        "controls.json", "golden.json", "operating-sequence.json", "library/cigre_mmc_avm_v1.pslx",
    }

    blueprint = json.loads((ASSET_ROOT / "blueprint.json").read_text(encoding="utf-8"))
    parsed = parse_blueprint(blueprint)
    assert parsed.profile == "cigre_b4_p2p_avm_v1"
    assert len(parsed.stations) == 2
    assert sum(len(station.arms) for station in parsed.stations) == 12

    assert parsed.nominal_vdc_kv == 640.0
    assert parsed.nominal_power_mw == 1000.0
    assert parsed.provenance["blocked_state_path"] == "half_bridge_diode_equivalent"
    assert parsed.provenance["intrinsic_dc_fault_blocking"] is False
    arm_components = [component for component in parsed.components if component.definition.endswith(":MMCAverageArm")]
    assert len(arm_components) == 12
    assert len({component.logical_id for component in arm_components}) == 12
    assert {net.logical_id for net in parsed.nets} >= {"dc_positive_conductor", "dc_negative_conductor"}
    assert all("ground" not in net.logical_id.casefold() for net in parsed.nets)

    required_roles = {
        "dc_voltage_pole_to_pole", "dc_voltage_pole_to_ground", "dc_conductor_current",
        "station_ac_active_power", "station_ac_reactive_power", "station_dc_power", "ac_voltage",
        "ac_current", "arm_current", "arm_energy", "equivalent_capacitor_voltage", "circulating_current",
        "arm_energy_difference", "pll_frequency", "pll_lock", "active_power_command",
        "reactive_power_command", "dc_voltage_command", "modulation_index_unclipped",
        "modulation_index_clipped", "modulation_margin", "controller_saturation",
        "controller_saturation_duration", "sequence_state",
    }
    assert required_roles <= {output.role for output in parsed.outputs}
    assert sum(output.role == "arm_current" for output in parsed.outputs) == 12
    assert sum(output.role == "arm_energy" for output in parsed.outputs) == 12
    assert sum(output.role == "equivalent_capacitor_voltage" for output in parsed.outputs) == 12

    sequence = json.loads((ASSET_ROOT / "operating-sequence.json").read_text(encoding="utf-8"))
    assert sequence["phases"] == [
        "blocked_precharge", "ready_to_deblock", "forward_ramp", "forward_steady", "power_reversal", "reverse_steady"
    ]
    acceptance = json.loads((ASSET_ROOT / "acceptance.json").read_text(encoding="utf-8"))
    assert [window["name"] for window in acceptance["windows"]] == ["precharge_ready", "forward_steady", "power_reversal", "reverse_steady"]
    assert {
        window["name"]: window["expected"]["channels"]
        for window in acceptance["windows"]
    } == {
        "precharge_ready": ["vdc_pole_to_pole"],
        "forward_steady": ["p_ac_p"],
        "power_reversal": ["p_ac_p"],
        "reverse_steady": ["p_ac_p"],
    }
    assert {
        check.name: list(check.expected["channels"])
        for check in parsed.acceptance_checks
    } == {
        "precharge_ready": ["vdc_pole_to_pole"],
        "forward_steady": ["p_ac_p"],
        "power_reversal": ["p_ac_p"],
        "reverse_steady": ["p_ac_p"],
    }
    controls = json.loads((ASSET_ROOT / "controls.json").read_text(encoding="utf-8"))
    assert controls["bandwidth_hz"] == {"pll": 10.0, "outer": 20.0, "energy": 40.0, "circulating": 60.0, "inner": 120.0}
    assert controls["blocked_state_path"] == "half_bridge_diode_equivalent"
    assert controls["intrinsic_dc_fault_blocking"] is False
    golden = json.loads((ASSET_ROOT / "golden.json").read_text(encoding="utf-8"))
    assert golden["source"]["builder_generated"] is False
    assert golden["source"]["status"] != "accepted"


def test_manifest_fails_closed_for_added_removed_and_changed_children(tmp_path):
    copy = tmp_path / "asset"
    shutil.copytree(ASSET_ROOT, copy)
    (copy / "unexpected.json").write_text("{}", encoding="utf-8")
    assert audit_asset_root(copy)["valid"] is False
    (copy / "unexpected.json").unlink()
    (copy / "blueprint.json").write_text("{}", encoding="utf-8")
    assert audit_asset_root(copy)["valid"] is False
