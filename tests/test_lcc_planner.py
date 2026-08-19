import copy
from dataclasses import replace
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.assets import LccAssetSet
from pscad_mcp.hvdc.builders.lcc.models import LccBlueprint
from pscad_mcp.hvdc.builders.lcc.planner import LccPlanRequest, create_plan
from pscad_mcp.hvdc.builders.lcc.schema import parse_blueprint


BLUEPRINT = {
    "schema_version": 1,
    "name": "cigre_lcc_monopole_v1",
    "topology": "lcc",
    "poles": 1,
    "terminals": 2,
    "settings": {
        "time_step_s": 5e-5,
        "output_step_s": 5e-5,
        "simulation_duration_s": 1.0,
        "compiler_target": "fortran",
        "output_enabled": True,
    },
    "components": [
        {
            "logical_id": "source",
            "definition": "master:source3",
            "location": {"x": 0, "y": 0},
            "ports": ["ac"],
            "parameters": {"Amplitude": 230.0},
        },
        {
            "logical_id": "bridge",
            "definition": "cigre_lcc_v1:LCC12PulseBridge",
            "location": {"x": 100, "y": 0},
            "ports": ["ac"],
        },
    ],
    "nets": [
        {
            "logical_id": "ac",
            "kind": "electrical",
            "endpoints": [
                {"component": "source", "port": "ac"},
                {"component": "bridge", "port": "ac"},
            ],
            "route": {"vertices": [[10, 0], [90, 0]]},
        }
    ],
    "measurements": [{
        "logical_id": "vdc_measurement",
        "kind": "electrical",
        "component": "source",
        "port": "ac",
        "channels": ["Main/VDC"],
    }],
    "outputs": [
        {
            "logical_id": "vdc",
            "path": "Main/VDC",
            "units": "kV",
            "role": "dc_voltage",
            "measurement": "vdc_measurement",
        }
    ],
}


CATALOG = {
    "schema_version": 1,
    "name": "cigre_lcc_monopole_v1",
    "pscad_version": "4.6.2",
    "identity": "cigre_lcc_monopole_v1/catalog-pscad-4.6.2",
    "definitions": [
        {
            "scoped_name": "master:source3",
            "ports": [{"name": "ac", "kind": "electrical", "dimension": 3, "offset": [10, 0]}],
            "parameters": {"Amplitude": {"type": "float", "minimum": 0, "maximum": 1000}},
            "bounding_box": [-10, -10, 10, 10],
        },
        {
            "scoped_name": "cigre_lcc_v1:LCC12PulseBridge",
            "ports": [{"name": "ac", "kind": "electrical", "dimension": 3, "offset": [-10, 0]}],
            "parameters": {},
            "bounding_box": [-10, -10, 10, 10],
        },
    ],
}


INVENTORY = {
    "pscad_version": "4.6.2",
    "definitions": {
        "master:source3": {"ports": ["ac"]},
        "cigre_lcc_v1:LCC12PulseBridge": {"ports": ["ac"]},
    },
}


def _asset_set(blueprint=None, catalog=None):
    parsed = parse_blueprint(blueprint or BLUEPRINT)
    catalog_value = catalog or CATALOG
    return LccAssetSet(
        name="cigre_lcc_monopole_v1",
        schema_version=1,
        pscad_version="4.6.2",
        companion_library="library/cigre_lcc_v1.pslx",
        blueprint=parsed,
        catalog=catalog_value,
        acceptance={"checks": [{"name": "golden", "kind": "golden", "required": True, "expected": {}}]},
        golden={"channels": {}},
        provenance="source",
        hashes={"library/cigre_lcc_v1.pslx": "a" * 64},
        library_bytes=b"library",
        files={},
    )


def _request(**overrides):
    values = {"project_name": "CIGRE_LCC", "folder": None, "simulation_duration_s": None, "blueprint": "cigre_lcc_monopole_v1"}
    values.update(overrides)
    return LccPlanRequest(**values)


def _assert_code(call, code):
    with pytest.raises(BackendError) as raised:
        call()
    assert raised.value.code == code


def test_create_plan_is_deterministic_and_side_effect_free(tmp_path):
    request = _request()
    asset_set = _asset_set()

    first = create_plan(request, asset_set, INVENTORY, tmp_path)
    second = create_plan(request, asset_set, INVENTORY, tmp_path)

    assert first.to_dict() == second.to_dict()
    assert first.plan_hash == second.plan_hash
    assert list(dict.fromkeys(operation.phase for operation in first.operations)) == [
        "materialize_library",
        "create_staging",
        "set_settings",
        "place_power",
        "verify_parameters",
        "connect_electrical",
        "create_outputs",
        "save_and_validate",
        "compile",
        "simulate",
        "accept",
        "publish",
    ]
    assert list(tmp_path.iterdir()) == []


