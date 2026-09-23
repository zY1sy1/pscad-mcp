from __future__ import annotations

import asyncio
import copy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.common.serialization import json_safe
from pscad_mcp.hvdc.builders.mmc.engines.avm import AvmBlueprintEngine
from pscad_mcp.hvdc.builders.mmc.executor import MmcExecutor
from pscad_mcp.hvdc.builders.mmc.master_bindings import audit_mmc_master_bindings
from pscad_mcp.hvdc.builders.mmc.models import MmcComponentSpec, MmcNetSpec
from pscad_mcp.hvdc.builders.mmc.planner import MmcPlanRequest, create_plan
from pscad_mcp.hvdc.builders.mmc.service import MmcBuilderService
from tests.mmc_parametric_fakes import avm_parametric_plan
from tests.test_mmc_planner import ASSET, CATALOG, INVENTORY

MASTER = Path("C:/Program Files (x86)/PSCAD46/master.pslx")
pytestmark = pytest.mark.skipif(
    not MASTER.is_file(), reason="Static installed Master XML required"
)


@pytest.fixture
def bound_assets():
    context = audit_mmc_master_bindings(MASTER)
    catalog = copy.deepcopy(CATALOG)
    catalog["definitions"]["test:Cable"] = catalog["definitions"].pop("master:dc_cable")
    catalog["definitions"]["master:ground"] = {
        "ports": [{"name": "GND", "kind": "electrical", "dimension": 1}]
    }
    components = []
    neutral_nets = []
    for index, component in enumerate(ASSET.blueprint.components):
        parameters = dict(component.parameters)
        ports = component.ports
        definition = component.definition
        if definition == "master:source3":
            parameters = {
                "Name": f"SOURCE_{index}",
                "Amplitude": 400.0,
                "Frequency": 50.0,
                "GridR": 3.0,
                "GridX": 4.0,
            }
        elif definition == "master:transformer":
            parameters = {
                "Name": f"XFMR_{index}",
                "RatedPower_MVA": 1100.0,
                "Primary_kV": 400.0,
                "Secondary_kV": 320.0,
                "Frequency": 50.0,
                "Leakage_pu": 0.15,
            }
        elif definition == "master:dc_bus":
            parameters = {"Name": f"DC_NODE_{index}"}
        elif definition == "master:dc_cable":
            definition = "test:Cable"
        if definition in {"master:source3", "master:transformer"}:
            ports = (*ports, "NEUTRAL")
            ground_id = f"neutral_ground_{index}"
            components.append(
                MmcComponentSpec(
                    ground_id, "master:ground", (-500, index * 360), ports=("GND",)
                )
            )
            neutral_nets.append(
                MmcNetSpec(
                    f"neutral_reference_{index}",
                    "electrical",
                    (f"{component.logical_id}:NEUTRAL", f"{ground_id}:GND"),
                )
            )
        components.append(
            replace(
                component,
                definition=definition,
                parameters=parameters,
                ports=ports,
                location=(index * 720, 1000 + index * 720),
            )
        )
    inventory = copy.deepcopy(INVENTORY)
    inventory["definitions"]["test:Cable"] = inventory["definitions"].pop(
        "master:dc_cable"
    )
    inventory["definitions"].update(json_safe(context.audited.definitions))
    inventory.update(
        master_path=str(MASTER),
        master_sha256=context.audited.master_sha256,
        master_binding_registry_sha256=context.audited.registry.sha256,
    )
    blueprint = replace(
        ASSET.blueprint,
        components=tuple(components),
        nets=(*ASSET.blueprint.nets, *neutral_nets),
    )
    return replace(ASSET, blueprint=blueprint, catalog=catalog), inventory


