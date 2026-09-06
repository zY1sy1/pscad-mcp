from __future__ import annotations

import asyncio
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.master_bindings import parse_master_binding_registry
from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set
from pscad_mcp.hvdc.builders.lcc.executor import (
    LccExecutor,
    _legacy_project_settings,
    _same_setting,
)
from pscad_mcp.hvdc.builders.lcc.executor import execute_build as _execute_build
from pscad_mcp.hvdc.builders.lcc.models import (
    LccBlueprint,
    LccBuildPlan,
    LccBuildState,
    LccComponentSpec,
    LccEndpoint,
    LccNetSpec,
    LccOutputSpec,
    LccPlanOperation,
    LccRoute,
)
from pscad_mcp.hvdc.builders.lcc.project_graph import (
    GraphComponent,
    GraphLabel,
    GraphNet,
    GraphPort,
    GraphWire,
    ProjectGraph,
)
from tests.lcc_builder_fakes import RecordingPscadService
from tests.lcc_dynamic_fakes import passing_raw_channels
from tests.test_lcc_smoke import contract as smoke_contract
from tests.test_lcc_smoke import mutate_samples, valid_samples


def execute_build(*args, **kwargs):
    kwargs.setdefault("allow_test_double", True)
    return _execute_build(*args, **kwargs)


@pytest.mark.parametrize(
    ("expected", "observed", "matches"),
    [
        (50.0, 49.99999999999999, True),
        (50.0, 49.99, False),
        (0.0, 1e-8, False),
        (True, 1, False),
        ("Y-delta", "Y-delta", True),
        ("Y-delta", "Y-Y", False),
    ],
)
def test_parameter_readback_allows_only_numeric_serialization_noise(
    expected,
    observed,
    matches,
):
    assert _same_setting(expected, observed) is matches


