"""Native cable assembly topology, provenance, and DC-loop physical contracts."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.hvdc.builders.mmc import cable_constants
from tests.test_mmc_cable_constants import _fake_native_run


def _module():
    return importlib.import_module("pscad_mcp.hvdc.builders.mmc.cable_companion")


def _parameters(element):
    return {item.get("name"): item.get("value") for item in element.findall("./paramlist/param")}


@pytest.fixture(scope="module")
def installed_sources():
    master = Path(r"C:\Program Files (x86)\PSCAD46\master.pslx")
    project = Path(r"C:\Users\Public\Documents\PSCAD\4.6\Examples\hvdc_vsc\VSCTrans.pscx")
    if not master.is_file() or not project.is_file():
        pytest.skip("Installed native cable source metadata is required; no license or vendor process is used")
    return project, master


@pytest.fixture
def constants_receipt(installed_sources, tmp_path, monkeypatch):
    project, master = installed_sources
    executable = tmp_path / "native-bin" / "tline.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"test executable")
    monkeypatch.setattr(cable_constants.subprocess, "run", _fake_native_run)
    artifact = cable_constants.generate_public_cable_constants(
        project, tmp_path / "constants", master_path=master, executable=executable,
        lengths_km=(100.0,), reference_frequency_hz=50.0,
    )[0]
    return Path(artifact.evidence_path)


@pytest.fixture
def assembly(constants_receipt, installed_sources, tmp_path):
    project, master = installed_sources
    receipt = _module().materialize_cable_assembly(
        tmp_path / "assembly", constants_evidence=constants_receipt,
        source_project=project, master_path=master,
    )
    return receipt, ET.parse(receipt["project_path"]).getroot()


def test_assembly_has_four_separate_native_terminals_and_one_coupled_line(assembly):
    receipt, root = assembly
    definitions = {item.get("name"): item for item in root.findall("./definitions/Definition")}
    assert set(definitions) == {"Station", "Main", "Cable2", "MMCCableLink"}
    assert root.get("Target") == "EMTDC"
    ports = definitions["MMCCableLink"].findall("./svg/port")
    assert {port.get("name") for port in ports} == {"SEND_POS", "SEND_NEG", "RECV_POS", "RECV_NEG"}
    assert all(port.get("model") == "Natural" and port.get("dim") == "1" for port in ports)
    assert len(root.findall(".//Wire[@classid='Cable']")) == 1
    assert len(root.findall(".//User[@defn='master:cable_interface']")) == 2
    assert root.findall(".//script") == []
    assert receipt["licensed_acceptance"] == "NOT_RUN"
    assert receipt["topology"]["terminals_separate"] is True
    assert set(receipt["terminals"]) == {port.get("name") for port in ports}


def test_interfaces_preserve_phase_order_and_explicit_end_selection(assembly):
    receipt, root = assembly
    interfaces = root.findall(".//User[@defn='master:cable_interface']")
    values = [_parameters(interface) for interface in interfaces]
    assert {value["send_recv"] for value in values} == {"1", "2"}
    for value in values:
        assert value["Name"] == receipt["cable_name"]
        assert value["NCAB"] == "2"
        assert value["C1T"] == value["C2T"] == "1"
        assert value["dim_s"] == value["dim_r"] == "0"
    mapping = receipt["topology"]["port_bindings"]
    assert mapping == {
        "SEND_POS": {"end": "sending", "native_port": "C1"},
        "SEND_NEG": {"end": "sending", "native_port": "C2"},
        "RECV_POS": {"end": "receiving", "native_port": "C1"},
        "RECV_NEG": {"end": "receiving", "native_port": "C2"},
    }


def test_geometry_audit_ignores_definition_date_but_rejects_geometry_changes(assembly):
    receipt, root = assembly
    geometry = root.find("./definitions/Definition[@name='Cable2']")
    geometry.set("date", "1789188040")
    ET.ElementTree(root).write(receipt["project_path"], encoding="utf-8")
    assert _module().audit_cable_assembly(receipt["project_path"], receipt)["terminals_separate"]
    parameter = geometry.find(".//param")
    parameter.set("value", "changed")
    ET.ElementTree(root).write(receipt["project_path"], encoding="utf-8")
    with pytest.raises(ValueError, match="geometry"):
        _module().audit_cable_assembly(receipt["project_path"], receipt)


def test_materialization_binds_exact_local_constants_and_keeps_source_receipts(assembly, constants_receipt, installed_sources):
    receipt, root = assembly
    native = json.loads(constants_receipt.read_text(encoding="utf-8"))
    source_project, master = installed_sources
    configuration = root.find(".//Wire[@classid='Cable']/User")
    values = _parameters(configuration)
    assert float(values["Length"].split()[0]) == native["length_km"]
    assert values["Dim"] == "2"
    assert values["const_path"] == receipt["constants_path"]
    assert Path(values["const_path"]).suffix == ".clo"
    assert hashlib.sha256(Path(values["const_path"]).read_bytes()).hexdigest() == native["constants_sha256"]
    assert receipt["source_hashes_before"] == receipt["source_hashes_after"]
    assert receipt["source_hashes_before"][str(source_project)] == hashlib.sha256(source_project.read_bytes()).hexdigest()
    assert receipt["source_hashes_before"][str(master)] == hashlib.sha256(master.read_bytes()).hexdigest()
    assert receipt["constants_receipt_sha256"] == hashlib.sha256(constants_receipt.read_bytes()).hexdigest()
    assert not root.findall(".//User[@defn='master:dc_cable']")
    assert not root.findall(".//User[@defn='master:resistor']")
    hierarchy = root.find("./hierarchy/call/call")
    assert {item.get("name").rsplit(":", 1)[-1] for item in hierarchy} == {"Cable2", "MMCCableLink"}


@pytest.mark.parametrize("mutation", ["bypass", "swapped_poles", "extra_component"])
def test_saved_topology_audit_rejects_bypass_or_changed_terminal_semantics(assembly, mutation):
    receipt, root = assembly
    module = root.find("./definitions/Definition[@name='MMCCableLink']")
    if mutation == "bypass":
        wire = ET.SubElement(module.find("schematic"), "Wire", {
            "classid": "WireOrthogonal", "id": "1999999999", "x": "198", "y": "216",
        })
        ET.SubElement(wire, "vertex", {"x": "0", "y": "0"})
        ET.SubElement(wire, "vertex", {"x": "360", "y": "0"})
    elif mutation == "swapped_poles":
        nodes = module.findall("./schematic/User[@defn='master:xnode']/paramlist/param[@name='Name']")
        nodes[0].set("value", "SEND_NEG")
        nodes[1].set("value", "SEND_POS")
    else:
        ET.SubElement(module.find("schematic"), "User", {"id": "1999999998", "defn": "master:resistor"})
    ET.ElementTree(root).write(receipt["project_path"], encoding="utf-8")
    with pytest.raises(ValueError):
        _module().audit_cable_assembly(receipt["project_path"], receipt)


@pytest.mark.parametrize("mutation", ["constants", "receipt_length", "receipt_metrics"])
def test_materializer_rejects_changed_constants_or_unverified_receipts(constants_receipt, installed_sources, tmp_path, mutation):
    project, master = installed_sources
    receipt = json.loads(constants_receipt.read_text(encoding="utf-8"))
    if mutation == "constants":
        Path(receipt["constants_path"]).write_text("Fre-Phase 2 0 1 1 /\n", encoding="ascii")
    elif mutation == "receipt_length":
        receipt["length_km"] = 300.0
        constants_receipt.write_text(json.dumps(receipt), encoding="utf-8")
    else:
        receipt["fit_record"]["max_residue_pole_ratio"] = 0.0
        constants_receipt.write_text(json.dumps(receipt), encoding="utf-8")
    destination = tmp_path / "invalid"
    with pytest.raises(ValueError):
        _module().materialize_cable_assembly(
            destination, constants_evidence=constants_receipt,
            source_project=project, master_path=master,
        )
    assert not destination.exists()


def test_dc_fixture_has_one_ground_and_a_load_returning_through_negative_conductor(constants_receipt, installed_sources, tmp_path):
    project, master = installed_sources
    receipt = _module().materialize_cable_loop_fixture(
        tmp_path / "fixture", constants_evidence=constants_receipt,
        source_project=project, master_path=master,
    )
    root = ET.parse(receipt["project_path"]).getroot()
    main = root.find("./definitions/Definition[@name='Main']")
    assert len(main.findall("./schematic/User[@defn='master:ground']")) == 1
    assert len(main.findall("./schematic/User[@defn='master:source_1']")) == 1
    assert len(main.findall("./schematic/User[@defn='master:resistor']")) == 1
    assert len(main.findall("./schematic/User[@defn='master:pgb']")) == 4
    nets = receipt["electrical_nets"]["Main"]
    assert "sending_current:N2" in nets["SEND_POS"]
    assert "test_ground:A" in nets["GND"]
    assert "cable_link:SEND_NEG" in nets["GND"]
    assert "load:A" in nets["RECV_POS"]
    assert "receiving_current:N2" in nets["RECV_NEG"]
    assert "load:B" in nets["LOAD_RETURN"]
    assert receipt["channels"] == {"I_SEND": "kA", "I_RETURN": "kA", "V_SEND": "kV", "V_RECV": "kV"}
    expected = 10.0 / (100.0 + receipt["loop_dc_resistance_ohm"])
    assert receipt["physical_reference"]["dc_current_ka"] == pytest.approx(expected)
    assert receipt["topology"]["terminals_separate"] is True


def test_analyzer_accepts_a_complete_passive_dc_loop_and_rejects_a_short_cable():
    module = _module()
    reference = {
        "source_voltage_kv": 10.0, "load_resistance_ohm": 100.0,
        "loop_dc_resistance_ohm": 16.5982595976,
        "duration_s": 5.0, "output_step_s": 0.01, "steady_window_s": [4.0, 5.0],
    }
    current = 10.0 / (100.0 + reference["loop_dc_resistance_ohm"])
    trace = {"time": [index * 0.01 for index in range(501)],
             "I_SEND": [current] * 501, "I_RETURN": [current] * 501,
             "V_SEND": [10.0] * 501, "V_RECV": [100.0 * current] * 501}
    assert module.analyze_cable_loop(trace, reference)["status"] == "PASS"
    short = {**trace, "I_SEND": [0.1] * 501, "I_RETURN": [0.1] * 501, "V_RECV": [10.0] * 501}
    failed = module.analyze_cable_loop(short, reference)
    assert failed["status"] == "FAIL"
    assert "dc_current" in failed["failed_checks"]


@pytest.mark.parametrize("mutation", ["missing", "nonfinite", "time", "return"])
def test_analyzer_rejects_incomplete_or_nonphysical_trace(mutation):
    module = _module()
    reference = {"source_voltage_kv": 10.0, "load_resistance_ohm": 100.0,
                 "loop_dc_resistance_ohm": 10.0, "duration_s": 5.0,
                 "output_step_s": 0.01, "steady_window_s": [4.0, 5.0]}
    current = 10.0 / 110.0
    trace = {"time": [index * 0.01 for index in range(501)],
             "I_SEND": [current] * 501, "I_RETURN": [current] * 501,
             "V_SEND": [10.0] * 501, "V_RECV": [100.0 * current] * 501}
    if mutation == "missing":
        del trace["V_RECV"]
    elif mutation == "nonfinite":
        trace["I_SEND"][450] = math.nan
    elif mutation == "time":
        trace["time"][-1] = 4.8
    else:
        trace["I_RETURN"] = [-current] * 501
    assert module.analyze_cable_loop(trace, reference)["status"] == "FAIL"