def test_native_binding_evidence_reaches_placement_and_routing(bound_assets, tmp_path):
    asset, inventory = bound_assets
    plan = create_plan(MmcPlanRequest("MMC_BOUND"), asset, inventory, tmp_path)
    source = next(
        op
        for op in plan.operations
        if op.kind == "place_component" and op.target == "STATION_P.ac"
    )
    assert source.arguments["binding"]["physical_parameters"]["Es"] == 400.0
    assert source.arguments["binding"]["physical_parameters"]["F0"] == 50.0
    assert source.arguments["parameters"]["GridMagnitude"] == 5.0
    assert plan.metadata["master_sha256"] == inventory["master_sha256"]
    route = next(
        op
        for op in plan.operations
        if op.kind == "connect_net" and op.target == "ac_station_p"
    )
    assert tuple(route.arguments["vertices"][0]) == (36, 1000)
    assert (
        plan.plan_hash
        == create_plan(
            MmcPlanRequest("MMC_BOUND"), asset, inventory, tmp_path
        ).plan_hash
    )


@pytest.mark.parametrize("field", ["master_sha256", "master_binding_registry_sha256"])
def test_plan_rejects_stale_native_binding_identity(bound_assets, tmp_path, field):
    asset, inventory = bound_assets
    inventory[field] = "0" * 64
    with pytest.raises(BackendError) as raised:
        create_plan(MmcPlanRequest("MMC_BOUND"), asset, inventory, tmp_path)
    assert raised.value.code == "MASTER_SOURCE_CHANGED"
    assert not list(tmp_path.iterdir())


def test_plan_rejects_forged_observed_terminal(bound_assets, tmp_path):
    asset, inventory = bound_assets
    inventory["definitions"]["master:source3"]["selected_ports"]["NEUTRAL"][
        "occurrence"
    ] = 0
    with pytest.raises(BackendError) as raised:
        create_plan(MmcPlanRequest("MMC_BOUND"), asset, inventory, tmp_path)
    assert raised.value.code == "MASTER_SOURCE_CHANGED"


def test_plan_rejects_floating_source_neutral(bound_assets, tmp_path):
    asset, inventory = bound_assets
    blueprint = replace(
        asset.blueprint,
        nets=tuple(
            net
            for net in asset.blueprint.nets
            if "STATION_P.ac:NEUTRAL" not in net.endpoints
        ),
    )
    with pytest.raises(BackendError) as raised:
        create_plan(
            MmcPlanRequest("MMC_BOUND"),
            replace(asset, blueprint=blueprint),
            inventory,
            tmp_path,
        )
    assert raised.value.code == "MMC_STRUCTURE_INVALID"
    assert "neutral" in str(raised.value).casefold()


def test_plan_rejects_dc_pole_ground_even_when_reference_is_renamed(
    bound_assets, tmp_path
):
    asset, inventory = bound_assets
    renamed = {
        component.logical_id: f"g{index}"
        for index, component in enumerate(asset.blueprint.components)
        if component.definition == "master:ground"
    }
    components = tuple(
        replace(
            component,
            logical_id=renamed.get(component.logical_id, component.logical_id),
        )
        for component in asset.blueprint.components
    )
    nets = tuple(
        replace(
            net,
            endpoints=tuple(
                f"{renamed.get(owner, owner)}:{port}"
                for owner, port in (
                    endpoint.split(":", 1) for endpoint in net.endpoints
                )
            ),
        )
        for net in asset.blueprint.nets
    )
    pole_ground = MmcNetSpec(
        "pole_reference",
        "electrical",
        ("STATION_P.positive_bus:DC", f"{next(iter(renamed.values()))}:GND"),
    )
    blueprint = replace(
        asset.blueprint, components=components, nets=(*nets, pole_ground)
    )
    with pytest.raises(BackendError) as raised:
        create_plan(
            MmcPlanRequest("MMC_BOUND"),
            replace(asset, blueprint=blueprint),
            inventory,
            tmp_path,
        )
    assert raised.value.code == "MMC_STRUCTURE_INVALID"


def test_service_queries_binding_aware_inventory(bound_assets, tmp_path):
    asset, inventory = bound_assets
    calls = []

    async def get_inventory(catalog, registry):
        calls.append((catalog, registry))
        return {
            **inventory,
            "definitions": {
                name: record
                for name, record in inventory["definitions"].items()
                if name in catalog["definitions"]
            },
        }

    service = MmcBuilderService(
        SimpleNamespace(get_lcc_inventory=get_inventory),
        workspace_root=tmp_path,
        asset_loader=lambda _: asset,
    )
    plan = service.plan_model("MMC_BOUND")
    assert len(calls) == 1
    assert calls[0][1]["pscad_version"] == "4.6.2"
    assert "master:pi_controller" in calls[0][0]["definitions"]
    assert plan["metadata"]["master_sha256"] == inventory["master_sha256"]


