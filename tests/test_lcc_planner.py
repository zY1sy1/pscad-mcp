import copy
from dataclasses import replace

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.master_bindings import parse_master_binding_registry
from pscad_mcp.hvdc.builders.lcc.assets import (
    LccAssetSet,
    load_packaged_asset_set,
)
from pscad_mcp.hvdc.builders.lcc.catalog import parse_catalog
from pscad_mcp.hvdc.builders.lcc.planner import (
    LccPlanRequest,
    _component_rectangles,
    _net_route,
    create_plan,
)
from pscad_mcp.hvdc.builders.lcc.routing import route_intersects_rectangles
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

SMOKE_CONTRACT = {
    "schema_version": 1,
    "identity": "cigre_lcc_monopole_v1/wp1b_smoke",
    "duration_s": 0.1,
    "output_step_s": 0.00005,
    "required_channels": ["Main/VDC"],
    "enable_channels": ["Main/VDC"],
    "ao_limits_rad": {"Main/VDC": [0.0, 1.0]},
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
        smoke=copy.deepcopy(SMOKE_CONTRACT),
        provenance="source",
        hashes={
            "library/cigre_lcc_v1.pslx": "a" * 64,
            "smoke.json": "c" * 64,
        },
        library_bytes=b"library",
        files={},
    )


def _bound_asset_set():
    registry = parse_master_binding_registry(
        {
            "schema_version": 1,
            "name": "planner_test_registry",
            "pscad_version": "4.6.2",
            "bindings": [
                {
                    "logical_name": "master:source3",
                    "physical_definition": "source3",
                    "shape": {"kind": "direct"},
                    "ports": [
                        {
                            "logical": "ac",
                            "physical": "N3",
                            "kind": "electrical",
                            "dimension": 3,
                            "occurrence": 0,
                        }
                    ],
                    "parameters": [
                        {
                            "logical": ["Amplitude"],
                            "physical": ["Vm"],
                            "transform": {"kind": "identity"},
                            "physical_contracts": {
                                "Vm": {"type": "Real", "unit": "kV"}
                            },
                        }
                    ],
                    "fixed_parameters": [],
                    "evidence_parameters": [],
                }
            ],
        }
    )
    assets = _asset_set()
    hashes = dict(assets.hashes)
    hashes["master-bindings-pscad-4.6.2.json"] = "b" * 64
    return replace(
        assets,
        hashes=hashes,
        master_bindings=registry,
        master_binding_hash="b" * 64,
    )


def _bound_inventory(*, master_sha256: str = "a" * 64):
    registry = _bound_asset_set().master_bindings
    assert registry is not None
    return {
        "pscad_version": "4.6.2",
        "master_sha256": master_sha256,
        "master_binding_registry_sha256": registry.sha256,
        "definitions": {
            "master:source3": {
                "physical_definition": "source3",
                "verification_state": "verified",
                "ports": [
                    {
                        "name": "ac",
                        "physical": "N3",
                        "occurrence": 0,
                        "dimension": 3,
                        "kind": "electrical",
                    }
                ],
                "selected_ports": {
                    "ac": {
                        "physical": "N3",
                        "occurrence": 0,
                        "kind": "electrical",
                        "dimension": 3,
                        "raw_dimension": 3,
                        "model": "Natural",
                        "type": "NonRemovable",
                        "mode": None,
                        "condition": "View==1",
                        "offset": [36, 0],
                        "instance": None,
                    }
                },
            },
            "cigre_lcc_v1:LCC12PulseBridge": {"ports": ["ac"]},
        },
    }


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


def test_plan_contains_resolved_master_evidence_and_hashes(tmp_path):
    assets = _bound_asset_set()
    inventory = _bound_inventory()

    plan = create_plan(_request(), assets, inventory, tmp_path)

    source = next(
        operation
        for operation in plan.operations
        if operation.kind == "place_component" and operation.target == "source"
    )
    assert source.arguments["definition"] == "master:source3"
    assert source.arguments["binding"]["physical_definition"] == "source3"
    assert source.arguments["binding"]["physical_parameters"] == {"Vm": 230.0}
    assert source.arguments["binding"]["selected_ports"]["ac"]["physical"] == "N3"
    assert plan.master_sha256 == "a" * 64
    assert (
        plan.master_binding_registry_sha256
        == assets.master_bindings.sha256
    )


def test_plan_hash_changes_when_live_master_hash_changes(tmp_path):
    assets = _bound_asset_set()

    first = create_plan(_request(), assets, _bound_inventory(), tmp_path)
    second = create_plan(
        _request(),
        assets,
        _bound_inventory(master_sha256="c" * 64),
        tmp_path,
    )

    assert first.plan_hash != second.plan_hash


def test_bound_plan_rejects_missing_or_mismatched_registry_evidence(tmp_path):
    assets = _bound_asset_set()
    missing = _bound_inventory()
    del missing["master_binding_registry_sha256"]
    mismatched = _bound_inventory()
    mismatched["master_binding_registry_sha256"] = "f" * 64

    _assert_code(
        lambda: create_plan(_request(), assets, missing, tmp_path),
        "MASTER_BINDING_MISSING",
    )
    _assert_code(
        lambda: create_plan(_request(), assets, mismatched, tmp_path),
        "MASTER_SOURCE_CHANGED",
    )


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


