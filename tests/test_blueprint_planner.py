from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pscad_mcp.builders.blueprint.assets import hash_tree, load_blueprint_asset
from pscad_mcp.builders.blueprint.inventory import normalize_inventory
from pscad_mcp.builders.blueprint.planner import create_plan, plan_from_dict
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from tests.test_blueprint_assets import write_source_package
from tests.test_blueprint_schema import valid_blueprint


def live_inventory() -> dict:
    return {
        "pscad_version": "4.6.2",
        "definitions": {
            "master:breaker": {
                "ports": {"A": {"kind": "electrical", "dimension": 1}, "B": {"kind": "electrical", "dimension": 1}},
                "parameters": {"Name": {"resolved": True, "units": None}},
            }
        },
        "components": [
            {
                "id": 17,
                "logical_id": "source_breaker",
                "name": "BRK_SOURCE",
                "definition": "master:breaker",
                "canvas": "Main",
                "location": [10, 10],
                "orientation": 0,
                "parameters": {"Name": "BRK_SOURCE"},
                "parameter_metadata": {"Name": {"resolved": True, "units": None}},
                "ports": {"A": {"x": 9, "y": 10, "kind": "electrical", "dimension": 1}, "B": {"x": 11, "y": 10, "kind": "electrical", "dimension": 1}},
                "resolved": True,
            },
            {
                "id": 99,
                "logical_id": "legacy_unknown",
                "name": "UNKNOWN",
                "definition": "user:unknown",
                "canvas": "Main",
                "location": [100, 100],
                "orientation": 0,
                "parameters": {},
                "parameter_metadata": {},
                "ports": {},
                "resolved": False,
            },
        ],
    }


def plan(tmp_path: Path, *, blueprint=None, inventory=None, overrides=None):
    source = write_source_package(tmp_path)
    return create_plan(
        load_blueprint_asset(blueprint or valid_blueprint()),
        str(source),
        "BuiltCase",
        normalize_inventory(inventory or live_inventory()),
        PathPolicy(str(tmp_path)),
        parameter_overrides=overrides,
    )


def test_plan_is_deterministic_side_effect_free_and_binds_all_evidence(tmp_path):
    source = write_source_package(tmp_path)
    before = hash_tree(source)
    policy = PathPolicy(str(tmp_path))
    asset = load_blueprint_asset(valid_blueprint())
    inventory = normalize_inventory(live_inventory())

    first = create_plan(asset, str(source), "BuiltCase", inventory, policy)
    second = create_plan(asset, str(source), "BuiltCase", inventory, policy)

    assert first == second
    assert first.plan_hash == second.plan_hash
    assert len(first.plan_hash) == 64
    assert first.blueprint_hash == asset.hashes["blueprint.json"]
    assert first.resolved_selectors["source_breaker"] == 17
    assert first.operations[0].arguments["source_component_id"] == 17
    assert first.operations[1].target == "breaker_copy"
    assert first.warnings == ("unresolved source element left untouched: legacy_unknown",)
    assert first.staging_path.endswith(".pscad-mcp/blueprint-builds/pending/BuiltCase")
    assert hash_tree(source) == before
    assert not (tmp_path / ".pscad-mcp").exists()
    json.dumps(first.to_dict(), allow_nan=False)


def test_plan_rejects_duplicate_created_logical_ids(tmp_path):
    blueprint = valid_blueprint()
    blueprint["operations"].append(
        {
            "sequence": 3,
            "kind": "create_component",
            "target": "duplicate",
            "arguments": {
                "logical_id": "breaker_copy",
                "definition": "master:breaker",
                "location": [30, 30],
                "orientation": 0,
                "canvas": "Main",
                "parameters": {"Name": "DUPLICATE"},
                "units": {},
            },
            "operation_id": "op-003",
        }
    )

    with pytest.raises(BackendError) as raised:
        plan(tmp_path, blueprint=blueprint)

    assert raised.value.code == "BLUEPRINT_OPERATION_INVALID"