class OutputFileRecordingService(RecordingPscadService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.discovered_project_name = None

    async def discover_output_files(self, project_name: str, *, started_after: float, max_files: int = 100) -> list[str]:
        self.discovered_project_name = project_name
        self._call("discover_output_files", project_name, started_after, max_files)
        output = Path(project_name).parent / "result.out"
        output.write_text("placeholder", encoding="utf-8")
        return [str(output)]

    async def read_output_file(self, file_path: str, max_samples: int = 10_000, channel: str | None = None, summary_only: bool = False) -> dict[str, object]:
        self._call("read_output_file", file_path, max_samples, channel, summary_only)
        return {"path": file_path, "verdict": "PASS"}


class PhysicalizedSavedGraphService(RecordingPscadService):
    def _write_project(self, path: Path, project_name: str | None = None) -> None:
        super()._write_project(path, project_name)
        root = ET.parse(path).getroot()
        definition = root.find("./definition")
        assert definition is not None
        for component in definition.findall("./component"):
            component.set("logical_id", str(component.get("definition")))
        ET.SubElement(
            definition,
            "component",
            {
                "id": "999",
                "logical_id": "master:pgb",
                "definition": "master:pgb",
                "x": "72",
                "y": "72",
                "orientation": "0",
            },
        )
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class ReloadingRecordingService(RecordingPscadService):
    async def reload_project(self, project_name, filename):
        self._call("reload_project", project_name, filename)
        return "reloaded"


def test_executor_validates_readback_projection_for_physicalized_saved_graph(
    tmp_path,
):
    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            PhysicalizedSavedGraphService(),
            tmp_path,
            build_id="build-physicalized-graph",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "published"


def test_executor_rejects_planned_net_missing_from_saved_project(tmp_path):
    plan = _plan(tmp_path)
    source, load = plan.blueprint.components
    source = replace(
        source,
        ports=("P",),
        port_contracts=({"name": "P", "kind": "electrical", "dimension": 1},),
    )
    load = replace(
        load,
        ports=("P",),
        port_contracts=({"name": "P", "kind": "electrical", "dimension": 1},),
    )
    net = LccNetSpec(
        "source_to_load",
        "electrical",
        (LccEndpoint("source", "P"), LccEndpoint("load", "P")),
        LccRoute(((10, 20), (40, 20))),
    )
    plan = replace(
        plan,
        blueprint=replace(
            plan.blueprint,
            components=(source, load),
            nets=(net,),
        ),
    )
    executor = LccExecutor(plan, RecordingPscadService(), tmp_path)
    executor.component_ids = {"source": 1, "load": 2}
    executor._logical_components = {
        "source": GraphComponent(
            "source",
            "master:source",
            "Main",
            (10, 20),
            0,
            {"LogicalId": "source"},
            (GraphPort("P", "electrical", 1, (0, 0), (10, 20)),),
        ),
        "load": GraphComponent(
            "load",
            "master:load",
            "Main",
            (40, 20),
            0,
            {"LogicalId": "load"},
            (GraphPort("P", "electrical", 1, (0, 0), (40, 20)),),
        ),
    }
    executor._logical_nets = {
        "source_to_load": GraphNet(
            "electrical",
            ((10, 20), (40, 20)),
            (),
            ("source:P", "load:P"),
        )
    }
    saved = tmp_path / "missing-wire.pscx"
    writer = RecordingPscadService()
    writer.components = {
        1: {
            "id": 1,
            "logical_id": "source",
            "definition": "master:source",
            "x": 10,
            "y": 20,
            "orientation": 0,
            "parameters": {"LogicalId": "source"},
        },
        2: {
            "id": 2,
            "logical_id": "load",
            "definition": "master:load",
            "x": 40,
            "y": 20,
            "orientation": 0,
            "parameters": {"LogicalId": "load"},
        },
    }
    writer._write_project(saved, executor.project_name)

    with pytest.raises(BackendError) as raised:
        executor._validate_graph(saved)

    assert raised.value.code == "LCC_STRUCTURE_INVALID"

    root = ET.parse(saved).getroot()
    definition = root.find("./definition")
    assert definition is not None
    wire = ET.SubElement(
        definition,
        "wire",
        {"id": "3", "x": "10", "y": "20", "kind": "electrical"},
    )
    ET.SubElement(wire, "vertex", {"x": "0", "y": "0"})
    endpoint = ET.SubElement(wire, "vertex", {"x": "30", "y": "0"})
    ET.ElementTree(root).write(saved, encoding="utf-8", xml_declaration=True)

    assert executor._validate_graph(saved)["valid"] is True

    endpoint.set("x", "20")
    ET.ElementTree(root).write(saved, encoding="utf-8", xml_declaration=True)
    with pytest.raises(BackendError) as drifted:
        executor._validate_graph(saved)

    assert drifted.value.code == "LCC_STRUCTURE_INVALID"


def test_saved_projection_accepts_only_registry_declared_filter_expansion(
    tmp_path,
):
    assets = load_packaged_asset_set()
    binding = assets.master_bindings.by_logical_name[
        "master:ac_filter_branch"
    ]
    operation = LccPlanOperation(
        1,
        "place_component",
        "filter",
        {
            "definition": "master:ac_filter_branch",
            "location": [342, 198],
            "binding": {
                "logical_name": binding.logical_name,
                "physical_definition": binding.physical_definition,
            },
        },
        "place_power:filter:000",
        "place_power",
    )
    executor = LccExecutor(
        replace(_plan(tmp_path), operations=(operation,)),
        RecordingPscadService(),
        tmp_path,
        asset_set=assets,
    )
    executor.component_ids = {"filter": 1}
    executor._logical_components = {
        "filter": GraphComponent(
            "filter",
            "master:ac_filter_branch",
            "Main",
            (342, 198),
            0,
            {},
        )
    }
    physical_components = (
        (1, "master:cfilter", (342, 198)),
        (2, "master:cfilter", (342, 342)),
        (3, "master:cfilter", (342, 486)),
        (4, "master:ground", (396, 252)),
        (5, "master:ground", (396, 396)),
        (6, "master:ground", (396, 540)),
    )
    saved = ProjectGraph(
        "executor",
        "4.6.2",
        tuple(
            GraphComponent(
                definition,
                definition,
                "Main",
                location,
                0,
                {},
                component_id=str(component_id),
            )
            for component_id, definition, location in physical_components
        ),
        (
            GraphWire("electrical", ((342, 252), (396, 252))),
            GraphWire("electrical", ((342, 396), (396, 396))),
            GraphWire("electrical", ((342, 540), (396, 540))),
        ),
        (),
        (),
    )

    projected, findings = executor._saved_logical_graph(saved)

    assert findings == []
    assert [component.logical_id for component in projected.components] == [
        "filter"
    ]
    assert projected.wires == ()
    assert projected.nets == ()

    _projected, missing_wire_findings = executor._saved_logical_graph(
        replace(saved, wires=saved.wires[:-1])
    )
    assert {
        finding["reason"] for finding in missing_wire_findings
    } == {"bound physical wire missing from saved PSCX"}

    _projected, missing_findings = executor._saved_logical_graph(
        replace(saved, components=saved.components[:-1])
    )
    assert {
        finding["reason"] for finding in missing_findings
    } == {"bound physical component missing from saved PSCX"}

    unexplained = GraphComponent(
        "master:resistor",
        "master:resistor",
        "Main",
        (900, 900),
        0,
        {},
        component_id="99",
    )
    _projected, extra_findings = executor._saved_logical_graph(
        replace(saved, components=(*saved.components, unexplained))
    )
    assert {
        finding["reason"] for finding in extra_findings
    } == {"unexpected saved component"}


def test_saved_projection_maps_bound_main_signal_import_from_data_label(
    tmp_path,
):
    operation = LccPlanOperation(
        1,
        "place_component",
        "signal_import",
        {
            "definition": "master:main_signal_import",
            "location": [18, 18],
            "binding": {
                "logical_name": "master:main_signal_import",
                "physical_definition": "datalabel",
            },
        },
        "place_measurement:signal_import:000",
        "place_measurement",
    )
    executor = LccExecutor(
        replace(_plan(tmp_path), operations=(operation,)),
        RecordingPscadService(),
        tmp_path,
    )
    executor.component_ids = {"signal_import": 7}
    executor._logical_components = {
        "signal_import": GraphComponent(
            "signal_import",
            "master:main_signal_import",
            "Main",
            (18, 18),
            0,
            {"Name": "SIGNAL_A"},
            (GraphPort("OUT", "data", 1, (0, 0), (18, 18)),),
        )
    }
    saved = ProjectGraph(
        "executor",
        "4.6.2",
        (),
        (),
        (GraphLabel("SIGNAL_A", "data", (18, 18)),),
        (),
    )

    projected, findings = executor._saved_logical_graph(saved)

    assert findings == []
    assert [component.logical_id for component in projected.components] == [
        "signal_import"
    ]


def test_saved_validation_blueprint_binds_executed_label_network(tmp_path):
    plan = _plan(tmp_path)
    net = LccNetSpec(
        "labeled_net",
        "data",
        (LccEndpoint("source", "P"), LccEndpoint("load", "P")),
        LccRoute(((10, 20), (40, 20))),
    )
    executor = LccExecutor(
        replace(plan, blueprint=replace(plan.blueprint, nets=(net,))),
        RecordingPscadService(),
        tmp_path,
    )
    executor._logical_nets = {
        "labeled_net": GraphNet(
            "data",
            ((18, 18), (36, 18)),
            ("WP1B_SHARED",),
            ("source:P", "load:P"),
        )
    }

    projected = executor._saved_validation_blueprint()

    assert projected.nets[0].label == "WP1B_SHARED"
    assert projected.nets[0].route is None


class FixedSmokeRecordingService(OutputFileRecordingService):
    def __init__(self, *, mutation: str | None = None):
        super().__init__()
        self.mutation = mutation

    async def read_output_file(
        self,
        file_path: str,
        max_samples: int = 10_000,
        channel: str | None = None,
        summary_only: bool = False,
    ) -> dict[str, object]:
        self._call(
            "read_output_file",
            file_path,
            max_samples,
            channel,
            summary_only,
        )
        payload = valid_samples()
        return (
            payload
            if self.mutation is None
            else mutate_samples(payload, self.mutation)
        )


class CompileMessageRecordingService(RecordingPscadService):
    def __init__(self, batches):
        super().__init__()
        self.batches = list(batches)

    async def get_project_output(
        self,
        project_name: str,
        structured: bool = False,
    ):
        if not structured:
            return await super().get_project_output(project_name, structured=False)
        self._call("get_project_output", project_name, structured=True)
        return self.batches.pop(0) if self.batches else []


class PredeclaredLegacyOutputService(RecordingPscadService):
    def __init__(self):
        super().__init__()
        self.saved = False

    async def create_output_channel(
        self,
        project_name,
        path,
        units,
        *,
        call_id=None,
    ):
        self._call(
            "create_output_channel",
            project_name,
            path,
            units,
            call_id=call_id,
        )
        raise BackendError(
            "CAPABILITY_UNAVAILABLE",
            "Legacy output channels are predeclared components.",
            "legacy",
            "create_output_channel",
        )

    async def save_project(self, project_name, *, confirm=False):
        await super().save_project(project_name, confirm=confirm)
        self.saved = True
        return "saved"

    async def get_output_channels(self, project_name):
        self._call("get_output_channels", project_name)
        if not self.saved:
            raise BackendError(
                "CAPABILITY_UNAVAILABLE",
                "Output metadata is not saved yet.",
                "legacy",
                "get_output_channels",
            )
        return [
            {
                "path": "Main/VDC",
                "units": "kV",
                "call_id": None,
            }
        ]


class UnavailablePredeclaredOutputService(PredeclaredLegacyOutputService):
    async def get_output_channels(self, project_name):
        self._call("get_output_channels", project_name)
        raise BackendError(
            "CAPABILITY_UNAVAILABLE",
            "Legacy output metadata is unavailable.",
            "legacy",
            "get_output_channels",
        )


def test_legacy_predeclared_output_is_saved_before_static_verification(tmp_path):
    service = PredeclaredLegacyOutputService()
    executor = LccExecutor(_plan(tmp_path), service, tmp_path)
    operation = next(
        item for item in executor.plan.operations if item.kind == "create_output"
    )

    asyncio.run(executor._create_output(operation))

    calls = [call[0] for call in service.calls]
    assert calls.index("create_output_channel") < calls.index("save_project")
    assert calls.index("save_project") < calls.index("get_output_channels")


@pytest.mark.parametrize("selector", ["Main/VDC", "Main/UNKNOWN"])
def test_wp1b_compiled_predeclared_output_falls_back_to_asset_contract(
    tmp_path,
    selector,
):
    plan = _plan_with_profile(tmp_path)
    output = LccOutputSpec(
        "vdc",
        "Main/VDC",
        "kV",
        "dc_voltage",
        measurement="vdc_measurement",
    )
    plan = replace(
        plan,
        blueprint=replace(plan.blueprint, outputs=(output,)),
    )
    assets = replace(
        _fixed_smoke_assets(plan),
        smoke={
            **smoke_contract(),
            "required_channels": ["Main/VDC"],
            "enable_channels": ["Main/VDC"],
            "ao_limits_rad": {"Main/VDC": [0.0, 1.0]},
        },
    )
    service = UnavailablePredeclaredOutputService()
    executor = LccExecutor(plan, service, tmp_path, asset_set=assets)
    executor.history.append({"state": "compiled"})
    operation = next(
        item for item in plan.operations if item.kind == "create_output"
    )
    operation = replace(
        operation,
        arguments={**operation.arguments, "path": selector},
    )

    if selector == "Main/VDC":
        asyncio.run(executor._create_output(operation))
        assert executor.history[-1]["verification"] == "compiled_asset_contract"
    else:
        with pytest.raises(BackendError) as failure:
            asyncio.run(executor._create_output(operation))
        assert failure.value.code == "LCC_OUTPUT_INCOMPLETE"


def test_wp1c_compiled_predeclared_output_falls_back_to_asset_contract(tmp_path):
    plan = _plan(tmp_path)
    output = LccOutputSpec(
        "vdc",
        "Main/VDC",
        "kV",
        "dc_voltage",
        measurement="vdc_measurement",
    )
    plan = replace(
        plan,
        verification_profile="wp1c_dynamic",
        blueprint=replace(plan.blueprint, outputs=(output,)),
    )
    service = UnavailablePredeclaredOutputService()
    executor = LccExecutor(
        plan,
        service,
        tmp_path,
        asset_set=load_packaged_asset_set(),
    )
    executor.history.append({"state": "compiled"})
    operation = next(
        item for item in plan.operations if item.kind == "create_output"
    )

    asyncio.run(executor._create_output(operation))

    assert executor.history[-1]["verification"] == "compiled_asset_contract"


def test_legacy_output_paths_are_mapped_from_measurement_components(tmp_path):
    plan = _plan_with_profile(tmp_path)
    source, load = plan.blueprint.components
    source = replace(source, ports=("P",))
    output = LccOutputSpec(
        "vdc",
        "Main/VDC",
        "kV",
        "dc_voltage",
        measurement="vdc_measurement",
    )
    plan = replace(
        plan,
        blueprint=replace(
            plan.blueprint,
            components=(source, load),
            measurements=(
                {
                    "logical_id": "vdc_measurement",
                    "component": "source",
                    "port": "P",
                },
            ),
            outputs=(output,),
        ),
    )
    executor = LccExecutor(plan, RecordingPscadService(), tmp_path)
    payload = {
        "channels": [
            {
                "path": "source/VDC",
                "domain": [0.0, 0.1],
                "values": [0.0, 1.0],
                "units": "kV",
            }
        ]
    }

    normalized = executor._logical_output_payload(payload)

    assert normalized["channels"][0]["path"] == "Main/VDC"
    assert payload["channels"][0]["path"] == "source/VDC"


def _plan(tmp_path: Path) -> LccBuildPlan:
    blueprint = LccBlueprint(
        schema_version=1,
        name="executor_test",
        topology="lcc",
        poles=1,
        terminals=2,
        settings={"simulation_duration_s": 1.0},
        components=(
            LccComponentSpec("source", "master:source", (10, 20), parameters={"LogicalId": "source"}),
            LccComponentSpec("load", "master:load", (40, 20), parameters={"LogicalId": "load"}),
        ),
        nets=(),
        outputs=(),
    )
    staging = tmp_path / ".pscad-mcp" / "lcc-builds" / "executor.staging"
    target = tmp_path / "final.pscx"
    operations = [
        LccPlanOperation(1, "materialize_library", "library/cigre.pslx", {}, "materialize:library:000", "materialize_library"),
        LccPlanOperation(2, "create_staging", "executor", {"target_path": str(target), "staging_path": str(staging)}, "create_staging:executor:000", "create_staging"),
        LccPlanOperation(3, "set_project_settings", "executor", {"settings": {"simulation_duration_s": 1.0}}, "set_settings:executor:000", "set_settings"),
        LccPlanOperation(4, "place_component", "source", {"definition": "master:source", "location": [10, 20], "orientation": 0, "parameters": {"LogicalId": "source"}, "ports": []}, "place_power:source:000", "place_power"),
        LccPlanOperation(5, "place_component", "load", {"definition": "master:load", "location": [40, 20], "orientation": 0, "parameters": {"LogicalId": "load"}, "ports": []}, "place_power:load:001", "place_power"),
        LccPlanOperation(6, "verify_parameters", "source", {"parameters": {"LogicalId": "source"}}, "verify_parameters:source:000", "verify_parameters"),
        LccPlanOperation(7, "verify_parameters", "load", {"parameters": {"LogicalId": "load"}}, "verify_parameters:load:001", "verify_parameters"),
        LccPlanOperation(8, "create_output", "vdc", {"path": "Main/VDC", "units": "kV"}, "create_outputs:vdc:000", "create_outputs"),
        LccPlanOperation(9, "save_and_validate", "executor", {}, "save_and_validate:executor:000", "save_and_validate"),
        LccPlanOperation(10, "compile", "executor", {}, "compile:executor:000", "compile"),
        LccPlanOperation(11, "simulate", "executor", {"duration_s": 1.0}, "simulate:executor:000", "simulate"),
        LccPlanOperation(12, "accept", "executor", {"required_checks": []}, "accept:executor:000", "accept"),
        LccPlanOperation(13, "publish", "executor", {"target_path": str(target)}, "publish:executor:000", "publish"),
    ]
    return LccBuildPlan(
        blueprint=blueprint,
        operations=tuple(operations),
        plan_hash="plan-hash",
        target_path=str(target),
        staging_path=str(staging),
        metadata={"project_name": "executor"},
    )


def _plan_with_connection(tmp_path: Path) -> LccBuildPlan:
    plan = _plan(tmp_path)
    operations = []
    for operation in plan.operations:
        if operation.kind == "create_output":
            operations.append(
                LccPlanOperation(
                    operation.sequence,
                    "connect_net",
                    "source_to_load",
                    {"kind": "electrical", "vertices": [[10, 20], [40, 20]]},
                    "connect_electrical:source_to_load:000",
                    "connect_electrical",
                )
            )
        operations.append(operation)
    return replace(plan, operations=tuple(operations))


def _plan_with_profile(tmp_path: Path) -> LccBuildPlan:
    plan = _plan(tmp_path)
    operations = tuple(
        replace(
            operation,
            kind="smoke_validate",
            phase="smoke_validate",
            operation_id="smoke_validate:executor:000",
            arguments={
                "contract_sha256": "s" * 64,
                "required_channels": list(smoke_contract()["required_channels"]),
            },
        )
        if operation.kind == "accept"
        else operation
        for operation in plan.operations
    )
    return replace(
        plan,
        operations=operations,
        verification_profile="wp1b_smoke",
        asset_hashes={
            "library/cigre.pslx": "l" * 64,
            "smoke.json": "s" * 64,
        },
    )


def _fixed_smoke_assets(plan: LccBuildPlan):
    packaged = load_packaged_asset_set()
    library_hash = packaged.hashes[packaged.companion_library]
    catalog = {
        "schema_version": 1,
        "name": "executor_test",
        "pscad_version": "4.6.2",
        "identity": "executor_test/catalog",
        "definitions": [
            {
                "scoped_name": "master:source",
                "ports": [],
                "parameters": {"LogicalId": {"type": "string"}},
                "bounding_box": [-10, -10, 10, 10],
            },
            {
                "scoped_name": "master:load",
                "ports": [],
                "parameters": {"LogicalId": {"type": "string"}},
                "bounding_box": [-10, -10, 10, 10],
            },
        ],
    }
    return replace(
        packaged,
        name=plan.blueprint.name,
        companion_library="library/cigre.pslx",
        blueprint=plan.blueprint,
        catalog=catalog,
        smoke=smoke_contract(),
        hashes={
            "library/cigre.pslx": library_hash,
            "smoke.json": "s" * 64,
        },
    )


def test_executor_uses_smoke_evaluator_and_records_smoke_state(tmp_path):
    service = FixedSmokeRecordingService()
    plan = _plan_with_profile(tmp_path)

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            asset_set=_fixed_smoke_assets(plan),
            build_id="fixed-smoke",
            poll_interval_s=0,
        )
    )

    assert record.state == LccBuildState.PUBLISHED
    assert [item["state"] for item in record.history if "state" in item][
        -3:
    ] == ["simulated", "smoke_passed", "published"]
    assert record.result["smoke"]["verdict"] == "PASS"
    assert "golden_checks" not in record.result["smoke"]


