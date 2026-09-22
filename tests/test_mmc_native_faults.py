from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.hvdc.builders.mmc.native_faults import FAULT_NAME, append_native_fault_protocol, evaluate_native_fault_trace
from pscad_mcp.hvdc.builders.mmc.native_bundle import materialize_native_avm_fixture
from tests.test_mmc_native_dq import _run_native_equations
from tests.test_mmc_native_bundle import constants_evidence, installed_sources  # noqa: F401
from tests.test_mmc_native_dynamic_checks import evidence  # noqa: F401


def test_native_fault_uses_observed_power_start_and_emtdc_time(tmp_path):
    root = ET.Element("project")
    ET.SubElement(root, "definitions")
    append_native_fault_protocol(root)
    definition = root.find(f"./definitions/Definition[@name='{FAULT_NAME}']")
    rows = _run_native_equations(tmp_path, FAULT_NAME, definition=definition, declarations="",
        initialize="PAR_Fault_Delay_s = 0.3\nPAR_Fault_Duration_s = 0.05\nSIG_POWER_START = 0.2",
        loop="SIG_POWER_READY = 0.0\nif (TIME >= 0.2) SIG_POWER_READY = 1.0\nif (TIME >= 0.6) SIG_POWER_START = 0.6",
        observations="if (sample == 2000 .or. sample == 9999 .or. sample == 10000 .or. sample == 10999 .or. sample == 11000 .or. sample == 18000) print *, SIG_ACTIVE, SIG_OPEN, SIG_START, SIG_END",
        steps=18000)
    assert rows[0] == [0.0, 1.0, -1.0, -1.0]
    assert [row[0] for row in rows[1:]] == [0.0, 1.0, 1.0, 0.0, 0.0]
    for row in rows[1:]:
        assert row[2:] == pytest.approx([0.5, 0.55])


@pytest.mark.parametrize("kind,branches", [
    ("ac_three_phase", ("A", "B", "C")), ("ac_single_line_ground", ("A",)),
    ("dc_pole_to_pole", ("DC",)), ("dc_pole_to_ground", ("DC",)),
])
def test_fault_fixture_contains_controlled_electrical_shunts(constants_evidence, installed_sources, tmp_path, kind, branches):
    donor, master = installed_sources
    report = materialize_native_avm_fixture(tmp_path / "fault-model", constants_evidence=constants_evidence,
        source_project=donor, master_path=master, control_kind="dq_current", fault_kind=kind,
        reversal_time_s=1.0, simulation_duration_s=7.4)
    root = ET.parse(report["project_path"])
    main = root.find("./definitions/Definition[@name='Main']/schematic")
    shunts = [c for c in main.findall("User") if c.get("name", "").startswith("fault_branch_") and c.get("defn") == "master:breaker1"]
    assert len(shunts) == len(branches)
    for name in branches:
        assert report["channels"]["FAULT_I_" + name] == "kA"
    assert report["parameters"]["fault_kind"] == kind
    assert all(c.find("./paramlist/param[@name='NAME']").get("value") == "FAULT_OPEN" for c in shunts)


def test_trip_without_postfault_control_recovery_cannot_pass(evidence):
    trace, parameters, _ = evidence
    parameters["fault_kind"] = "dc_pole_to_pole"
    parameters["output_step_s"] = 0.001
    time = trace["time"]
    trace["FAULT_START"] = [2.1] * len(time)
    trace["FAULT_END"] = [2.15] * len(time)
    trace["FAULT_ACTIVE"] = [float(2.1 <= t < 2.15) for t in time]
    trace["FAULT_I_DC"] = [0.2 if 2.1 <= t < 2.15 else 0.0 for t in time]
    trace["P_CABLE_VDC"] = [0.02 if 2.1 <= t < 2.15 else 640.0 for t in time]
    trace["PROTECTION_TRIP"] = [float(t >= 2.101) for t in time]
    trace["PROTECTION_TIME"] = [2.101 if t >= 2.101 else -1.0 for t in time]
    trace["PROTECTION_CODE"] = [1.0 if t >= 2.101 else 0.0 for t in time]
    for s in ("P", "V"):
        for n, value in (("ARM_PEAK", 0.6), ("DC_PEAK", 1.6), ("CAP_MIN", 320.0), ("CAP_MAX", 320.0)):
            trace[f"FAULT_{s}_{n}"] = [value] * len(time)
        trace[s + "_P"] = trace["P_P"][:]
        trace[s + "_P_REFERENCE"] = trace["P_P_REFERENCE"][:]
        trace[s + "_BLOCK"] = [float(t >= 2.101) for t in time]
        for domain, branches in (("AC", "ABC"), ("DC", ("POS", "NEG"))):
            for branch in branches:
                trace[f"{s}_{domain}_{branch}_CONTACT_STATE"] = [2.0 if t >= 2.102 else 0.0 for t in time]
                trace[f"{s}_{domain}_{branch}_MOV_ENERGY"] = [10.0 if t >= 2.102 else 0.0 for t in time]
    result = evaluate_native_fault_trace(trace, parameters)
    assert result["checks"]["protection_trips_after_fault"]
    assert result["checks"]["both_stations_block"]
    assert result["status"] == "FAIL"
    assert "P:control_recovery" in result["failed_checks"]
    assert result["model_accepted"] is False and result["intrinsic_dc_fault_blocking"] is False
