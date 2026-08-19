from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.models import MmcNetSpec
from pscad_mcp.hvdc.builders.mmc.planner import MmcAssetSet, MmcPlanRequest, create_plan
from pscad_mcp.hvdc.builders.mmc.schema import parse_blueprint


ASSET_ROOT = Path(__file__).parents[1] / "pscad_mcp" / "assets" / "mmc" / "cigre_b4_p2p_avm_v1"
BLUEPRINT = parse_blueprint(__import__("json").loads((ASSET_ROOT / "blueprint.json").read_text(encoding="utf-8")))


def _ports(*names: str, kind: str = "signal", dimension: int = 1):
    return [{"name": name, "kind": "electrical" if name in {"AC", "DC", "IN", "OUT"} else kind, "dimension": dimension} for name in names]


CATALOG = {
    "schema_version": 1,
    "name": "cigre_b4_p2p_avm_v1",
    "pscad_version": "4.6.2",
    "identity": "cigre_b4_p2p_avm_v1/catalog-pscad-4.6.2",
    "definitions": {
        "master:source3": {"ports": _ports("AC", kind="electrical"), "bounding_box": [-10, -10, 10, 10]},
        "master:dc_bus": {"ports": _ports("DC", kind="electrical"), "bounding_box": [-10, -10, 10, 10]},
        "master:dc_cable": {"ports": _ports("IN", "OUT", kind="electrical"), "bounding_box": [-20, -5, 20, 5]},
        "master:transformer": {"ports": _ports("AC", "VALVE", kind="electrical"), "bounding_box": [-10, -10, 10, 10]},
        "cigre_mmc_avm_v1:MMCAverageArm": {"ports": _ports("AC", "DC_POS", "DC_NEG", "V_INSERTED", "I_ARM", "ENERGY"), "bounding_box": [-10, -10, 10, 10]},
        "cigre_mmc_avm_v1:MMCStationControl": {"ports": _ports("P_ORDER", "Q_ORDER", "VDC_ORDER", "GATES"), "bounding_box": [-10, -10, 10, 10]},
        "cigre_mmc_avm_v1:MMCEnergyControl": {"ports": _ports("ENERGY_REF", "ENERGY", "I_CIRC"), "bounding_box": [-10, -10, 10, 10]},
        "cigre_mmc_avm_v1:MMCInitialization": {"ports": _ports("RESET", "READY"), "bounding_box": [-10, -10, 10, 10]},
    },
}
INVENTORY = {
    "pscad_version": "4.6.2",
    "definitions": {name: {"ports": [port["name"] for port in definition["ports"]]} for name, definition in CATALOG["definitions"].items()},
}


ASSET = MmcAssetSet(
    name="cigre_b4_p2p_avm_v1",
    schema_version=1,
    pscad_version="4.6.2",
    companion_library="library/cigre_mmc_avm_v1.pslx",
    blueprint=BLUEPRINT,
    catalog=CATALOG,
    acceptance={"windows": [{"name": name, "required": True} for name in ("precharge_ready", "forward_steady", "power_reversal", "reverse_steady")]},
    golden={"source": {"builder_generated": False}},
    provenance="public source and original derivation",
    hashes={"library/cigre_mmc_avm_v1.pslx": "a" * 64},
    library_bytes=b"library",
    files={},
)


def _request(**changes) -> MmcPlanRequest:
    values = {"project_name": "MMC_STAGE_A", "folder": None, "simulation_duration_s": None, "blueprint": "cigre_b4_p2p_avm_v1"}
    values.update(changes)
    return MmcPlanRequest(**values)


def _asset(blueprint=BLUEPRINT, catalog=CATALOG):
    return replace(ASSET, blueprint=blueprint, catalog=catalog)


def _assert_code(call, code):
    with pytest.raises(BackendError) as raised:
        call()
    assert raised.value.code == code


def test_create_plan_is_deterministic_and_expands_fixed_topology_without_writes(tmp_path):
    first = create_plan(_request(), ASSET, INVENTORY, tmp_path)
    second = create_plan(_request(), ASSET, INVENTORY, tmp_path)

    assert first.to_dict() == second.to_dict()
    assert first.plan_hash == second.plan_hash
    assert first.asset_hashes == ASSET.hashes
    assert len([operation for operation in first.operations if operation.phase == "place_arm"]) == 12
    assert len([operation for operation in first.operations if operation.kind == "create_phase_midpoint"]) == 6
    assert {operation.target for operation in first.operations if operation.kind == "create_dc_terminal"} == {"positive", "negative"}
    assert {operation.target for operation in first.operations if operation.kind == "create_output"} == {output.logical_id for output in BLUEPRINT.outputs}
    assert "ground" not in " ".join(operation.target for operation in first.operations if operation.kind == "connect_net").casefold()
    assert list(tmp_path.iterdir()) == []


def test_planner_rejects_unsupported_version_missing_definition_and_existing_target(tmp_path):
    _assert_code(lambda: create_plan(_request(blueprint="other"), ASSET, INVENTORY, tmp_path), "MMC_BLUEPRINT_NOT_FOUND")
    missing = copy.deepcopy(INVENTORY)
    del missing["definitions"]["master:source3"]
    _assert_code(lambda: create_plan(_request(), ASSET, missing, tmp_path), "MMC_DEFINITION_MISSING")
    _assert_code(lambda: create_plan(_request(), ASSET, {**INVENTORY, "pscad_version": "5.0"}, tmp_path), "MMC_VERSION_UNSUPPORTED")
    (tmp_path / "MMC_STAGE_A.pscx").write_bytes(b"existing")
    _assert_code(lambda: create_plan(_request(), ASSET, INVENTORY, tmp_path), "MMC_BUILD_CONFLICT")


def test_planner_rejects_port_drift_diagonal_route_and_unbacked_output(tmp_path):
    missing_port = copy.deepcopy(INVENTORY)
    missing_port["definitions"]["cigre_mmc_avm_v1:MMCAverageArm"]["ports"].remove("ENERGY")
    _assert_code(lambda: create_plan(_request(), ASSET, missing_port, tmp_path), "MMC_PORT_MISMATCH")

    diagonal = replace(BLUEPRINT, nets=(replace(BLUEPRINT.nets[0], route=((0, 0), (1, 2))),) + BLUEPRINT.nets[1:])
    _assert_code(lambda: create_plan(_request(), _asset(diagonal), INVENTORY, tmp_path), "MMC_LAYOUT_INVALID")

    outputs = list(BLUEPRINT.outputs)
    outputs[0] = replace(outputs[0], measurement="missing_endpoint")
    unbacked = replace(BLUEPRINT, outputs=tuple(outputs))
    _assert_code(lambda: create_plan(_request(), _asset(unbacked), INVENTORY, tmp_path), "MMC_BLUEPRINT_INVALID")


def test_planner_rejects_overlap_and_ac_dc_short_path(tmp_path):
    components = list(BLUEPRINT.components)
    components[1] = replace(components[1], location=components[0].location)
    overlap = replace(BLUEPRINT, components=tuple(components))
    _assert_code(lambda: create_plan(_request(), _asset(overlap), INVENTORY, tmp_path), "MMC_LAYOUT_INVALID")

    nets = list(BLUEPRINT.nets)
    nets.append(MmcNetSpec(logical_id="ac_dc_short", kind="electrical", endpoints=("STATION_P.ac:AC", "dc_positive_line:IN")))
    short = replace(BLUEPRINT, nets=tuple(nets))
    _assert_code(lambda: create_plan(_request(), _asset(short), INVENTORY, tmp_path), "MMC_STRUCTURE_INVALID")