def test_smoke_failure_never_publishes_or_calls_acceptance(tmp_path, monkeypatch):
    service = FixedSmokeRecordingService(mutation="disabled")
    plan = _plan_with_profile(tmp_path)
    called = []
    monkeypatch.setattr(
        "pscad_mcp.hvdc.builders.lcc.executor.evaluate_acceptance",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            asset_set=_fixed_smoke_assets(plan),
            build_id="fixed-smoke-fail",
            poll_interval_s=0,
        )
    )

    assert record.state == LccBuildState.FAILED
    assert record.error["code"] == "LCC_FIXED_SMOKE_FAILED"
    assert called == []
    assert not Path(plan.target_path).exists()


def test_smoke_contract_hash_drift_fails_before_output_read(tmp_path):
    service = FixedSmokeRecordingService()
    plan = _plan_with_profile(tmp_path)
    packaged = load_packaged_asset_set()
    assets = replace(
        _fixed_smoke_assets(plan),
        hashes={
            "library/cigre.pslx": packaged.hashes[
                packaged.companion_library
            ],
            "smoke.json": "x" * 64,
        },
    )

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            asset_set=assets,
            build_id="fixed-smoke-drift",
            poll_interval_s=0,
        )
    )

    assert record.state == LccBuildState.FAILED
    assert record.error["code"] == "LCC_ASSET_MISMATCH"
    assert "read_output_file" not in [call[0] for call in service.calls]


def test_execute_build_verifies_mutations_and_publishes_after_acceptance(tmp_path):
    service = RecordingPscadService()
    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-1", poll_interval_s=0))

    assert record.state.value == "published"
    states = [entry["state"] for entry in record.history if "state" in entry]
    assert states == [
        "validated",
        "staging_created",
        "components_placed",
        "parameters_verified",
        "structure_verified",
        "staging_saved",
        "compiled",
        "simulated",
        "acceptance_passed",
        "published",
    ]
    names = [call[0] for call in service.calls]
    assert names.index("add_canvas_component") < names.index("get_component_location")
    assert names.index("get_component_parameters") < names.index("save_project")
    assert names.index("get_project_output") < names.index("save_project_as")
    assert Path(_plan(tmp_path).target_path).exists()

    journal = tmp_path / ".pscad-mcp" / "lcc-builds" / "build-1" / "journal.json"
    journal_payload = json.loads(journal.read_text(encoding="utf-8"))
    assert journal_payload["state"] == "published"
    assert journal_payload["plan"]["plan_hash"] == "plan-hash"
    assert journal_payload["target_path"] == str(Path(_plan(tmp_path).target_path))


def test_executor_rejects_structured_staging_compile_errors(tmp_path):
    service = CompileMessageRecordingService(
        [
            [
                {
                    "severity": "error",
                    "text": "Input port is floating.",
                    "source": {"kind": "build"},
                }
            ]
        ]
    )

    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            service,
            tmp_path,
            build_id="build-compile-message-error",
            poll_interval_s=0,
        )
    )

    assert record.state == LccBuildState.FAILED
    assert record.error["code"] == "LCC_BUILD_FAILED"
    assert "Input port is floating." in record.error["message"]
    names = [call[0] for call in service.calls]
    assert names.index("build_project") < names.index("get_project_output")
    assert "run_project" not in names


def test_executor_rejects_structured_final_compile_errors(tmp_path):
    service = CompileMessageRecordingService(
        [
            [],
            [
                {
                    "severity": "error",
                    "text": "Final project compile failed.",
                    "source": {"kind": "build"},
                }
            ],
        ]
    )

    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            service,
            tmp_path,
            build_id="build-final-compile-message-error",
            poll_interval_s=0,
        )
    )

    assert record.state == LccBuildState.FAILED
    assert record.error["code"] == "LCC_BUILD_FAILED"
    assert "Final project compile failed." in record.error["message"]
    assert not Path(_plan(tmp_path).target_path).exists()