def test_parametric_engine_requests_native_binding_evidence(tmp_path):
    calls = []

    async def get_inventory(catalog, registry):
        calls.append((catalog, registry))
        return INVENTORY

    engine = AvmBlueprintEngine(asset_set=ASSET)
    with pytest.raises(BackendError) as raised:
        asyncio.run(
            engine.execute_candidate(
                avm_parametric_plan(tmp_path),
                SimpleNamespace(get_lcc_inventory=get_inventory),
            )
        )
    assert raised.value.code == "MASTER_BINDING_MISSING"
    assert len(calls) == 1
    assert calls[0][1]["pscad_version"] == "4.6.2"
    assert not (tmp_path / ".mmc-candidates").exists()


def test_executor_forwards_binding_and_checks_readback(bound_assets, tmp_path):
    asset, inventory = bound_assets
    plan = create_plan(MmcPlanRequest("MMC_BOUND"), asset, inventory, tmp_path)
    operation = next(
        op
        for op in plan.operations
        if op.kind == "place_component" and op.target == "STATION_P.ac"
    )
    calls = []

    async def add(*args, **kwargs):
        calls.append(kwargs)
        return {"id": 7}

    async def parameters(*args):
        return {
            name: str(value)
            for name, value in operation.arguments["parameters"].items()
        }

    async def location(*args):
        return list(operation.arguments["location"])

    async def ports(*args):
        return {
            name: {
                "name": name,
                "x": operation.arguments["location"][0] + value["offset"][0],
                "y": operation.arguments["location"][1] + value["offset"][1],
                "dim": value["dimension"],
                "type": value["type"],
            }
            for name, value in operation.arguments["binding"]["selected_ports"].items()
        }

    service = SimpleNamespace(
        add_canvas_component=add,
        get_component_parameters=parameters,
        get_component_location=location,
        get_component_ports=ports,
    )
    executor = MmcExecutor(plan, service, tmp_path)
    asyncio.run(executor._place_component(operation))
    assert calls[0]["binding_evidence"] == json_safe(operation.arguments["binding"])

    async def changed_ports(*args):
        value = await ports(*args)
        value["NEUTRAL"]["x"] += 36
        return value

    service.get_component_ports = changed_ports
    with pytest.raises(BackendError) as raised:
        asyncio.run(executor._place_component(operation))
    assert raised.value.code == "MMC_PORT_MISMATCH"


def test_executor_rechecks_all_native_bindings_before_compile(bound_assets, tmp_path):
    asset, inventory = bound_assets
    plan = create_plan(MmcPlanRequest("MMC_BOUND"), asset, inventory, tmp_path)
    events = []

    async def verify(project, components, master_hash, registry_hash, **kwargs):
        events.append(("verify", components, master_hash, registry_hash))
        raise BackendError("MASTER_SOURCE_CHANGED", "source changed", "test", "verify")

    async def build(*args):
        events.append(("build",))

    executor = MmcExecutor(
        plan,
        SimpleNamespace(verify_master_binding_state=verify, build_project=build),
        tmp_path,
    )
    targets = {
        op.target
        for op in plan.operations
        if op.kind == "place_component" and "binding" in op.arguments
    }
    executor.component_ids = {
        target: index for index, target in enumerate(sorted(targets), 1)
    }
    operation = next(op for op in plan.operations if op.kind == "compile")
    with pytest.raises(BackendError) as raised:
        asyncio.run(executor._compile(operation))
    assert raised.value.code == "MASTER_SOURCE_CHANGED"
    assert len(events) == 1
    assert set(events[0][1]) == targets
    assert events[0][2:] == (
        inventory["master_sha256"],
        inventory["master_binding_registry_sha256"],
    )
