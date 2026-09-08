import asyncio
import copy
import importlib
import json
import xml.etree.ElementTree as ET

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.hvdc.service import HvdcDomainService

MASTER = """<project name="master"><definitions>
<Definition name="const"><form><category><parameter name="Value" type="Real"><value>0</value></parameter></category></form>
<svg><port name="OUT" x="36" y="0" dim="1" mode="Output" type="Real" model="Transfer">true</port></svg>
<script><segment name="Fortran">      $OUT = $Value</segment></script></Definition>
<Definition name="pgb"><form><category><parameter name="Name" type="Text"><value>Untitled</value></parameter></category></form>
<svg><port name="Signl" x="0" y="0" dim="0" mode="Input" type="Real" model="Transfer">true</port></svg></Definition>
</definitions></project>"""
PROJECT = """<project name="case" version="4.6.2" Target="EMTDC">
<paramlist name="Settings"><param name="time_step" value="10"/><param name="sample_step" value="10"/>
<param name="time_duration" value="0.05"/><param name="PlotType" value="1"/></paramlist>
<definitions><Definition classid="UserCmpDefn" name="Main" id="1"><schematic>
<User classid="UserCmp" id="17" defn="master:const" x="180" y="180" orient="0">
<paramlist><param name="Name" value="Test command"/><param name="Value" value="0"/></paramlist></User>
</schematic></Definition></definitions></project>"""


def _module():
    spec = importlib.util.find_spec("pscad_mcp.hvdc.builders.mmc.timed_control")
    assert spec is not None, "Embedded EMTDC control adapter is missing"
    return importlib.import_module(spec.name)


def _inputs(tmp_path):
    source = tmp_path / "source.pscx"
    master = tmp_path / "master.pslx"
    source.write_text(PROJECT)
    master.write_text(MASTER)
    event = {
        "event_id": "pulse",
        "time_s": 0.02,
        "end_time_s": 0.03,
        "target": {
            "instance_path": "Main",
            "owner": "17",
            "definition": "master:const",
            "parameter": "Value",
        },
        "before_value": 0,
        "value": 1,
        "after_value": 0,
        "units": "1",
    }
    return source, master, event


def _plan(tmp_path, events=None):
    source, master, event = _inputs(tmp_path)
    plan = _module().plan_embedded_control(
        source,
        events or [event],
        master_path=master,
        time_step_s=1e-5,
        output_step_s=1e-5,
        duration_s=0.05,
        max_timing_error_s=2e-5,
    )
    return source, master, plan


def test_embedded_contract_is_hashed_before_exclusive_copy_and_read_back(tmp_path):
    source, _master, plan = _plan(tmp_path)
    before = source.read_bytes()
    assert plan["time_basis"] == "EMTDC"
    assert len(plan["schedule_sha256"]) == 64
    assert plan["events"][0]["event_selector"]["port"] == "Signl"
    destination = tmp_path / "derived.pscx"
    result = _module().materialize_embedded_control(plan, destination)
    assert source.read_bytes() == before
    assert result["readback"]["matched"] is True
    assert result["schedule_sha256"] == plan["schedule_sha256"]
    root = ET.parse(destination).getroot()
    script = "\n".join(node.text or "" for node in root.findall(".//segment"))
    assert "TIME" in script and "0.02" in script and "0.03" in script
    with pytest.raises(BackendError):
        _module().materialize_embedded_control(plan, destination)


@pytest.mark.parametrize(
    "override",
    [
        {"time_s": -1},
        {"time_s": float("nan")},
        {"end_time_s": 0.01},
        {"end_time_s": float("inf")},
        {"value": float("nan")},
    ],
)
def test_invalid_contract_never_modifies_source(tmp_path, override):
    source, master, event = _inputs(tmp_path)
    before = source.read_bytes()
    with pytest.raises(BackendError):
        _module().plan_embedded_control(
            source,
            [{**event, **override}],
            master_path=master,
            time_step_s=1e-5,
            output_step_s=1e-5,
            duration_s=0.05,
            max_timing_error_s=2e-5,
        )
    assert source.read_bytes() == before


def test_conflicts_rejected_but_non_overlapping_same_target_allowed(tmp_path):
    source, master, event = _inputs(tmp_path)
    options = {
        "master_path": master,
        "time_step_s": 1e-5,
        "output_step_s": 1e-5,
        "duration_s": 0.05,
        "max_timing_error_s": 2e-5,
    }
    other = {**event, "event_id": "second", "time_s": 0.025, "end_time_s": 0.04}
    with pytest.raises(BackendError):
        _module().plan_embedded_control(source, [event, other], **options)
    other["time_s"] = 0.035
    plan = _module().plan_embedded_control(source, [other, event], **options)
    assert [item["event_id"] for item in plan["events"]] == ["pulse", "second"]