def test_fixed_blueprint_has_two_transformer_groups_and_four_ao_nets():
    blueprint = load_packaged_asset_set().blueprint
    component_ids = {component.logical_id for component in blueprint.components}
    net_ids = {net.logical_id for net in blueprint.nets}

    assert {
        "rectifier_transformer_y",
        "rectifier_transformer_d",
        "inverter_transformer_y",
        "inverter_transformer_d",
        "initialization",
        "signal_interface",
        "vdc_rect_main_import",
        "vdc_inv_main_import",
        "idc_main_import",
    } <= component_ids
    assert {
        "rectifier_ao_y",
        "rectifier_ao_d",
        "inverter_ao_y",
        "inverter_ao_d",
        "vdc_rect_raw",
        "vdc_inv_raw",
        "idc_raw",
    } <= net_ids
    assert not any(
        endpoint.port == "GATES"
        for net in blueprint.nets
        for endpoint in net.endpoints
    )


def test_packaged_blueprint_routes_avoid_unrelated_component_rectangles():
    assets = load_packaged_asset_set()
    catalog = parse_catalog(assets.catalog)
    components = {
        component.logical_id: component
        for component in assets.blueprint.components
    }
    rectangles = list(
        _component_rectangles(assets.blueprint.components, catalog).items()
    )

    for net in assets.blueprint.nets:
        excluded = {endpoint.component for endpoint in net.endpoints}
        route_intersects_rectangles(
            _net_route(net, components, catalog),
            [
                rectangle
                for logical_id, rectangle in rectangles
                if logical_id not in excluded
            ],
        )


def test_wp1b_smoke_plan_uses_smoke_gate_and_hashes_profile(tmp_path):
    assets = _asset_set()
    request = LccPlanRequest(
        project_name="CIGRE_LCC",
        folder=str(tmp_path),
        simulation_duration_s=0.1,
        verification_profile="wp1b_smoke",
    )

    smoke = create_plan(request, assets, INVENTORY, tmp_path)
    full = create_plan(
        replace(
            request,
            simulation_duration_s=1.0,
            verification_profile="full_acceptance",
        ),
        assets,
        INVENTORY,
        tmp_path,
    )

    assert smoke.verification_profile == "wp1b_smoke"
    assert smoke.plan_hash != full.plan_hash
    assert [item.kind for item in smoke.operations][-2:] == [
        "smoke_validate",
        "publish",
    ]
    assert "accept" not in [item.kind for item in smoke.operations]
    assert [item.kind for item in full.operations][-2:] == [
        "accept",
        "publish",
    ]
    assert [
        item.arguments["path"]
        for item in smoke.operations
        if item.kind == "create_output"
    ] == list(assets.smoke["required_channels"])
    assert [
        item.arguments["path"]
        for item in full.operations
        if item.kind == "create_output"
    ] == [output.path for output in assets.blueprint.outputs]
    smoke_kinds = [item.kind for item in smoke.operations]
    assert smoke_kinds.index("save_and_validate") < smoke_kinds.index("compile")
    assert smoke_kinds.index("compile") < smoke_kinds.index("create_output")
    assert smoke_kinds.index("create_output") < smoke_kinds.index("simulate")


def test_wp1b_smoke_plan_excludes_non_smoke_derived_outputs(tmp_path):
    candidate = copy.deepcopy(BLUEPRINT)
    candidate["measurements"].append(
        {
            "logical_id": "derived_measurement",
            "kind": "electrical",
            "component": "source",
            "port": "ac",
            "channels": ["Main/DERIVED"],
            "derived_from": "vdc_measurement",
        }
    )
    candidate["outputs"].append(
        {
            "logical_id": "derived",
            "path": "Main/DERIVED",
            "units": "kV",
            "role": "derived_voltage",
            "measurement": "derived_measurement",
        }
    )
    assets = _asset_set(candidate)
    request = LccPlanRequest(
        project_name="CIGRE_LCC",
        folder=str(tmp_path),
        simulation_duration_s=0.1,
        verification_profile="wp1b_smoke",
    )

    plan = create_plan(request, assets, INVENTORY, tmp_path)

    assert [
        item.arguments["path"]
        for item in plan.operations
        if item.kind == "create_output"
    ] == ["Main/VDC"]


@pytest.mark.parametrize(
    ("profile", "duration"),
    [
        ("wp1b_smoke", 0.2),
        ("unknown", 0.1),
    ],
)
def test_wp1b_smoke_profile_rejects_wrong_duration_or_name(
    tmp_path,
    profile,
    duration,
):
    request = LccPlanRequest(
        "CIGRE_LCC",
        simulation_duration_s=duration,
        verification_profile=profile,
    )

    with pytest.raises(BackendError) as failure:
        create_plan(request, _asset_set(), INVENTORY, tmp_path)

    assert failure.value.code == "LCC_BLUEPRINT_INVALID"