def test_executor_forwards_master_binding_evidence_to_service(tmp_path):
    plan = _plan(tmp_path)
    binding = {
        "logical_name": "master:source",
        "physical_definition": "source3",
        "physical_parameters": {"Vm": 230.0},
        "evidence_parameters": {},
        "instances": ["default"],
        "selected_ports": {},
        "registry_sha256": "a" * 64,
        "master_sha256": "b" * 64,
        "verification_state": "verified",
    }
    operations = []
    for operation in plan.operations:
        if operation.kind == "place_component" and operation.target == "source":
            arguments = dict(operation.arguments)
            arguments["binding"] = binding
            operation = replace(operation, arguments=arguments)
        operations.append(operation)
    plan = replace(
        plan,
        operations=tuple(operations),
        master_sha256="b" * 64,
        master_binding_registry_sha256="a" * 64,
    )
    service = RecordingPscadService()

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            build_id="build-binding-evidence",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "published"
    call = next(
        call
        for call in service.calls
        if call[0] == "add_canvas_component" and call[1][2] == "source"
    )
    planned_binding = next(
        operation.arguments["binding"]
        for operation in plan.operations
        if operation.kind == "place_component" and operation.target == "source"
    )
    assert call[2]["binding_evidence"] == planned_binding
    verification_calls = [
        item for item in service.calls if item[0] == "verify_master_binding_state"
    ]
    assert len(verification_calls) == 4
    assert [item[2]["refresh_components"] for item in verification_calls] == [
        True,
        True,
        True,
        False,
    ]


class MasterSourceChangedAfterPlacementService(RecordingPscadService):
    async def verify_master_binding_state(self, *args, **kwargs):
        await super().verify_master_binding_state(*args, **kwargs)
        raise BackendError(
            "MASTER_SOURCE_CHANGED",
            "Master changed after placement.",
            "legacy",
            "verify_master_binding_state",
        )


def test_executor_rechecks_master_source_before_compile(tmp_path):
    plan = _plan(tmp_path)
    binding = {
        "logical_name": "master:source",
        "physical_definition": "source3",
        "physical_parameters": {},
        "evidence_parameters": {},
        "instances": ["default"],
        "selected_ports": {},
        "registry_sha256": "a" * 64,
        "master_sha256": "b" * 64,
        "verification_state": "verified",
    }
    operations = []
    for operation in plan.operations:
        if operation.kind == "place_component" and operation.target == "source":
            arguments = dict(operation.arguments)
            arguments["binding"] = binding
            operation = replace(operation, arguments=arguments)
        operations.append(operation)
    plan = replace(
        plan,
        operations=tuple(operations),
        master_sha256="b" * 64,
        master_binding_registry_sha256="a" * 64,
    )
    service = MasterSourceChangedAfterPlacementService()

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            build_id="build-master-source-changed",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "MASTER_SOURCE_CHANGED"
    names = [call[0] for call in service.calls]
    assert "verify_master_binding_state" in names
    assert "build_project" not in names


def test_executor_forwards_trusted_threshold_registry_to_acceptance(tmp_path, monkeypatch):
    registry = {"review": {"review_id": "review"}}
    captured = {}

    def fake_evaluate(samples, golden, contract, trusted_threshold_sources=None):
        captured["samples"] = samples
        captured["trusted_threshold_sources"] = trusted_threshold_sources
        return {"verdict": "PASS"}

    monkeypatch.setattr("pscad_mcp.hvdc.builders.lcc.executor.evaluate_acceptance", fake_evaluate)
    asset_set = type("Asset", (), {"golden": {}, "acceptance": {}})()
    executor = LccExecutor(
        _plan(tmp_path),
        RecordingPscadService(),
        tmp_path,
        asset_set=asset_set,
        trusted_threshold_sources=registry,
    )

    async def acceptance_output():
        return {"time": [0.0], "channels": {}}

    executor._acceptance_output = acceptance_output
    operation = next(operation for operation in executor.plan.operations if operation.kind == "accept")
    asyncio.run(executor._accept(operation))

    assert captured["trusted_threshold_sources"] is registry


class TimedScheduleBackend:
    def __init__(self, *, native: bool = True):
        self.native = native
        self.events = None

    async def get_timed_control_capabilities(self, project_name):
        return {
            "native_schedule": self.native,
            "simulation_clock": self.native,
            "time_basis": "EMTDC" if self.native else "wall_clock",
        }

    async def schedule_timed_controls(self, project_name, events):
        self.events = (project_name, list(events))
        return [{"event_id": event["event_id"], "status": "registered"} for event in events]


class TimedScheduleService(RecordingPscadService):
    def __init__(self, backend):
        super().__init__()
        self.backend_service = backend


def _dynamic_asset_set():
    bindings = []
    for logical_name in ("master:source", "master:load"):
        bindings.append(
            {
                "logical_name": logical_name,
                "physical_definition": logical_name.split(":", 1)[1],
                "shape": {"kind": "direct"},
                "ports": [
                    {
                        "logical": "P",
                        "physical": "P",
                        "kind": "electrical",
                        "dimension": 1,
                        "occurrence": 0,
                    }
                ],
                "parameters": [
                    {
                        "logical": ["LogicalId"],
                        "physical": ["NAME"],
                        "transform": {"kind": "identity"},
                        "physical_contracts": {
                            "NAME": {"type": "Text", "unit": None}
                        },
                    }
                ],
                "fixed_parameters": [],
                "evidence_parameters": [],
            }
        )
    registry = parse_master_binding_registry(
        {
            "schema_version": 1,
            "name": "dynamic_executor_test",
            "pscad_version": "4.6.2",
            "bindings": bindings,
        }
    )
    return type("DynamicAssetSet", (), {"master_bindings": registry})()


def test_executor_registers_dynamic_events_with_native_emtdc_scheduler(tmp_path):
    backend = TimedScheduleBackend()
    executor = LccExecutor(
        _plan(tmp_path),
        TimedScheduleService(backend),
        tmp_path,
        asset_set=_dynamic_asset_set(),
    )
    executor.component_ids = {"source": 41, "load": 42}
    operation = LccPlanOperation(
        sequence=1,
        kind="register_dynamic_events",
        target="CIGRE_LCC",
        arguments={
            "events": [
                {"event_id": "fault-a-on", "time_s": 0.8, "target": "source.LogicalId", "value": 1},
                {"event_id": "fault-b-on", "time_s": 0.8, "target": "load.LogicalId", "value": 1},
                {"event_id": "fault-a-off", "time_s": 0.9, "target": "source.LogicalId", "value": 0},
                {"event_id": "fault-b-off", "time_s": 0.9, "target": "load.LogicalId", "value": 0},
            ]
        },
    )

    asyncio.run(executor._register_dynamic_events(operation))

    assert backend.events == (
        executor.project_name,
        [
            {
                **event,
                "component_id": 41 if event["target"].startswith("source.") else 42,
                "parameter_name": "NAME",
            }
            for event in operation.arguments["events"]
        ],
    )
    assert executor.result["dynamic_schedule"]["status"] == "PASS"
    assert len(executor.result["dynamic_schedule"]["acknowledgements"]) == 4


@pytest.mark.parametrize(
    ("target", "event_ids"),
    [
        ("missing.LogicalId", ("fault-on", "fault-off")),
        ("source.Unknown", ("fault-on", "fault-off")),
        ("source.LogicalId", ("fault-on", "fault-on")),
    ],
)
def test_executor_rejects_unresolved_or_ambiguous_dynamic_targets(
    tmp_path, target, event_ids
):
    backend = TimedScheduleBackend()
    executor = LccExecutor(
        _plan(tmp_path),
        TimedScheduleService(backend),
        tmp_path,
        asset_set=_dynamic_asset_set(),
    )
    executor.component_ids = {"source": 41, "load": 42}
    operation = LccPlanOperation(
        sequence=1,
        kind="register_dynamic_events",
        target="CIGRE_LCC",
        arguments={
            "events": [
                {"event_id": event_ids[0], "time_s": 0.8, "target": target, "value": 1},
                {"event_id": event_ids[1], "time_s": 0.9, "target": target, "value": 0},
            ]
        },
    )

    with pytest.raises(BackendError) as raised:
        asyncio.run(executor._register_dynamic_events(operation))

    assert raised.value.code == "LCC_DYNAMIC_EVENT_UNAVAILABLE"
    assert backend.events is None


def test_wp1c_executor_accepts_engineering_pass_without_forging_total_pass(
    tmp_path,
):
    assets = load_packaged_asset_set()
    base = _plan(tmp_path)
    plan = replace(
        base,
        blueprint=replace(
            base.blueprint,
            settings={"simulation_duration_s": 1.5, "output_step_s": 0.00005},
        ),
        verification_profile="wp1c_dynamic",
        asset_hashes={"dynamic.json": assets.hashes["dynamic.json"]},
    )
    service = RecordingPscadService(output=passing_raw_channels())
    executor = LccExecutor(plan, service, tmp_path, asset_set=assets)
    operation = LccPlanOperation(
        sequence=1,
        kind="dynamic_accept",
        target="executor",
        arguments={
            "contract_sha256": assets.hashes["dynamic.json"],
            "event": {"time_s": 0.8, "duration_s": 0.1},
        },
    )

    asyncio.run(executor._dynamic_accept(operation))

    assert executor.result["engineering_verdict"] == "PASS"
    assert executor.result["golden_verdict"] == "INCOMPLETE_ANALYSIS"
    assert executor.result["status"] == "INCOMPLETE_ANALYSIS"
    assert any(
        item.get("state") == "dynamic_engineering_passed"
        for item in executor.history
    )