@pytest.mark.parametrize("drift", ["source", "schedule", "selector"])
def test_drift_invalidates_plan_before_destination_creation(tmp_path, drift):
    source, _master, plan = _plan(tmp_path)
    if drift == "source":
        source.write_text(PROJECT.replace('value="0"', 'value="2"'))
    elif drift == "schedule":
        plan["events"][0]["value"] = 2
    else:
        plan["events"][0]["event_selector"]["owner"] = "9999"
    destination = tmp_path / "derived.pscx"
    with pytest.raises(BackendError):
        _module().materialize_embedded_control(plan, destination)
    assert not destination.exists()


def test_duplicate_owner_or_conditional_port_fails_closed(tmp_path):
    source, master, event = _inputs(tmp_path)
    source.write_text(
        PROJECT.replace(
            "</schematic>",
            PROJECT.split("<schematic>")[1].split("</schematic>")[0] + "</schematic>",
        )
    )
    with pytest.raises(BackendError):
        _module().plan_embedded_control(
            source,
            [event],
            master_path=master,
            time_step_s=1e-5,
            output_step_s=1e-5,
            duration_s=0.05,
            max_timing_error_s=2e-5,
        )


def test_saved_readback_detects_script_and_output_binding_drift(tmp_path):
    _source, _master, plan = _plan(tmp_path)
    destination = tmp_path / "derived.pscx"
    _module().materialize_embedded_control(plan, destination)
    root = ET.parse(destination)
    root.find(".//segment").text = "      $OUT = 0.0"
    root.write(destination)
    with pytest.raises(BackendError):
        _module().verify_embedded_control(plan, destination)


def test_var_cannot_use_an_unaudited_const_replacement_port(tmp_path):
    source, master, event = _inputs(tmp_path)
    source.write_text(PROJECT.replace("master:const", "master:var"))
    event["target"]["definition"] = "master:var"
    root = ET.fromstring(MASTER)
    replacement = copy.deepcopy(root.find("./definitions/Definition[@name='const']"))
    replacement.set("name", "var")
    root.find("definitions").append(replacement)
    root.find("./definitions/Definition[@name='const']/svg/port").set("x", "72")
    ET.ElementTree(root).write(master)
    with pytest.raises(BackendError):
        _module().plan_embedded_control(
            source,
            [event],
            master_path=master,
            time_step_s=1e-5,
            output_step_s=1e-5,
            duration_s=0.05,
            max_timing_error_s=2e-5,
        )


def test_saved_control_output_net_cannot_drift(tmp_path):
    source, master, event = _inputs(tmp_path)
    tree = ET.parse(source)
    wire = ET.SubElement(
        tree.find(".//schematic"),
        "Wire",
        id="20",
        classid="WireOrthogonal",
        x="216",
        y="180",
        orient="0",
    )
    ET.SubElement(wire, "vertex", x="0", y="0")
    ET.SubElement(wire, "vertex", x="36", y="0")
    tree.write(source)
    plan = _module().plan_embedded_control(
        source,
        [event],
        master_path=master,
        time_step_s=1e-5,
        output_step_s=1e-5,
        duration_s=0.05,
        max_timing_error_s=2e-5,
    )
    destination = tmp_path / "derived.pscx"
    _module().materialize_embedded_control(plan, destination)
    saved = ET.parse(destination)
    saved.findall(".//Wire/vertex")[1].set("x", "72")
    saved.write(destination)
    with pytest.raises(BackendError):
        _module().verify_embedded_control(plan, destination)


def test_planning_does_not_replace_a_callers_stale_master_identity(tmp_path):
    source, master, event = _inputs(tmp_path)
    with pytest.raises(BackendError):
        _module().plan_embedded_control(
            source,
            [event],
            master_path=master,
            time_step_s=1e-5,
            output_step_s=1e-5,
            duration_s=0.05,
            max_timing_error_s=2e-5,
            source_hashes={
                "master": {"path": str(master.resolve()), "sha256": "0" * 64}
            },
        )


def test_rehashed_invalid_serialized_plan_is_revalidated_before_mutation(tmp_path):
    _source, _master, plan = _plan(tmp_path)
    plan["events"][0]["time_s"] = -0.02
    plan["schedule_sha256"] = _module().schedule_sha256(plan)
    destination = tmp_path / "derived.pscx"
    with pytest.raises(BackendError):
        _module().materialize_embedded_control(plan, destination)
    assert not destination.exists()