def test_plan_validates_create_component_parameters_against_live_definition(tmp_path):
    blueprint = valid_blueprint()
    blueprint["operations"] = [
        {
            "sequence": 1,
            "kind": "create_component",
            "target": "created",
            "arguments": {
                "logical_id": "created",
                "definition": "master:breaker",
                "location": [30, 30],
                "orientation": 0,
                "canvas": "Main",
                "parameters": {"Unknown": 1},
                "units": {},
            },
            "operation_id": "op-001",
        }
    ]

    with pytest.raises(BackendError) as raised:
        plan(tmp_path, blueprint=blueprint)

    assert raised.value.code == "BLUEPRINT_TARGET_UNRESOLVED"


def test_plan_hash_changes_with_source_inventory_blueprint_or_overrides(tmp_path):
    baseline = plan(tmp_path)
    (tmp_path / "source-package" / "support" / "notes.txt").write_text("changed", encoding="utf-8")
    source_changed = create_plan(
        load_blueprint_asset(valid_blueprint()),
        str(tmp_path / "source-package"),
        "BuiltCase",
        normalize_inventory(live_inventory()),
        PathPolicy(str(tmp_path)),
    )
    assert source_changed.plan_hash != baseline.plan_hash

    other_root = tmp_path / "other"
    other_root.mkdir()
    inventory_value = live_inventory()
    inventory_value["components"][0]["parameters"]["Name"] = "OTHER"
    assert plan(other_root, inventory=inventory_value).plan_hash != baseline.plan_hash

    third_root = tmp_path / "third"
    third_root.mkdir()
    blueprint_value = valid_blueprint()
    blueprint_value["identity"]["name"] = "breaker-copy-v2"
    assert plan(third_root, blueprint=blueprint_value).plan_hash != baseline.plan_hash

    fourth_root = tmp_path / "fourth"
    fourth_root.mkdir()
    assert plan(fourth_root, overrides={"breaker_copy": {"Name": "OVERRIDE"}}).plan_hash != baseline.plan_hash


@pytest.mark.parametrize("mode", ["ambiguous", "unresolved", "version", "unit", "unknown_override"])
def test_plan_rejects_stale_or_unresolved_live_contracts(tmp_path, mode):
    inventory = live_inventory()
    blueprint = valid_blueprint()
    overrides = None
    if mode == "ambiguous":
        duplicate = copy.deepcopy(inventory["components"][0])
        duplicate["id"] = 18
        inventory["components"].append(duplicate)
    elif mode == "unresolved":
        blueprint["operations"][0]["target"] = "legacy_unknown"
    elif mode == "version":
        inventory["pscad_version"] = "5.1.0"
    elif mode == "unit":
        blueprint["operations"][1]["arguments"]["units"] = {"Name": "kV"}
    else:
        overrides = {"missing": {"Name": "VALUE"}}

    with pytest.raises(BackendError) as raised:
        plan(tmp_path, blueprint=blueprint, inventory=inventory, overrides=overrides)

    assert raised.value.code in {
        "BLUEPRINT_SELECTOR_AMBIGUOUS",
        "BLUEPRINT_TARGET_UNRESOLVED",
        "BLUEPRINT_PSCAD_VERSION_UNSUPPORTED",
        "BLUEPRINT_UNIT_MISMATCH",
        "BLUEPRINT_OVERRIDE_INVALID",
    }


def test_normalize_inventory_rejects_duplicate_component_ids_and_non_finite_values():
    value = live_inventory()
    duplicate = copy.deepcopy(value["components"][0])
    duplicate["logical_id"] = "other"
    value["components"].append(duplicate)
    with pytest.raises(BackendError) as duplicate_error:
        normalize_inventory(value)
    assert duplicate_error.value.code == "BLUEPRINT_INVENTORY_INVALID"

    value = live_inventory()
    value["components"][0]["location"][0] = float("inf")
    with pytest.raises(BackendError) as finite_error:
        normalize_inventory(value)
    assert finite_error.value.code == "BLUEPRINT_INVENTORY_INVALID"


@pytest.mark.parametrize("warnings", ["one warning", 17, ["valid", 3]])
def test_plan_from_dict_rejects_invalid_warning_collections(tmp_path, warnings):
    value = plan(tmp_path).to_dict()
    value["warnings"] = warnings

    with pytest.raises(BackendError) as raised:
        plan_from_dict(value)

    assert raised.value.code == "BLUEPRINT_PLAN_INVALID"