def test_wp1c_executor_dynamic_failure_never_publishes(tmp_path):
    assets = load_packaged_asset_set()
    base = _plan(tmp_path)
    plan = replace(
        base,
        blueprint=replace(
            base.blueprint,
            settings={"simulation_duration_s": 1.5, "output_step_s": 0.00005},
        ),
        verification_profile="wp1c_dynamic",
        asset_hashes={"dynamic.json": assets.hashes["dynamic.json"]},
    )
    output = passing_raw_channels()
    gamma = next(item for item in output["channels"] if item["path"] == "Main/GAMMA_INV")
    gamma["values"] = [math.radians(18.0) for _ in gamma["values"]]
    service = RecordingPscadService(output=output)
    executor = LccExecutor(plan, service, tmp_path, asset_set=assets)
    operation = LccPlanOperation(
        sequence=1,
        kind="dynamic_accept",
        target="executor",
        arguments={"contract_sha256": assets.hashes["dynamic.json"]},
    )

    with pytest.raises(BackendError) as raised:
        asyncio.run(executor._dynamic_accept(operation))

    assert raised.value.code == "LCC_DYNAMIC_ACCEPTANCE_FAILED"
    assert "save_project_as" not in [call[0] for call in service.calls]


def test_executor_rejects_dynamic_events_without_native_emtdc_scheduler(tmp_path):
    executor = LccExecutor(
        _plan(tmp_path),
        TimedScheduleService(TimedScheduleBackend(native=False)),
        tmp_path,
        asset_set=_dynamic_asset_set(),
    )
    executor.component_ids = {"source": 41, "load": 42}
    operation = LccPlanOperation(
        sequence=1,
        kind="register_dynamic_events",
        target="CIGRE_LCC",
        arguments={"events": [{"event_id": "fault-on", "time_s": 0.8, "target": "source.LogicalId", "value": 1}]},
    )

    with pytest.raises(BackendError) as raised:
        asyncio.run(executor._register_dynamic_events(operation))
    assert raised.value.code == "LCC_DYNAMIC_EVENT_UNAVAILABLE"


def _dynamic_control_operation(**overrides):
    arguments = {
        "control_mode": "embedded_emtdc",
        "control_signal": "LCC_FAULT_ACTIVE",
        "timer_component": "inverter_fault_timer",
        "control_components": [
            "inverter_fault_breaker_a",
            "inverter_fault_breaker_b",
            "inverter_fault_breaker_c",
        ],
        "channel": "Fault/LCC Fault Active",
        "event": {"time_s": 0.8, "duration_s": 0.1},
    }
    arguments.update(overrides)
    return LccPlanOperation(
        sequence=1,
        kind="verify_dynamic_control",
        target="CIGRE_LCC",
        arguments=arguments,
    )


def _dynamic_control_executor(tmp_path, *, service=None, **plan_overrides):
    plan = replace(_plan(tmp_path), verification_profile="wp1c_dynamic", **plan_overrides)
    executor = LccExecutor(plan, service or RecordingPscadService(), tmp_path)
    executor.history.append({"state": LccBuildState.COMPILED.value})
    executor.component_ids = {
        "inverter_fault_timer": 10,
        "inverter_fault_breaker_a": 11,
        "inverter_fault_breaker_b": 12,
        "inverter_fault_breaker_c": 13,
    }
    executor.service.components = {
        10: {"parameters": {"FaultTime_s": 0.8, "FaultDuration_s": 0.1}},
        11: {"parameters": {"NAME": "LCC_FAULT_ACTIVE"}},
        12: {"parameters": {"NAME": "LCC_FAULT_ACTIVE"}},
        13: {"parameters": {"NAME": "LCC_FAULT_ACTIVE"}},
    }
    return executor


def test_executor_verifies_embedded_dynamic_control_after_compile(tmp_path):
    service = RecordingPscadService()
    executor = _dynamic_control_executor(tmp_path, service=service)

    asyncio.run(executor._dispatch(_dynamic_control_operation()))

    assert executor.result["dynamic_control"] == {
        "status": "PASS",
        "mode": "embedded_emtdc",
        "signal": "LCC_FAULT_ACTIVE",
        "timer_component_id": 10,
        "consumer_component_ids": [11, 12, 13],
        "output": "Fault/LCC Fault Active",
        "source": "compiled_project_readback",
    }


def test_executor_rejects_duplicate_dynamic_control_consumers(tmp_path):
    service = RecordingPscadService()
    executor = _dynamic_control_executor(tmp_path, service=service)
    operation = _dynamic_control_operation(
        control_components=[
            "inverter_fault_breaker_a",
            "inverter_fault_breaker_a",
            "inverter_fault_breaker_a",
        ]
    )

    with pytest.raises(BackendError) as raised:
        asyncio.run(executor._verify_dynamic_control(operation))

    assert raised.value.code == "LCC_DYNAMIC_EVENT_UNAVAILABLE"
    assert "run_project" not in [call[0] for call in service.calls]


def test_recording_fake_persists_symbolic_parameter_values(tmp_path):
    service = RecordingPscadService()
    service.components = {
        11: {
            "id": 11,
            "logical_id": "breaker",
            "definition": "master:breaker",
            "x": 0,
            "y": 0,
            "orientation": 0,
            "parameters": {"NAME": "LCC_FAULT_ACTIVE"},
        }
    }
    project = tmp_path / "readback.pscx"
    service._write_project(project)

    parameter = ET.parse(project).find("./definition/component/parameters/param")
    assert parameter is not None
    assert parameter.get("value") == "LCC_FAULT_ACTIVE"
    assert asyncio.run(service.get_component_parameters("readback", 11))["NAME"] == "LCC_FAULT_ACTIVE"


@pytest.mark.parametrize(
    ("case", "operation_kwargs", "history", "component_ids", "components"),
    [
        (
            "numeric_name",
            {},
            [{"state": LccBuildState.COMPILED.value}],
            None,
            {11: {"parameters": {"NAME": 1}}},
        ),
        (
            "different_symbol",
            {},
            [{"state": LccBuildState.COMPILED.value}],
            None,
            {11: {"parameters": {"NAME": "OTHER_SIGNAL"}}},
        ),
        (
            "missing_timer",
            {},
            [{"state": LccBuildState.COMPILED.value}],
            {"inverter_fault_breaker_a": 11, "inverter_fault_breaker_b": 12, "inverter_fault_breaker_c": 13},
            None,
        ),
        (
            "timing_mismatch",
            {"event": {"time_s": 0.7, "duration_s": 0.1}},
            [{"state": LccBuildState.COMPILED.value}],
            None,
            None,
        ),
        (
            "pre_compiled",
            {},
            [],
            None,
            None,
        ),
    ],
)
def test_executor_rejects_unavailable_embedded_dynamic_control(
    tmp_path, case, operation_kwargs, history, component_ids, components
):
    executor = _dynamic_control_executor(tmp_path)
    executor.history = list(history)
    if component_ids is not None:
        executor.component_ids = component_ids
    if components is not None:
        for component_id, component in components.items():
            executor.service.components[component_id] = component
    with pytest.raises(BackendError) as raised:
        asyncio.run(executor._verify_dynamic_control(_dynamic_control_operation(**operation_kwargs)))
    assert raised.value.code == "LCC_DYNAMIC_EVENT_UNAVAILABLE", case
    assert "run_project" not in [call[0] for call in executor.service.calls]


class DynamicMasterBindingFailureService(RecordingPscadService):
    async def verify_master_binding_state(self, *args, **kwargs):
        await super().verify_master_binding_state(*args, **kwargs)
        raise BackendError(
            "MASTER_SOURCE_CHANGED",
            "Master changed after placement.",
            "hvdc",
            "verify_master_binding_state",
        )


def test_executor_maps_pinned_master_readback_failure_to_dynamic_unavailable(tmp_path):
    service = DynamicMasterBindingFailureService()
    executor = _dynamic_control_executor(
        tmp_path,
        service=service,
        master_sha256="b" * 64,
        master_binding_registry_sha256="a" * 64,
    )

    with pytest.raises(BackendError) as raised:
        asyncio.run(executor._verify_dynamic_control(_dynamic_control_operation()))

    assert raised.value.code == "LCC_DYNAMIC_EVENT_UNAVAILABLE"
    assert "run_project" not in [call[0] for call in service.calls]