def _samples(plan, *, rise=0.02, fall=0.03):
    times = [index * 1e-5 for index in range(5001)]
    return {
        "channels": [
            {
                "description": plan["event_channels"][0]["description"],
                "units": "1",
                "domain": times,
                "values": [1.0 if rise <= time < fall else 0.0 for time in times],
            }
        ]
    }


@pytest.mark.parametrize("fault", ["missing", "late", "duration", "gap"])
def test_event_waveform_requires_both_edges_and_fully_sampled_interval(tmp_path, fault):
    _, _, plan = _plan(tmp_path)
    samples = _samples(
        plan,
        rise=0.0201 if fault == "late" else 0.02,
        fall=0.031 if fault == "duration" else 0.03,
    )
    if fault == "missing":
        samples["channels"] = []
    if fault == "gap":
        samples["channels"][0]["values"][2500] = 0
    assert hasattr(_module(), "measure_event_waveforms"), (
        "Measured event acceptance is missing"
    )
    with pytest.raises(BackendError):
        _module().measure_event_waveforms(plan, samples)


@pytest.mark.parametrize("build_error", [False, True])
def test_public_scenario_compiles_embedded_events_before_run_and_verifies_output(
    tmp_path, build_error
):
    source, _, plan = _plan(tmp_path)
    profile_dir = tmp_path / ".pscad-mcp" / "hvdc-profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "event_test.json").write_text(
        json.dumps(
            {
                "profile_version": 2,
                "required_assets": [],
                "mappings": [],
                "project_fingerprints": [],
                "command_bindings": [
                    {
                        "canonical": "probe",
                        "component": {
                            "component_id": "17",
                            "definition": "master:const",
                            "canvas": "Main",
                        },
                        "parameter_name": "Value",
                        "allowed_values": [0, 1],
                        "semantics": "active_high",
                        "read_back": True,
                    }
                ],
                "result_channels": [],
                "metric_roles": {},
                "sequences": [],
            }
        )
    )
    output = tmp_path / "result_01.out"
    output.write_text("fresh fake output")

    class Backend:
        def __init__(self):
            self.calls = []

        async def load_projects(self, files):
            self.calls.append("load")

        async def list_projects(self):
            return [{"name": "derived", "type": "Case"}]

        async def save_project(self, project, *, confirm):
            assert project == "derived"
            self.calls.append("save")

        async def build_project(self, project):
            assert project == "derived"
            self.calls.append("build")

        async def get_project_output(self, project, structured=False):
            assert project == "derived"
            return (
                [
                    {
                        "severity": "error",
                        "text": "Linker could not resolve a required library",
                    }
                ]
                if build_error
                else []
            )

        async def get_project_settings(self, project):
            assert project == "derived"
            return {"PlotType": "1"}

        async def run_project(self, project):
            assert project == "derived"
            self.calls.append("run")

        async def get_run_status(self, project):
            return {"status": "completed"}

        async def discover_output_files(self, project, started_after):
            return [str(output)]

        async def read_output_file(self, path, **kwargs):
            return _samples(plan)

    backend = Backend()
    service = HvdcDomainService(
        backend, path_policy=PathPolicy(workspace_root=str(tmp_path))
    )
    scenario = {
        "name": "pulse",
        "profile": "event_test",
        "project": str(source),
        "derived_project": str(tmp_path / "derived.pscx"),
        "timed_control": plan,
        "events": [
            {
                "event_id": "pulse",
                "target": "probe",
                "time_s": 0.02,
                "end_time_s": 0.03,
                "before_value": 0,
                "value": 1,
                "after_value": 0,
                "units": "1",
            }
        ],
        "analysis": {},
        "run": {"timeout_s": 2},
    }

    async def exercise():
        result = await service.run_scenario(str(source), scenario, confirm=True)
        await service._scenario_tasks[result["scenario_id"]]
        for _ in range(10):
            if service._active_scenario_id is None:
                break
            await asyncio.sleep(0)
        return await service.scenario_status(result["scenario_id"])

    result = asyncio.run(exercise())
    if build_error:
        assert result["status"] == "failed"
        assert result["error"]["code"] == "HVDC_SCENARIO_BUILD_FAILED"
        assert "run" not in backend.calls
        assert result["reservation_held"] is False
        return
    assert result["status"] == "completed", result["error"]
    assert backend.calls.index("build") < backend.calls.index("run")
    assert backend.calls.index("save") < backend.calls.index("build")
    assert result["timing_basis"]["time_basis"] == "EMTDC"
    assert result["timing_basis"]["measured_events"][0]["rise_time_s"] == pytest.approx(
        0.02
    )
    assert result["reservation_held"] is False
    assert result["runtime_project_name"] == "derived"
