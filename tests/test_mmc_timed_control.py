import copy
import hashlib
import importlib
import xml.etree.ElementTree as ET

import pytest

from pscad_mcp.core.backend.base import BackendError


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
    event = {"event_id": "pulse", "time_s": 0.02, "end_time_s": 0.03,
             "target": {"instance_path": "Main", "owner": "17", "definition": "master:const", "parameter": "Value"},
             "before_value": 0, "value": 1, "after_value": 0, "units": "1"}
    return source, master, event


def _plan(tmp_path, events=None):
    source, master, event = _inputs(tmp_path)
    plan = _module().plan_embedded_control(source, events or [event], master_path=master,
        time_step_s=1e-5, output_step_s=1e-5, duration_s=0.05, max_timing_error_s=2e-5)
    return source, master, plan


def test_embedded_contract_is_hashed_before_exclusive_copy_and_read_back(tmp_path):
    source, master, plan = _plan(tmp_path)
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


@pytest.mark.parametrize("override", [
    {"time_s": -1}, {"time_s": float("nan")}, {"end_time_s": 0.01},
    {"end_time_s": float("inf")}, {"value": float("nan")},
])
def test_invalid_contract_never_modifies_source(tmp_path, override):
    source, master, event = _inputs(tmp_path)
    before = source.read_bytes()
    with pytest.raises(BackendError):
        _module().plan_embedded_control(source, [{**event, **override}], master_path=master,
            time_step_s=1e-5, output_step_s=1e-5, duration_s=0.05, max_timing_error_s=2e-5)
    assert source.read_bytes() == before


def test_conflicts_rejected_but_non_overlapping_same_target_allowed(tmp_path):
    source, master, event = _inputs(tmp_path)
    options = dict(master_path=master, time_step_s=1e-5, output_step_s=1e-5,
                   duration_s=0.05, max_timing_error_s=2e-5)
    other = {**event, "event_id": "second", "time_s": 0.025, "end_time_s": 0.04}
    with pytest.raises(BackendError):
        _module().plan_embedded_control(source, [event, other], **options)
    other["time_s"] = 0.035
    plan = _module().plan_embedded_control(source, [other, event], **options)
    assert [item["event_id"] for item in plan["events"]] == ["pulse", "second"]


@pytest.mark.parametrize("drift", ["source", "schedule", "selector"])
def test_drift_invalidates_plan_before_destination_creation(tmp_path, drift):
    source, master, plan = _plan(tmp_path)
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
    source.write_text(PROJECT.replace('</schematic>', PROJECT.split('<schematic>')[1].split('</schematic>')[0] + '</schematic>'))
    with pytest.raises(BackendError):
        _module().plan_embedded_control(source, [event], master_path=master,
            time_step_s=1e-5, output_step_s=1e-5, duration_s=0.05, max_timing_error_s=2e-5)


def test_saved_readback_detects_script_and_output_binding_drift(tmp_path):
    source, master, plan = _plan(tmp_path)
    destination = tmp_path / "derived.pscx"
    _module().materialize_embedded_control(plan, destination)
    root = ET.parse(destination)
    root.find(".//segment").text = "      $OUT = 0.0"
    root.write(destination)
    with pytest.raises(BackendError):
        _module().verify_embedded_control(plan, destination)