def test_execute_build_rejects_unverified_companion_library_before_loading(tmp_path):
    asset_set = load_packaged_asset_set()
    invalid_library = b"<pslx><definition name='unexpected' /></pslx>"
    hashes = dict(asset_set.hashes)
    hashes[asset_set.companion_library] = hashlib.sha256(invalid_library).hexdigest()
    asset_set = replace(asset_set, hashes=hashes, library_bytes=invalid_library)
    service = RecordingPscadService()

    record = asyncio.run(
        _execute_build(
            _plan(tmp_path),
            service,
            tmp_path,
            asset_set=asset_set,
            build_id="build-invalid-library",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_COMPANION_INVALID"
    assert "load_projects" not in [call[0] for call in service.calls]


def test_publish_reloads_final_identity_before_compile_smoke(tmp_path):
    service = RecordingPscadService()

    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-final-identity", poll_interval_s=0))

    assert record.state.value == "published"
    load_calls = [call for call in service.calls if call[0] == "load_projects"]
    assert load_calls[-1][1][0] == [str(Path(_plan(tmp_path).target_path).resolve())]
    build_calls = [call[1][0] for call in service.calls if call[0] == "build_project"]
    assert build_calls[-1] == "final"
    publication = next(entry for entry in record.history if entry.get("state") == "published")
    assert isinstance(publication.get("final_project_sha256"), str)
    assert len(publication["final_project_sha256"]) == 64


def test_publish_same_identity_uses_unload_reload_boundary(tmp_path):
    plan = _plan(tmp_path)
    target = tmp_path / "executor.pscx"
    operations = []
    for operation in plan.operations:
        if operation.kind == "create_staging":
            arguments = {**operation.arguments, "target_path": str(target)}
            operation = replace(operation, arguments=arguments)
        elif operation.kind == "publish":
            operation = replace(
                operation,
                arguments={**operation.arguments, "target_path": str(target)},
            )
        operations.append(operation)
    plan = replace(
        plan,
        target_path=str(target),
        operations=tuple(operations),
    )
    service = ReloadingRecordingService()

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            build_id="build-same-final-identity",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "published"
    reload_call = next(
        call for call in service.calls if call[0] == "reload_project"
    )
    assert reload_call[1] == ("executor", str(target.resolve()))


def test_execute_build_reads_waveforms_from_a_discovered_output_file(tmp_path):
    service = OutputFileRecordingService()

    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-output-file", poll_interval_s=0))

    assert record.state.value == "published"
    names = [call[0] for call in service.calls]
    assert names.index("discover_output_files") < names.index("read_output_file")
    compile_message_calls = [
        call for call in service.calls if call[0] == "get_project_output"
    ]
    assert compile_message_calls
    assert all(
        call[2].get("structured") is True for call in compile_message_calls
    )
    assert service.discovered_project_name == str(service.project_file.resolve())
    assert record.result["output_file"] == str((service.project_file.parent / "result.out").resolve())


class GroupedOutputFileService(OutputFileRecordingService):
    async def discover_output_files(
        self,
        project_name: str,
        *,
        started_after: float,
        max_files: int = 100,
    ) -> list[str]:
        self.discovered_project_name = project_name
        self._call("discover_output_files", project_name, started_after, max_files)
        root = Path(project_name).parent
        outputs = []
        for index in range(1, 4):
            output = root / f"result_{index:02d}.out"
            output.write_text("placeholder", encoding="utf-8")
            outputs.append(str(output))
        return outputs


def test_execute_build_treats_legacy_output_parts_as_one_dataset(tmp_path):
    service = GroupedOutputFileService()

    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            service,
            tmp_path,
            build_id="build-output-parts",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "published"
    assert record.result["output_file"].endswith("result_01.out")
    read_calls = [call for call in service.calls if call[0] == "read_output_file"]
    assert len(read_calls) == 1
    assert read_calls[0][1][0].endswith("result_01.out")


class ExternalOutputFileService(OutputFileRecordingService):
    async def discover_output_files(self, project_name: str, *, started_after: float, max_files: int = 100) -> list[str]:
        self.discovered_project_name = project_name
        self._call("discover_output_files", project_name, started_after, max_files)
        output = Path(project_name).parent.parent / "external.out"
        output.write_text("external", encoding="utf-8")
        return [str(output)]


class InternalSymlinkOutputFileService(OutputFileRecordingService):
    async def discover_output_files(self, project_name: str, *, started_after: float, max_files: int = 100) -> list[str]:
        self.discovered_project_name = project_name
        self._call("discover_output_files", project_name, started_after, max_files)
        output = Path(project_name).parent / "result.out"
        output.write_text("placeholder", encoding="utf-8")
        alias = Path(project_name).parent / "alias.out"
        alias.symlink_to(output)
        return [str(alias)]


class AmbiguousOutputFileService(OutputFileRecordingService):
    async def discover_output_files(self, project_name: str, *, started_after: float, max_files: int = 100) -> list[str]:
        self.discovered_project_name = project_name
        self._call("discover_output_files", project_name, started_after, max_files)
        first = Path(project_name).parent / "first.out"
        second = Path(project_name).parent / "second.out"
        first.write_text("first", encoding="utf-8")
        second.write_text("second", encoding="utf-8")
        return [str(first), str(second)]


class BlockingRunStatusService(RecordingPscadService):
    def __init__(self):
        super().__init__(run_statuses=["running"])
        self.status_started = asyncio.Event()
        self.stopped = False

    async def stop_simulation(self, project_name: str) -> str:
        self._call("stop_simulation", project_name)
        self.stopped = True
        return "stopped"

    async def get_run_status(self, project_name: str) -> dict[str, str]:
        self._call("get_run_status", project_name)
        if self.stopped:
            return {"status": "stopped"}
        self.status_started.set()
        await asyncio.sleep(60)
        return {"status": "running"}


class RunCommandAcknowledgementLostService(RecordingPscadService):
    async def run_project(self, project_name: str) -> str:
        self._call("run_project", project_name)
        raise RuntimeError("run command acknowledgement lost after submission")


def test_execute_build_stops_when_run_command_acknowledgement_is_lost(tmp_path):
    service = RunCommandAcknowledgementLostService()

    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            service,
            tmp_path,
            build_id="build-run-ack-lost",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    names = [call[0] for call in service.calls]
    assert names.index("run_project") < names.index("stop_simulation")


def test_execute_build_stops_simulation_when_cancelled(tmp_path):
    service = BlockingRunStatusService()

    async def scenario():
        task = asyncio.create_task(
            execute_build(_plan(tmp_path), service, tmp_path, build_id="build-cancelled", poll_interval_s=0)
        )
        await service.status_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    names = [call[0] for call in service.calls]
    assert names.index("run_project") < names.index("stop_simulation")


def test_execute_build_rejects_waveform_outside_staging_ownership(tmp_path):
    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            ExternalOutputFileService(),
            tmp_path,
            build_id="build-external-output",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_OUTPUT_INCOMPLETE"
    assert record.error["details"]["reason"] == "output_outside_staging"


def test_execute_build_rejects_waveform_symlink_inside_staging(tmp_path):
    probe_target = tmp_path / "symlink-target"
    probe_alias = tmp_path / "symlink-alias"
    probe_target.write_text("probe", encoding="utf-8")
    try:
        probe_alias.symlink_to(probe_target)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            InternalSymlinkOutputFileService(),
            tmp_path,
            build_id="build-internal-symlink-output",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_OUTPUT_INCOMPLETE"
    assert record.error["details"]["reason"] == "output_not_regular"


def test_execute_build_rejects_ambiguous_waveform_candidates(tmp_path):
    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            AmbiguousOutputFileService(),
            tmp_path,
            build_id="build-ambiguous-output",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_OUTPUT_INCOMPLETE"
    assert record.error["details"]["reason"] == "output_ambiguous"


class MissingOutputSelectorService(RecordingPscadService):
    async def get_output_channels(self, project_name: str) -> list[dict[str, object]]:
        self._call("get_output_channels", project_name)
        return []


class DuplicateOutputSelectorService(RecordingPscadService):
    async def get_output_channels(self, project_name: str) -> list[dict[str, object]]:
        self._call("get_output_channels", project_name)
        return [
            {"path": "Main/VDC", "units": "kV", "call_id": None},
            {"path": "Main/VDC", "units": "kV", "call_id": None},
        ]


class NoOutputMutationService(RecordingPscadService):
    create_output_channel = None


def test_execute_build_rejects_missing_output_creation_capability(tmp_path):
    service = NoOutputMutationService()

    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-no-output-create", poll_interval_s=0))

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_OUTPUT_INCOMPLETE"
    assert record.error["details"]["reason"] == "output_channel_mutation_unavailable"
    assert "run_project" not in [call[0] for call in service.calls]


class EscapingStagingService(RecordingPscadService):
    async def create_project(self, kind: str, filename: str, folder: str, *, confirm: bool = False) -> dict[str, str]:
        self._call("create_project", kind, filename, folder, confirm=confirm)
        return {"name": "outside", "filename": str(Path(folder).parent / "outside.pscx")}


class ExternalReplacementAfterPublicationService(RecordingPscadService):
    async def load_projects(self, filenames: list[str]) -> str:
        result = await super().load_projects(filenames)
        if filenames and Path(filenames[0]).suffix == ".pscx" and Path(filenames[0]).name == "final.pscx":
            Path(filenames[0]).write_text("external replacement", encoding="utf-8")
        return result


def test_execute_build_rejects_backend_staging_path_escape(tmp_path):
    record = asyncio.run(execute_build(_plan(tmp_path), EscapingStagingService(), tmp_path, build_id="build-staging-escape", poll_interval_s=0))

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_POSTCONDITION_FAILED"
    assert not (tmp_path / "outside.pscx").exists()


def test_execute_build_rejects_missing_output_selector_before_simulation(tmp_path):
    service = MissingOutputSelectorService()

    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-missing-output", poll_interval_s=0))

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_OUTPUT_INCOMPLETE"
    names = [call[0] for call in service.calls]
    assert "get_output_channels" in names
    assert "run_project" not in names


def test_execute_build_rejects_ambiguous_output_selector_before_simulation(tmp_path):
    service = DuplicateOutputSelectorService()

    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-duplicate-output", poll_interval_s=0))

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_OUTPUT_INCOMPLETE"
    assert record.error["details"]["matches"] == 2
    assert "run_project" not in [call[0] for call in service.calls]


class MismatchedDefinitionService(RecordingPscadService):
    async def add_canvas_component(self, *args, **kwargs):
        created = await super().add_canvas_component(*args, **kwargs)
        created["definition"] = "master:unexpected"
        return created


class MismatchedTransformerConnectionService(RecordingPscadService):
    async def get_component_parameters(self, project_name, component_id):
        observed = await super().get_component_parameters(project_name, component_id)
        if component_id == 1:
            observed["Connection"] = "Y-Y"
        return observed


class MismatchedOrientationService(RecordingPscadService):
    async def add_canvas_component(self, *args, **kwargs):
        created = await super().add_canvas_component(*args, **kwargs)
        created["orientation"] = 7
        return created


class MismatchedConnectionService(RecordingPscadService):
    async def create_connection(self, *args, **kwargs):
        created = await super().create_connection(*args, **kwargs)
        created["p1"] = [999, 999]
        return created


class SnappedRouteEndpointService(RecordingPscadService):
    async def get_component_ports(self, project_name, component_id):
        self._call("get_component_ports", project_name, component_id)
        return {
            "P": {
                "name": "P",
                "x": 342 if component_id == 1 else 520,
                "y": 396 if component_id == 1 else 130,
            }
        }


class GroundReturnEndpointService(RecordingPscadService):
    async def get_component_ports(self, project_name, component_id):
        self._call("get_component_ports", project_name, component_id)
        point = (1980, 207) if component_id == 1 else (1908, 450)
        name = "DC_POS" if component_id == 1 else "GND"
        return {name: {"name": name, "x": point[0], "y": point[1]}}


class ThreeEndpointService(RecordingPscadService):
    async def get_component_ports(self, project_name, component_id):
        self._call("get_component_ports", project_name, component_id)
        points = {
            1: (0, 0),
            2: (0, 18),
            3: (36, 36),
        }
        x, y = points[component_id]
        return {"A": {"name": "A", "x": x, "y": y}}


def test_three_endpoint_labeled_electrical_net_uses_labels_without_crossing_wire(
    tmp_path,
):
    service = ThreeEndpointService()
    executor = LccExecutor(_plan(tmp_path), service, tmp_path)
    executor.component_ids = {"source": 1, "meter": 2, "breaker": 3}
    operation = LccPlanOperation(
        1,
        "connect_net",
        "source_meter_breaker",
        {
            "kind": "electrical",
            "vertices": [[0, 0], [0, 18], [36, 18], [36, 36]],
            "endpoints": ["source:A", "meter:A", "breaker:A"],
            "label": "SHARED_AC",
        },
        "connect_electrical:source_meter_breaker:000",
        "connect_electrical",
    )

    asyncio.run(executor._connect_net(operation))

    connections = [call for call in service.calls if call[0] == "create_connection"]
    assert [call[1][1:5] for call in connections] == [
        ([0, 0], [0, 0], "SHARED_AC", True),
        ([0, 18], [0, 18], "SHARED_AC", True),
        ([36, 36], [36, 36], "SHARED_AC", True),
    ]
    wires = [call for call in service.calls if call[0] == "create_wire"]
    assert wires == []
    assert executor._logical_nets["source_meter_breaker"].points == (
        (0, 0),
        (0, 18),
        (36, 18),
        (36, 36),
    )
    assert executor._logical_nets["source_meter_breaker"].endpoints == (
        "source:A",
        "meter:A",
        "breaker:A",
    )


def test_ground_return_wires_terminate_at_both_component_ports(tmp_path):
    plan = _plan(tmp_path)
    source, ground = plan.blueprint.components
    source = replace(source, definition="cigre_lcc_v1:LCC12PulseBridge")
    ground = replace(ground, definition="master:ground")
    executor = LccExecutor(
        replace(
            plan,
            blueprint=replace(plan.blueprint, components=(source, ground)),
        ),
        GroundReturnEndpointService(),
        tmp_path,
    )
    executor.component_ids = {"source": 1, "load": 2}
    operation = LccPlanOperation(
        1,
        "connect_net",
        "inverter_return",
        {
            "kind": "electrical",
            "vertices": [[1972, 201], [1900, 201], [1900, 450]],
            "endpoints": ["source:DC_POS", "load:GND"],
        },
        "connect_electrical:inverter_return:000",
        "connect_electrical",
    )

    asyncio.run(executor._connect_net(operation))

    wires = [call[1][1] for call in executor.service.calls if call[0] == "create_wire"]
    assert len(wires) == 2
    assert {tuple(wire[-1]) for wire in wires} == {(1980, 207), (1908, 450)}
    assert tuple(wires[0][0]) == tuple(wires[1][0])


def test_connect_net_preserves_orthogonality_after_snapping_collapses_a_bend(
    tmp_path,
):
    service = SnappedRouteEndpointService()
    executor = LccExecutor(_plan(tmp_path), service, tmp_path)
    executor.component_ids = {"source": 1, "load": 2}
    source, load = executor.plan.blueprint.components
    source = replace(
        source,
        location=(342, 396),
        ports=("P",),
        port_contracts=({"name": "P", "kind": "data", "dimension": 1},),
    )
    load = replace(
        load,
        location=(520, 130),
        ports=("P",),
        port_contracts=({"name": "P", "kind": "data", "dimension": 1},),
    )
    route = LccRoute(
        ((342, 396), (462, 396), (462, 130), (520, 130))
    )
    executor.plan = replace(
        executor.plan,
        blueprint=replace(
            executor.plan.blueprint,
            components=(source, load),
            nets=(
                LccNetSpec(
                    "snapped_route",
                    "data",
                    (LccEndpoint("source", "P"), LccEndpoint("load", "P")),
                    route,
                ),
            ),
        ),
    )
    executor._logical_components = {
        "source": GraphComponent(
            "source",
            "master:source",
            "Main",
            (342, 396),
            0,
            {"LogicalId": "source"},
            (GraphPort("P", "data", 1, (0, 0), (342, 396)),),
        ),
        "load": GraphComponent(
            "load",
            "master:load",
            "Main",
            (520, 130),
            0,
            {"LogicalId": "load"},
            (GraphPort("P", "data", 1, (0, 0), (520, 130)),),
        ),
    }
    operation = LccPlanOperation(
        1,
        "connect_net",
        "snapped_route",
        {
            "kind": "data",
            "vertices": [
                [342, 396],
                [462, 396],
                [462, 130],
                [520, 130],
            ],
            "endpoints": ["source:P", "load:P"],
        },
        "connect_data:snapped_route:000",
        "connect_data",
    )

    asyncio.run(executor._connect_net(operation))

    call = next(item for item in service.calls if item[0] == "create_wire")
    assert call[1][1] == [
        [342, 396],
        [468, 396],
        [468, 126],
        [468, 130],
        [520, 130],
    ]

    saved = tmp_path / "snapped-route.pscx"
    writer = RecordingPscadService()
    writer.components = {
        1: {
            "id": 1,
            "logical_id": "source",
            "definition": "master:source",
            "x": 342,
            "y": 396,
            "orientation": 0,
            "parameters": {"LogicalId": "source"},
        },
        2: {
            "id": 2,
            "logical_id": "load",
            "definition": "master:load",
            "x": 520,
            "y": 130,
            "orientation": 0,
            "parameters": {"LogicalId": "load"},
        },
    }
    writer._write_project(saved, executor.project_name)
    root = ET.parse(saved).getroot()
    definition = root.find("./definition")
    assert definition is not None
    wire = ET.SubElement(
        definition,
        "wire",
        {"id": "3", "x": "0", "y": "0", "kind": "data"},
    )
    for x, y in call[1][1]:
        ET.SubElement(wire, "vertex", {"x": str(x), "y": str(y)})
    ET.ElementTree(root).write(saved, encoding="utf-8", xml_declaration=True)

    assert executor._validate_graph(saved)["valid"] is True


@pytest.mark.parametrize(
    "vertices",
    [
        [[0, 0], [9, 9]],
        [[1, 1], [2, 1]],
    ],
)
def test_connect_net_rejects_invalid_transformed_route_before_backend(
    tmp_path,
    vertices,
):
    service = RecordingPscadService()
    executor = LccExecutor(_plan(tmp_path), service, tmp_path)
    operation = LccPlanOperation(
        1,
        "connect_net",
        "invalid_route",
        {"kind": "data", "vertices": vertices},
        "connect_data:invalid_route:000",
        "connect_data",
    )

    with pytest.raises(BackendError) as raised:
        asyncio.run(executor._connect_net(operation))

    assert raised.value.code == "LCC_LAYOUT_INVALID"
    assert "create_wire" not in [call[0] for call in service.calls]


class StrictConnectionArgumentService(RecordingPscadService):
    async def create_connection(
        self,
        project_name,
        p1,
        p2,
        label,
        electrical,
        *,
        canvas_name="Main",
    ):
        if (label is None) != (electrical is None):
            raise ValueError(
                "label and electrical must either both be provided or both omitted"
            )
        return await super().create_connection(
            project_name,
            p1,
            p2,
            label,
            electrical,
            canvas_name=canvas_name,
        )


def test_two_point_unlabeled_net_omits_electrical_flag(tmp_path):
    service = StrictConnectionArgumentService()

    record = asyncio.run(
        execute_build(
            _plan_with_connection(tmp_path),
            service,
            tmp_path,
            build_id="build-unlabeled-connection",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "published"
    connection = next(call for call in service.calls if call[0] == "create_connection")
    assert connection[1][3:5] == (None, None)


class SnappedCompanionPortService(RecordingPscadService):
    async def add_canvas_component(self, *args, **kwargs):
        created = await super().add_canvas_component(*args, **kwargs)
        component = self.components[created["id"]]
        component["x"] = round(component["x"] / 18) * 18
        component["y"] = round(component["y"] / 18) * 18
        created["location"] = {"x": component["x"], "y": component["y"]}
        return created

    async def get_component_ports(self, project_name, component_id):
        self._call("get_component_ports", project_name, component_id)
        component = self.components[component_id]
        return [
            {
                "name": "ACD_A",
                "x": component["x"] - 72,
                "y": component["y"] - 36,
                "dim": 1,
                "type": "electrical",
            }
        ]


class RealDataCompanionPortService(SnappedCompanionPortService):
    async def get_component_ports(self, project_name, component_id):
        self._call("get_component_ports", project_name, component_id)
        component = self.components[component_id]
        return [
            {
                "name": "AM_D",
                "x": component["x"] + 72,
                "y": component["y"] + 45,
                "dim": 1,
                "type": "Real",
            }
        ]


def test_companion_port_readback_uses_verified_snapped_component_origin(tmp_path):
    service = SnappedCompanionPortService()
    executor = LccExecutor(
        _plan(tmp_path),
        service,
        tmp_path,
        asset_set=load_packaged_asset_set(),
    )
    operation = LccPlanOperation(
        1,
        "place_component",
        "rectifier_bridge",
        {
            "definition": "cigre_lcc_v1:LCC12PulseBridge",
            "location": [800, 210],
            "orientation": 0,
            "parameters": {"UP": 1},
            "ports": ["ACD_A"],
            "canvas": "Main",
        },
        "place_power:rectifier_bridge:000",
        "place_power",
    )

    asyncio.run(executor._place_component(operation))

    assert executor.component_ids["rectifier_bridge"] == 1
    assert service.components[1]["x"] == 792
    assert service.components[1]["y"] == 216
    assert executor._logical_components["rectifier_bridge"].ports[
        0
    ].absolute == (720, 180)


def test_companion_real_port_readback_matches_data_contract(tmp_path):
    service = RealDataCompanionPortService()
    executor = LccExecutor(
        _plan(tmp_path),
        service,
        tmp_path,
        asset_set=load_packaged_asset_set(),
    )
    operation = LccPlanOperation(
        1,
        "place_component",
        "rectifier_bridge",
        {
            "definition": "cigre_lcc_v1:LCC12PulseBridge",
            "location": [800, 210],
            "orientation": 0,
            "parameters": {"UP": 1},
            "ports": ["AM_D"],
            "canvas": "Main",
        },
        "place_power:rectifier_bridge:000",
        "place_power",
    )

    asyncio.run(executor._place_component(operation))

    assert executor.component_ids["rectifier_bridge"] == 1


@pytest.mark.parametrize(
    ("service_type", "reason"),
    [
        (MismatchedDefinitionService, "definition"),
        (MismatchedOrientationService, "orientation"),
    ],
)
def test_execute_build_rejects_component_identity_drift(tmp_path, service_type, reason):
    service = service_type()

    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            service,
            tmp_path,
            build_id=f"build-component-{reason}",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_POSTCONDITION_FAILED"
    assert reason in record.error["details"]
    assert "run_project" not in [call[0] for call in service.calls]


def test_execute_build_verifies_transformer_connection_readback(tmp_path):
    plan = _plan(tmp_path)
    components = list(plan.blueprint.components)
    components[0] = replace(
        components[0],
        definition="master:converter_transformer",
        parameters={"LogicalId": "source", "Connection": "Y-delta"},
    )
    operations = []
    for operation in plan.operations:
        if operation.target == "source" and operation.kind in {
            "place_component",
            "verify_parameters",
        }:
            arguments = dict(operation.arguments)
            arguments["definition"] = "master:converter_transformer"
            arguments["parameters"] = {
                "LogicalId": "source",
                "Connection": "Y-delta",
            }
            operation = replace(operation, arguments=arguments)
        operations.append(operation)
    plan = replace(
        plan,
        blueprint=replace(plan.blueprint, components=tuple(components)),
        operations=tuple(operations),
    )
    service = MismatchedTransformerConnectionService()

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            build_id="build-transformer-connection",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_PARAMETER_MISMATCH"
    assert "run_project" not in [call[0] for call in service.calls]


def test_execute_build_rejects_connection_endpoint_drift(tmp_path):
    service = MismatchedConnectionService()

    record = asyncio.run(
        execute_build(
            _plan_with_connection(tmp_path),
            service,
            tmp_path,
            build_id="build-connection-endpoint",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_POSTCONDITION_FAILED"
    assert "run_project" not in [call[0] for call in service.calls]


def test_execute_build_fails_closed_when_staging_path_already_exists(tmp_path):
    plan = _plan(tmp_path)
    staging = Path(plan.staging_path)
    staging.mkdir(parents=True)

    record = asyncio.run(
        execute_build(plan, RecordingPscadService(), tmp_path, build_id="build-stale-staging", poll_interval_s=0)
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_BUILD_CONFLICT"
    assert not (tmp_path / "final.pscx").exists()


def test_execute_build_never_quarantines_a_preexisting_final_target(tmp_path):
    plan = _plan(tmp_path)
    target = Path(plan.target_path)
    target.write_text("external", encoding="utf-8")

    record = asyncio.run(
        execute_build(plan, RecordingPscadService(), tmp_path, build_id="build-external-target", poll_interval_s=0)
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_BUILD_CONFLICT"
    assert target.read_text(encoding="utf-8") == "external"


def test_execute_build_never_quarantines_a_replaced_published_target(tmp_path):
    plan = _plan(tmp_path)
    target = Path(plan.target_path)

    record = asyncio.run(
        execute_build(
            plan,
            ExternalReplacementAfterPublicationService(),
            tmp_path,
            build_id="build-replaced-final",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert target.read_text(encoding="utf-8") == "external replacement"
    cleanup = [entry for entry in record.history if "publication_cleanup" in entry]
    assert cleanup[-1]["publication_cleanup"]["action"] == "preserved_external_replacement"


@pytest.mark.parametrize("failure", ["create_project", "get_component_parameters", "save_project", "build_project", "run_project", "get_project_output", "save_project_as"])
def test_execute_build_contains_failures_and_never_publishes(tmp_path, failure):
    service = RecordingPscadService(fail_on=failure)
    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id=f"build-{failure}", poll_interval_s=0))

    assert record.state.value == "failed"
    assert not Path(_plan(tmp_path).target_path).exists()
    assert Path(record.workspace).exists()
    assert record.error["backend"] == "hvdc"
    calls = [call[0] for call in service.calls]
    if failure in calls:
        assert calls.index(failure) == max(index for index, name in enumerate(calls) if name == failure)
    journal = tmp_path / ".pscad-mcp" / "lcc-builds" / f"build-{failure}" / "journal.json"
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "failed"


def test_execute_build_rejects_simulation_terminal_state_without_observed_run(tmp_path):
    service = RecordingPscadService(run_statuses=["completed"])
    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-no-run", poll_interval_s=0, timeout_s=0))

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_BUILD_TIMED_OUT"


def test_execute_build_stops_simulation_before_reporting_timeout(tmp_path):
    service = RecordingPscadService(run_statuses=["running", "running"])
    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            service,
            tmp_path,
            build_id="build-timeout-stop",
            poll_interval_s=0,
            timeout_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_BUILD_TIMED_OUT"
    names = [call[0] for call in service.calls]
    assert names.index("run_project") < names.index("stop_simulation")


def test_execute_build_without_assets_cannot_fabricate_acceptance_pass(tmp_path):
    record = asyncio.run(_execute_build(_plan(tmp_path), RecordingPscadService(), tmp_path, build_id="build-no-assets"))

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_ACCEPTANCE_FAILED"
    assert record.result["verdict"] == "INCOMPLETE_ANALYSIS"


def test_legacy_project_settings_map_seconds_to_pscad_46_microseconds():
    mapped = _legacy_project_settings(
        {
            "simulation_duration_s": 1.0,
            "time_step_s": 0.00005,
            "output_step_s": 0.00025,
            "output_enabled": True,
            "compiler_target": "fortran",
        }
    )
    assert mapped == {
        "time_duration": 1.0,
        "time_step": 50,
        "sample_step": 250,
        "PlotType": 1,
    }