def test_planner_rejects_existing_destination(tmp_path):
    (tmp_path / "CIGRE_LCC.pscx").write_bytes(b"existing")

    _assert_code(lambda: create_plan(_request(), _asset_set(), INVENTORY, tmp_path), "LCC_BUILD_CONFLICT")


def test_planner_rejects_dangling_symlink_destination(tmp_path):
    target = tmp_path / "CIGRE_LCC.pscx"
    try:
        target.symlink_to(tmp_path / "missing.pscx")
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    _assert_code(lambda: create_plan(_request(), _asset_set(), INVENTORY, tmp_path), "LCC_BUILD_CONFLICT")


def test_planner_rejects_missing_master_definition(tmp_path):
    inventory = copy.deepcopy(INVENTORY)
    del inventory["definitions"]["master:source3"]

    _assert_code(lambda: create_plan(_request(), _asset_set(), inventory, tmp_path), "LCC_DEFINITION_MISSING")


def test_planner_rejects_missing_companion_port(tmp_path):
    inventory = copy.deepcopy(INVENTORY)
    inventory["definitions"]["cigre_lcc_v1:LCC12PulseBridge"]["ports"] = []

    _assert_code(lambda: create_plan(_request(), _asset_set(), inventory, tmp_path), "LCC_PORT_MISMATCH")


def test_planner_rejects_short_duration_and_unsupported_version(tmp_path):
    _assert_code(
        lambda: create_plan(_request(simulation_duration_s=0.5), _asset_set(), INVENTORY, tmp_path),
        "LCC_BLUEPRINT_INVALID",
    )
    inventory = dict(INVENTORY, pscad_version="5.0")
    _assert_code(lambda: create_plan(_request(), _asset_set(), inventory, tmp_path), "LCC_VERSION_UNSUPPORTED")


def test_planner_rejects_bipolar_request_at_planner_boundary(tmp_path):
    candidate = copy.deepcopy(BLUEPRINT)
    candidate["poles"] = 2

    _assert_code(
        lambda: create_plan(_request(), _asset_set(candidate), INVENTORY, tmp_path),
        "LCC_BLUEPRINT_UNSUPPORTED",
    )


def test_planner_rejects_route_collision_and_unbacked_output(tmp_path):
    candidate = copy.deepcopy(BLUEPRINT)
    candidate["components"].append(
        {
            "logical_id": "obstacle",
            "definition": "master:source3",
            "location": {"x": 50, "y": 0},
            "parameters": {"Amplitude": 230.0},
            "ports": [],
        }
    )
    inventory = copy.deepcopy(INVENTORY)
    inventory["definitions"]["master:source3"]["ports"] = ["ac"]
    _assert_code(lambda: create_plan(_request(), _asset_set(candidate), inventory, tmp_path), "LCC_LAYOUT_INVALID")

    unbacked = copy.deepcopy(BLUEPRINT)
    unbacked["outputs"][0]["measurement"] = "missing"
    _assert_code(lambda: create_plan(_request(), _asset_set(unbacked), INVENTORY, tmp_path), "LCC_BLUEPRINT_INVALID")


def test_planner_rejects_output_measurement_without_exact_channel_binding(tmp_path):
    candidate = copy.deepcopy(BLUEPRINT)
    candidate["measurements"][0]["channels"] = ["Main/OTHER"]

    _assert_code(lambda: create_plan(_request(), _asset_set(candidate), INVENTORY, tmp_path), "LCC_BLUEPRINT_INVALID")


def test_planner_rejects_multiple_outputs_bound_to_one_measurement_endpoint(tmp_path):
    candidate = copy.deepcopy(BLUEPRINT)
    candidate["measurements"].append(
        {
            "logical_id": "duplicate_measurement",
            "kind": "electrical",
            "component": "source",
            "port": "ac",
            "channels": ["Main/OTHER"],
        }
    )
    candidate["outputs"].append(
        {
            "logical_id": "other",
            "path": "Main/OTHER",
            "units": "kV",
            "role": "other_voltage",
            "measurement": "duplicate_measurement",
        }
    )

    _assert_code(lambda: create_plan(_request(), _asset_set(candidate), INVENTORY, tmp_path), "LCC_BLUEPRINT_INVALID")


def test_planner_rejects_unimplemented_route_policy(tmp_path):
    candidate = copy.deepcopy(BLUEPRINT)
    candidate["nets"][0]["route"]["policy"] = "shortest_path"

    _assert_code(lambda: create_plan(_request(), _asset_set(candidate), INVENTORY, tmp_path), "LCC_LAYOUT_INVALID")
