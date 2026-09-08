"""Synthetic identity fixtures, not licensed electrical acceptance evidence."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc import fault_channels
from pscad_mcp.hvdc.builders.mmc.template_native import (
    evaluate_template_native_dc_fault,
)


def fault_fixture() -> tuple[dict, dict, dict]:
    times = [round(index * 0.005, 8) for index in range(201)]
    active = [int(0.4 <= value < 0.6) for value in times]
    channels = []
    contracts = []
    roles = {
        "fault_active": ("1", active, {"inactive": 0, "active": 1}),
        "v_inserted": ("kV", [-8.0 if value else 320.0 for value in active], None),
        "blocking_state": ("1", active, {"inactive": 0, "active": 1}),
        "i_dc_fault": ("kA", [2.0 if value else 0.0 for value in active], None),
        "v_dc": ("kV", [30.0 if value else 640.0 for value in active], None),
        "i_arm": ("kA", [0.1 if value else 1.0 for value in active], None),
        "v_cap": ("kV", [640.0 for _ in active], None),
        "recovery_enable": ("1", [1 - value for value in active], {"inactive": 0, "active": 1}),
        "p_active": ("MW", [0.0 if value else 900.0 for value in active], None),
    }
    for index, (role, (units, values, polarity)) in enumerate(roles.items(), 1):
        selector = {"description": role, "group": "MMC_FAULT", "owner_id": str(index), "instance_path": "Main[1]/T1[2]"}
        contract = {
            "role": role, "channel_id": role, "model_scope": "T1/A/upper",
            "instance_path": selector["instance_path"], "owner_id": str(index),
            "definition": "master:pgb", "signal_source": {"kind": "physical_measurement", "owner_id": f"source-{index}"},
            "selector": selector, "units": units, "dimension": 1, "polarity": polarity,
            "nominal": 900.0 if role == "p_active" else 640.0 if role in ("v_dc", "v_cap") else None,
        }
        contracts.append(contract)
        channels.append({
            **selector, "units": units, "dimension": 1, "domain": times[:], "values": values,
            "output_part": "synthetic_01.out", "metadata_file": "synthetic.inf",
            "hash": "a" * 64, "metadata_sha256": "b" * 64,
        })
    checks = {
        "schema_version": 1, "time_basis": "EMTDC", "time_units": "s", "output_step_s": 0.005,
        "frequency_hz": 60.0, "arm_rms_stability_relative_tolerance": 0.05,
        "nominal_target_relative_tolerance": 0.05,
        "arm_peak_limit_ka": 3.0,
        "maximum_power_loss_fraction": 0.1,
        "max_timing_error_s": 0.011, "fault_window_s": [0.4, 0.6],
        "prefault_window_s": [0.1, 0.3], "recovery_window_s": [0.8, 1.0],
        "negative_voltage_max_kv": -1.0, "fault_current_limit_ka": 20.0,
        "voltage_recovery_relative_tolerance": 0.05, "power_recovery_relative_tolerance": 0.05,
        "arm_rms_recovery_relative_tolerance": 0.1, "capacitor_recovery_relative_tolerance": 0.05,
        "steady_relative_rms_tolerance": 0.05, "minimum_operating_fraction": 0.9,
        "arm_rms_floor_ka": 0.05,
    }
    return {"channels": channels, "evidence_kind": "synthetic"}, {"schema_version": 1, "channels": contracts}, checks


def evaluate(samples, contract, checks):
    return evaluate_template_native_dc_fault(samples, channel_contract=contract, checks_contract=checks, fault_current_limit_ka=20.0)


def test_complete_traceable_fault_fixture():
    samples, contract, checks = fault_fixture()
    report = evaluate(samples, contract, checks)
    assert report["verdict"] == "PASS"
    assert report["checks"]["recovered"] is True
    assert report["check_results"]
    assert all({"expected", "observed", "window", "source", "status"} <= item.keys() for item in report["check_results"])


def test_production_fault_contract_preserves_physical_limits_and_isolated_windows():
    checks = fault_channels.default_fault_checks()
    assert checks["fault_current_limit_ka"] == 20.0
    assert checks["arm_peak_limit_ka"] == 3.0
    assert checks["fault_window_s"] == [2.5, 2.7]
    assert checks["recovery_window_s"] == [4.6, 5.0]
    checks["fault_window_s"][0] = 99
    assert fault_channels.default_fault_checks()["fault_window_s"] == [2.5, 2.7]


@pytest.mark.parametrize("injection", ["band", "window", "limit"])
def test_observations_cannot_authorize_their_own_acceptance_contract(injection):
    samples, contract, checks = fault_fixture()
    if injection == "band":
        checks["nominal_target_relative_tolerance"] = 0.2
        channel = next(item for item in samples["channels"] if item["description"] == "v_dc")
        channel["values"] = [600.0 if value == 640.0 else value for value in channel["values"]]
    elif injection == "window":
        checks["prefault_window_s"] = [0.0, 0.2]
    else:
        checks["fault_current_limit_ka"] = 200.0
    samples["channel_contract"] = contract
    samples["checks_contract"] = checks
    report = evaluate_template_native_dc_fault(samples, fault_current_limit_ka=checks["fault_current_limit_ka"])
    assert report["verdict"] == "INCOMPLETE_ANALYSIS"
    assert "channel_contract_missing" in report["invalid_evidence"]
    report = evaluate_template_native_dc_fault(samples, channel_contract=contract, fault_current_limit_ka=checks["fault_current_limit_ka"])
    assert report["verdict"] == "INCOMPLETE_ANALYSIS"
    assert "checks_contract_missing" in report["invalid_evidence"]


def test_a_high_activity_duplicate_cannot_override_the_bound_station():
    samples, contract, checks = fault_fixture()
    other = copy.deepcopy(samples["channels"][0])
    other["instance_path"] = "Main[1]/T2[3]"
    other["values"] = [9.0 for _ in other["values"]]
    samples["channels"].insert(0, other)
    assert evaluate(samples, contract, checks)["verdict"] == "PASS"
    samples["channels"].append(copy.deepcopy(samples["channels"][1]))
    assert evaluate(samples, contract, checks)["verdict"] == "INCOMPLETE_ANALYSIS"


@pytest.mark.parametrize("role", ["v_inserted", "v_dc", "i_arm", "v_cap", "recovery_enable", "p_active"])
def test_missing_physical_role_is_incomplete(role):
    samples, contract, checks = fault_fixture()
    samples["channels"] = [item for item in samples["channels"] if item["description"] != role]
    report = evaluate(samples, contract, checks)
    assert report["verdict"] == "INCOMPLETE_ANALYSIS"
    assert role in report["missing_channels"]


def test_low_active_blocking_is_explicit_and_unknown_polarity_rejected():
    samples, contract, checks = fault_fixture()
    channel = next(item for item in samples["channels"] if item["description"] == "blocking_state")
    channel["values"] = [1 - value for value in channel["values"]]
    binding = next(item for item in contract["channels"] if item["role"] == "blocking_state")
    binding["polarity"] = {"inactive": 1, "active": 0}
    assert evaluate(samples, contract, checks)["verdict"] == "PASS"
    binding["polarity"] = None
    assert evaluate(samples, contract, checks)["verdict"] == "INCOMPLETE_ANALYSIS"


def test_amperes_are_converted_explicitly():
    samples, contract, checks = fault_fixture()
    channel = next(item for item in samples["channels"] if item["description"] == "i_dc_fault")
    channel["units"] = "A"
    channel["values"] = [1000 * value for value in channel["values"]]
    report = evaluate(samples, contract, checks)
    assert report["verdict"] == "PASS"
    assert report["evidence"]["fault_current_peak_ka"] == 2.0
    assert report["evidence"]["unit_conversions"]
    channel["units"] = "unknown"
    assert evaluate(samples, contract, checks)["verdict"] == "INCOMPLETE_ANALYSIS"


@pytest.mark.parametrize("defect", ["nan", "reverse", "duplicate", "alignment", "missing_recovery"])
def test_invalid_or_incomplete_time_domain_rejected(defect):
    samples, contract, checks = fault_fixture()
    channel = samples["channels"][-1]
    if defect == "nan":
        channel["values"][5] = float("nan")
    elif defect == "reverse":
        channel["domain"][6] = 0.01
    elif defect == "duplicate":
        channel["domain"][6] = channel["domain"][5]
    elif defect == "alignment":
        channel["domain"] = [value + 0.001 for value in channel["domain"]]
    else:
        for channel in samples["channels"]:
            channel["domain"] = channel["domain"][:70]
            channel["values"] = channel["values"][:70]
    assert evaluate(samples, contract, checks)["verdict"] == "INCOMPLETE_ANALYSIS"


def test_negative_voltage_outside_fault_cannot_pass():
    samples, contract, checks = fault_fixture()
    channel = samples["channels"][1]
    channel["values"] = [-8.0 if time < 0.3 else 2.0 for time in channel["domain"]]
    report = evaluate(samples, contract, checks)
    assert report["verdict"] == "FAIL"
    assert report["checks"]["negative_voltage_inserted"] is False


@pytest.mark.parametrize("role", ["v_dc", "p_active", "i_arm"])
def test_unblocking_without_electrical_recovery_fails(role):
    samples, contract, checks = fault_fixture()
    channel = next(item for item in samples["channels"] if item["description"] == role)
    channel["values"] = [value if time < 0.6 else 0 for time, value in zip(channel["domain"], channel["values"])]
    report = evaluate(samples, contract, checks)
    assert report["verdict"] == "FAIL"
    assert report["checks"]["recovered"] is False


def test_zero_operating_point_cannot_be_its_own_recovery_reference():
    samples, contract, checks = fault_fixture()
    for channel in samples["channels"]:
        if channel["description"] in ("v_dc", "p_active", "i_arm"):
            channel["values"] = [0.0 for _ in channel["values"]]
    assert evaluate(samples, contract, checks)["verdict"] == "FAIL"


def output_fixture(tmp_path):
    base = tmp_path / "case"
    base.with_suffix(".inf").write_text('PGB(1) Output Desc="fault_active" Group="MMC_FAULT" Max=1 Min=0 Units="1"\n', encoding="ascii")
    part = base.with_name("case_01.out")
    part.write_text("0.0 0.0\n0.1 1.0\n", encoding="ascii")
    return part


@pytest.mark.parametrize("drift", ["metadata", "added_part", "removed_part", "stale"])
def test_complete_dataset_identity_rejects_drift(tmp_path, drift):
    part = output_fixture(tmp_path)
    manifest = fault_channels.snapshot_output_dataset(part)
    if drift == "metadata":
        part.with_name("case.inf").write_text("changed", encoding="ascii")
    elif drift == "added_part":
        part.with_name("case_02.out").write_text("0 0\n", encoding="ascii")
    elif drift == "removed_part":
        part.unlink()
    else:
        manifest["started_after"] = part.stat().st_mtime + 10
    with pytest.raises(BackendError) as error:
        fault_channels.verify_output_dataset(manifest)
    assert error.value.code == "MMC_OUTPUT_IDENTITY_CHANGED"


def test_runtime_source_hash_is_checked_before_materialization(tmp_path):
    source = tmp_path / "source.pscx"
    source.write_text("<project/>", encoding="ascii")
    with pytest.raises(BackendError) as error:
        fault_channels.instrument_fault_channels(source, tmp_path / "derived.pscx", library=source, master=source, expected_source_hashes={"project": "0" * 64})
    assert error.value.code == "MMC_TEMPLATE_SOURCE_CHANGED"


@pytest.fixture
def installed_sources():
    from pscad_mcp.hvdc.builders.mmc.template_audit import (
        discover_official_mmc_template,
    )
    master = Path("C:/Program Files (x86)/PSCAD46/master.pslx")
    if not master.is_file():
        pytest.skip("Installed master metadata is unavailable")
    try:
        project, library = discover_official_mmc_template()
    except BackendError:
        pytest.skip("Installed official MMC metadata is unavailable")
    return project, library, master


def test_installed_instrumentation_is_derived_unique_and_readable(tmp_path, installed_sources):
    project, library, master = installed_sources
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in installed_sources}
    derived = tmp_path / "observed.pscx"
    contract = fault_channels.instrument_fault_channels(project, derived, library=library, master=master)
    assert before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in installed_sources}
    assert {item["role"] for item in contract["channels"]} == set(fault_channels.REQUIRED_ROLES)
    inserted = [item for item in contract["channels"] if item["role"] == "v_inserted"]
    assert len(inserted) == 12
    assert len({item["instance_path"] + "/" + item["owner_id"] for item in inserted}) == 12
    assert len({item["selector"]["description"] for item in contract["channels"]}) == len(contract["channels"])
    assert all(item["selector"]["port"] == "Signl" for item in contract["channels"])
    assert all(item["sample_count"] is None and item["output_part"] is None for item in contract["channels"])
    assert fault_channels.verify_fault_instrumentation(derived, contract)["matched"] is True


def test_cell_voltage_extrema_keep_single_submodule_units(tmp_path, installed_sources):
    project, library, master = installed_sources
    contract = fault_channels.instrument_fault_channels(project, tmp_path / "observed.pscx", library=library, master=master)
    minimum = [item for item in contract["diagnostic_channels"] if item["role"] == "v_cap_minimum"]
    maximum = [item for item in contract["diagnostic_channels"] if item["role"] == "v_cap_maximum"]
    assert len(minimum) == len(maximum) == 12
    assert all(item["units"] == "kV" and item["dimension"] == 1 for item in minimum + maximum)
    assert all(item["signal_source"]["quantity"] == "single_submodule_voltage_extremum" for item in minimum + maximum)


def test_capacitor_energy_and_aggregate_source_keep_actual_cell_outputs(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET
    project, library, master = installed_sources
    derived = tmp_path / "observed.pscx"
    contract = fault_channels.instrument_fault_channels(project, derived, library=library, master=master)
    energy = [item for item in contract["diagnostic_channels"] if item["role"] == "arm_capacitor_energy"]
    equivalent = [item for item in contract["diagnostic_channels"] if item["role"] == "cell_equivalent_source_voltage"]
    assert len(energy) == len(equivalent) == 12
    assert all(item["units"] == "MJ" and item["signal_source"]["expression"] == "0.5*C_uF*1e-6*SUM(Vc_kV**2)" for item in energy)
    assert all(item["units"] == "kV" and item["signal_source"]["expression"] == "FULLCELL1_EXE RVD1_5" for item in equivalent)
    definition = next(item for item in ET.parse(derived).findall("./definitions/Definition") if item.get("name") == "MmcObservedFullCell")
    assert "0.5e-6*$C*SUM($Vc**2)" in next(item.text for item in definition.findall("./script/segment") if item.get("name") == "Dsout")


def test_sorter_diagnostics_observe_same_step_permutation_and_input(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET
    project, library, master = installed_sources
    derived = tmp_path / "observed.pscx"
    contract = fault_channels.instrument_fault_channels(project, derived, library=library, master=master)
    for role in ("sort_index_invalid", "sort_index_inversions", "sort_requested_count", "sort_enable", "sort_prefix_gap", "sort_suffix_gap", "sort_boundary_applicable", "capacitor_charge_power", "capacitor_current_sum"):
        bindings = [item for item in contract["diagnostic_channels"] if item["role"] == role]
        assert len(bindings) == 12
    tree = ET.parse(derived)
    sorter = next(item for item in tree.findall("./definitions/Definition") if item.get("name") == "MmcObservedSorter")
    script = next(item.text for item in sorter.findall("./script/segment") if item.get("name") == "Fortran")
    assert script.index("CALL E_SORTER") < script.index("MFEINV")
    assert "$IN($OUT" in script
    assert "MmcObservedSorter" in contract["readback_scripts"]
    calls = [item for definition in tree.findall("./definitions/Definition") if definition.get("name", "").startswith("MFE_Pole_") for item in definition.findall("./schematic/User") if item.get("defn", "").endswith(":MmcObservedSorter")]
    assert len(calls) == 12


def test_voltage_base_diagnostics_bind_physical_and_preclamp_nodes(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET
    project, library, master = installed_sources
    derived = tmp_path / "observed.pscx"
    contract = fault_channels.instrument_fault_channels(project, derived, library=library, master=master)
    diagnostics = contract["diagnostic_channels"]
    for role, count, units in (("v_dc_converter", 2, "kV"), ("controller_ac_magnitude_kv", 2, "kV"), ("controller_ac_magnitude_preclamp", 2, "pu"), ("phase_ac_reference", 6, "pu"), ("arm_deblocking_ramp", 6, "pu")):
        bindings = [item for item in diagnostics if item["role"] == role]
        assert len(bindings) == count
        assert all(item["units"] == units for item in bindings)
    ac = next(item for item in diagnostics if item["role"] == "controller_ac_magnitude_kv")
    assert ac["signal_source"]["owner_id"] == "736319288"
    assert ac["signal_source"]["quantity"] == "phase_voltage_command_magnitude_before_dc_normalization"
    tree = ET.parse(derived)
    definition = next(item for item in tree.findall("./definitions/Definition") if item.get("name") == ac["definition_name"])
    node = next(item for item in definition.findall("./schematic/User") if any(param.get("name") == "Name" and param.get("value") == "MmcAcMagnitudeKv" for param in item.findall("./paramlist/param")) and item.get("x") == "3204")
    assert node.get("y") == "2034"
    node.set("y", "2052")
    tree.write(derived, encoding="utf-8")
    with pytest.raises(BackendError):
        fault_channels.verify_fault_instrumentation(derived, contract)


def test_audit_preserves_reachable_roles_after_instrumentation(tmp_path, installed_sources):
    from pscad_mcp.hvdc.builders.mmc.template_audit import audit_mmc_template
    project, library, master = installed_sources
    derived = tmp_path / "observed.pscx"
    fault_channels.instrument_fault_channels(project, derived, library=library, master=master)
    report = audit_mmc_template(derived, library)
    assert report["compatible"] is True
    assert report["submodule_topology"]["full_cell_instances"] == 12
    stations = [item for item in report["role_bindings"] if item["role"] in ("station_p", "station_vdc")]
    assert len(stations) == 2
    assert all(item["definition"].rsplit(":", 1)[-1] in ("MFE_VSC_T1", "MFE_VSC_T2") for item in stations)
    assert all("Main[" in item["instance_path"] for item in stations)


def test_terminal_two_charging_delay_uses_its_own_setting(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET

    from pscad_mcp.hvdc.builders.mmc.template_audit import _parameters
    project, _, _ = installed_sources
    original_hash = hashlib.sha256(project.read_bytes()).hexdigest()
    derived = tmp_path / "charging.pscx"
    result = fault_channels.materialize_terminal_two_charging(project, derived)
    root = ET.parse(derived)
    owners = {item.get("id"): item for item in root.findall("./definitions/Definition[@name='Main']/schematic/User")}
    assert dict(_parameters(owners["606940312"]))["T"] == "Tcharging2"
    assert dict(_parameters(owners["584272924"]))["T"] == "Tcharging1"
    assert result["owner"] == "606940312"
    assert result["source_sha256"] == hashlib.sha256(project.read_bytes()).hexdigest() == original_hash
    before = ET.parse(project)
    target = next(item for item in before.findall("./definitions/Definition[@name='Main']/schematic/User") if item.get("id") == "606940312")
    next(item for item in target.findall("./paramlist/param") if item.get("name") == "T").set("value", "Tcharging2")
    assert ET.tostring(before.getroot()) == ET.tostring(root.getroot())


def test_readback_detects_changed_source_parameter(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET
    project, library, master = installed_sources
    derived = tmp_path / "observed.pscx"
    contract = fault_channels.instrument_fault_channels(project, derived, library=library, master=master)
    root = ET.parse(derived)
    next(item for item in root.iter("param") if item.get("name") == "MmcInserted").set("value", "UnrelatedVoltage")
    root.write(derived, encoding="utf-8")
    with pytest.raises(BackendError) as error:
        fault_channels.verify_fault_instrumentation(derived, contract)
    assert error.value.code == "MMC_POSTCONDITION_FAILED"


def test_conditional_partial_blocking_source_is_rejected(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET
    project, library, master = installed_sources
    root = ET.parse(project)
    for param in root.iter("param"):
        if param.get("name") == "DTBP":
            param.set("value", "1")
    altered = tmp_path / "partial.pscx"
    root.write(altered, encoding="utf-8")
    with pytest.raises(BackendError) as error:
        fault_channels.instrument_fault_channels(altered, tmp_path / "observed.pscx", library=library, master=master)
    assert error.value.code == "MMC_ACCEPTANCE_INCOMPLETE"


def test_compile_metadata_can_precede_fresh_output(tmp_path):
    import os
    import time
    part = output_fixture(tmp_path)
    metadata = part.with_name("case.inf")
    start = time.time() - 1
    os.utime(metadata, (start - 100, start - 100))
    manifest = fault_channels.snapshot_output_dataset(part, started_after=start)
    fault_channels.verify_output_dataset(manifest)


def test_first_vendor_save_can_rebind_only_virtual_root(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET
    project, library, master = installed_sources
    derived = tmp_path / "observed.pscx"
    contract = fault_channels.instrument_fault_channels(project, derived, library=library, master=master)
    tree = ET.parse(derived)
    tree.find("./hierarchy/call").set("link", "777777")
    tree.write(derived, encoding="utf-8")
    finalized = fault_channels.finalize_fault_instrumentation(derived, contract)
    assert finalized["readback"]["matched"] is True
    assert finalized["virtual_root_rebinding"]["after"] == "Station[777777]"
    assert all(channel["instance_path"].startswith("Station[777777]/") for channel in finalized["channels"])
    tree = ET.parse(derived)
    next(item for item in tree.findall(".//User") if item.get("id") == "1167847391").set("id", "999")
    tree.write(derived, encoding="utf-8")
    with pytest.raises(BackendError):
        fault_channels.finalize_fault_instrumentation(derived, finalized)


@pytest.mark.parametrize("defect", ["delete_wire", "move_wire", "port_position", "port_condition"])
def test_measurement_connectivity_and_port_readback_cannot_drift(tmp_path, installed_sources, defect):
    from xml.etree import ElementTree as ET
    project, library, master = installed_sources
    derived = tmp_path / "observed.pscx"
    contract = fault_channels.instrument_fault_channels(project, derived, library=library, master=master)
    tree = ET.parse(derived)
    if "wire" in defect:
        generated_pgb = next(item for item in tree.findall(".//User") if item.get("id") == contract["channels"][0]["owner_id"])
        canvas = next(item for item in tree.findall(".//schematic") if generated_pgb in list(item))
        wire = next(item for item in canvas.findall("Wire") if item.get("y") == generated_pgb.get("y") and item.get("x") == str(int(generated_pgb.get("x")) - 72))
        if defect == "delete_wire":
            canvas.remove(wire)
        else:
            wire.find("vertex").set("x", "18")
    else:
        definition = next(item for item in tree.findall("./definitions/Definition") if item.get("name") == "MmcObservedFullCell")
        port = next(item for item in definition.findall("./svg/port") if item.get("name") == "Ntop")
        if defect == "port_position":
            port.set("y", "-72")
        else:
            port.text = "DTBP==1"
    tree.write(derived, encoding="utf-8")
    with pytest.raises(BackendError) as error:
        fault_channels.verify_fault_instrumentation(derived, contract)
    assert error.value.code == "MMC_POSTCONDITION_FAILED"


@pytest.mark.parametrize("changed_first", [True, False])
def test_duplicate_wire_owner_is_rejected_in_either_order(tmp_path, installed_sources, changed_first):
    from xml.etree import ElementTree as ET
    project, library, master = installed_sources
    derived = tmp_path / "observed.pscx"
    contract = fault_channels.instrument_fault_channels(project, derived, library=library, master=master)
    tree = ET.parse(derived)
    record = contract["readback_wires"][0]
    definition = next(item for item in tree.findall("./definitions/Definition") if item.get("name") == record["definition_name"])
    canvas = definition.find("schematic")
    wire = next(item for item in canvas.findall("Wire") if item.get("id") == record["owner_id"])
    changed = copy.deepcopy(wire)
    changed.find("vertex").set("x", "900")
    if changed_first:
        canvas.insert(list(canvas).index(wire), changed)
    else:
        canvas.append(changed)
    tree.write(derived, encoding="utf-8")
    with pytest.raises(BackendError) as error:
        fault_channels.verify_fault_instrumentation(derived, contract)
    assert error.value.code == "MMC_POSTCONDITION_FAILED"


def test_channel_file_hash_must_belong_to_frozen_dataset(tmp_path):
    samples, contract, checks = fault_fixture()
    part = output_fixture(tmp_path)
    manifest = fault_channels.snapshot_output_dataset(part)
    for channel in samples["channels"]:
        channel.update(output_part=str(part), metadata_file=str(part.with_name("case.inf")), hash=manifest["files"][part.name]["sha256"], metadata_sha256=manifest["files"]["case.inf"]["sha256"])
    samples["identity"] = manifest
    samples["channels"][0]["hash"] = "0" * 64
    report = evaluate(samples, contract, checks)
    assert report["verdict"] == "INCOMPLETE_ANALYSIS"
    assert any("dataset_membership" in item for item in report["invalid_evidence"])


def test_valid_dataset_member_cannot_impersonate_another_numbered_part(tmp_path):
    samples, contract, checks = fault_fixture()
    part = output_fixture(tmp_path)
    part.with_name("case_02.out").write_text("0.0 0.0\n0.1 1.0\n", encoding="ascii")
    manifest = fault_channels.snapshot_output_dataset(part)
    for channel in samples["channels"]:
        channel.update(output_part=str(part), metadata_file=str(part.with_name("case.inf")), hash=manifest["files"][part.name]["sha256"], metadata_sha256=manifest["files"]["case.inf"]["sha256"], call_id=1)
    samples["identity"] = manifest
    samples["channels"][0]["call_id"] = 11
    samples["channels"][0]["compiled_identity"] = {"index": "10", "id": "1:0"}
    report = evaluate(samples, contract, checks)
    assert report["verdict"] == "INCOMPLETE_ANALYSIS"
    assert any("dataset_part_mapping" in item for item in report["invalid_evidence"])


@pytest.mark.parametrize("defect", ["unequal", "partial_cycle", "frequency_missing"])
def test_arm_comparison_requires_equal_complete_cycle_windows(defect):
    samples, contract, checks = fault_fixture()
    if defect == "unequal":
        checks["recovery_window_s"] = [0.8, 0.81]
    elif defect == "partial_cycle":
        checks["prefault_window_s"] = [0.1, 0.305]
        checks["recovery_window_s"] = [0.795, 1.0]
    else:
        checks.pop("frequency_hz")
    assert evaluate(samples, contract, checks)["verdict"] == "INCOMPLETE_ANALYSIS"


def test_equal_arm_rms_with_unstable_cycle_rms_does_not_pass():
    samples, contract, checks = fault_fixture()
    channel = next(item for item in samples["channels"] if item["description"] == "i_arm")
    channel["values"] = [1.0 if int(round(time * 60, 5)) % 2 else 2.0 for time in channel["domain"]]
    report = evaluate(samples, contract, checks)
    assert report["verdict"] == "FAIL"
    check = next(item for item in report["check_results"] if item["name"] == "i_arm_operating_point")
    assert check["status"] == "FAIL"


def test_native_dc_fault_binds_the_actual_timer_branch_and_clearing(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET

    from pscad_mcp.hvdc.builders.mmc.template_audit import _components, _parameters
    from pscad_mcp.hvdc.builders.mmc.template_native import (
        materialize_template_native_scenario,
    )
    project, _, _ = installed_sources
    derived = tmp_path / "native.pscx"
    record = materialize_template_native_scenario(project, derived, dc_fault_time_s=2.5, fault_duration_s=0.2)
    root = ET.parse(derived).getroot()
    timer = next(item for item in _components(root) if item.get("id") == "1067520513")
    assert dict(_parameters(timer))["DF"] == "0.2"
    location = next(item for item in _components(root) if item.get("id") == "1311596185")
    assert dict(_parameters(location))["Value"] == "3"
    switch = next(item for item in _components(root) if item.get("id") == "983117456")
    assert dict(_parameters(switch))["OpCur"] == "1"
    assert record["fault_execution"]["clearing_policy"] == "imposed_fault_removed_at_scheduled_time"


def test_stable_recovery_at_wrong_dc_reference_fails():
    samples, contract, checks = fault_fixture()
    channel = next(item for item in samples["channels"] if item["description"] == "v_dc")
    channel["values"] = [600.0 if value == 640 else value for value in channel["values"]]
    assert evaluate(samples, contract, checks)["verdict"] == "FAIL"


def test_recovery_must_still_meet_nominal_voltage_band():
    samples, contract, checks = fault_fixture()
    channel = next(item for item in samples["channels"] if item["description"] == "v_dc")
    channel["values"] = [600.0 if t >= 0.6 else 616.0 if v == 640 else v for t, v in zip(channel["domain"], channel["values"])]
    assert evaluate(samples, contract, checks)["verdict"] == "FAIL"


def test_compiler_metadata_must_match_measured_owner(tmp_path, installed_sources):
    import asyncio
    from xml.etree import ElementTree as ET
    project, library, master = installed_sources
    derived = tmp_path / "observed.pscx"
    contract = fault_channels.instrument_fault_channels(project, derived, library=library, master=master)
    binding = contract["channels"][0]
    contract["channels"] = [binding]
    description = binding["selector"]["description"]
    (tmp_path / "case.inf").write_text(f'PGB(1) Output Desc="{description}" Group="{fault_channels.OUTPUT_GROUP}" Max=1 Min=0 Units="1"\n', encoding="ascii")
    part = tmp_path / "case_01.out"
    part.write_text("0.0 0.0\n0.1 1.0\n", encoding="ascii")
    metadata = ET.Element("Output", {"device": "EMTDC"})
    ET.SubElement(metadata, "Domain", {"name": "Time", "unit": "s"})
    ET.SubElement(metadata, "Analog", {"name": "Main(0):" + description, "id": "wrong-owner:0", "index": "0", "label": fault_channels.OUTPUT_GROUP, "dim": "1", "unit": "1"})
    ET.ElementTree(metadata).write(tmp_path / "case.infx", encoding="utf-8")
    async def reader(*args, **kwargs):
        return {"channels": [{"description": description, "group": fault_channels.OUTPUT_GROUP, "units": "1", "domain": [0.0, 0.1], "values": [0.0, 1.0]}]}
    with pytest.raises(BackendError) as error:
        asyncio.run(fault_channels.read_fault_output_dataset(reader, part, contract))
    assert error.value.code == "MMC_OUTPUT_IDENTITY_CHANGED"


@pytest.mark.parametrize("channel_id,compiled_scope", [
    ("MFE_T1_A_upper_v_inserted", "Main(0)\\MFE_PWM_T1(0)\\MFE_Pole_T1_A(0)"),
    ("MFE_T1_controller_freeze", "Main(0)\\MFE_VSC_T1(VSC T1)\\MFE_Control_T1(0)"),
])
def test_compiler_metadata_keeps_full_instance_hierarchy(tmp_path, installed_sources, channel_id, compiled_scope):
    import asyncio
    from xml.etree import ElementTree as ET
    project, library, master = installed_sources
    derived = tmp_path / "observed.pscx"
    contract = fault_channels.instrument_fault_channels(project, derived, library=library, master=master)
    binding = next(item for item in contract["channels"] + contract["diagnostic_channels"] if item["channel_id"] == channel_id)
    contract["channels"] = [binding]
    contract["diagnostic_channels"] = []
    description = binding["selector"]["description"]
    units = binding["units"]
    (tmp_path / "case.inf").write_text(f'PGB(1) Output Desc="{description}" Group="{fault_channels.OUTPUT_GROUP}" Max=1 Min=0 Units="{units}"\n', encoding="ascii")
    part = tmp_path / "case_01.out"
    part.write_text("0.0 0.0\n0.1 1.0\n", encoding="ascii")
    metadata = ET.Element("Output", {"device": "EMTDC"})
    ET.SubElement(metadata, "Domain", {"name": "Time", "unit": "s"})
    ET.SubElement(metadata, "Analog", {"name": compiled_scope + ":" + description, "id": binding["owner_id"] + ":0", "index": "0", "label": fault_channels.OUTPUT_GROUP, "dim": "1", "unit": units})
    ET.ElementTree(metadata).write(tmp_path / "case.infx", encoding="utf-8")
    async def reader(*args, **kwargs):
        return {"channels": [{"description": description, "group": fault_channels.OUTPUT_GROUP, "units": units, "domain": [0.0, 0.1], "values": [0.0, 1.0]}]}
    samples = asyncio.run(fault_channels.read_fault_output_dataset(reader, part, contract))
    assert samples["channels"][0]["compiled_identity"]["name"] == compiled_scope + ":" + description
    metadata.find("Analog").set("name", compiled_scope.replace("Main(0)", "OtherMain(0)") + ":" + description)
    ET.ElementTree(metadata).write(tmp_path / "case.infx", encoding="utf-8")
    with pytest.raises(BackendError):
        asyncio.run(fault_channels.read_fault_output_dataset(reader, part, contract))


def test_derived_voltage_controller_has_bounded_current_headroom_and_matching_freeze(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET

    from pscad_mcp.hvdc.builders.mmc.template_audit import _components, _parameters
    project, _, _ = installed_sources
    destination = tmp_path / "headroom.pscx"
    report = fault_channels.materialize_voltage_control_headroom(project, destination, current_limit_pu=1.05)
    root = ET.parse(destination).getroot()
    users = {item.get("id"): item for item in _components(root)}
    assert dict(_parameters(users["976600655"]))["Imax"] == "1.05"
    assert dict(_parameters(users["800413106"]))["Imax"] == "1"
    assert users["278203269"].get("defn") == "master:gain"
    assert dict(_parameters(users["278203269"]))["G"] == "0.99999"
    assert report["freeze_reference"] == "0.99999 * Imax"
    assert all(dict(_parameters(users[owner]))["IvlMax"] == "3.0 [kA]" for owner in ("1167847391", "1268416470"))
    assert report["phase_current_peak_ka"] == pytest.approx(1.05 * 1000 / (3 ** 0.5 * 370) * 2 ** 0.5)


def test_steady_arm_current_must_respect_existing_hard_peak_limit():
    samples, contract, checks = fault_fixture()
    channel = next(item for item in samples["channels"] if item["description"] == "i_arm")
    channel["values"] = [3.1 for _ in channel["values"]]
    assert evaluate(samples, contract, checks)["verdict"] == "FAIL"


@pytest.mark.parametrize("owner,parameter,value", [
    ("976600655", "Vtr_2", "370 [V]"),
    ("976600655", "Sbase", "1000 [kVA]"),
    ("1167847391", "IvlMax", "3 [A]"),
])
def test_headroom_repair_rejects_incorrect_physical_unit_scale(tmp_path, installed_sources, owner, parameter, value):
    from xml.etree import ElementTree as ET
    project, _, _ = installed_sources
    tree = ET.parse(project)
    component = next(item for item in tree.findall(".//User") if item.get("id") == owner)
    next(item for item in component.findall("./paramlist/param") if item.get("name") == parameter).set("value", value)
    changed = tmp_path / "source.pscx"
    tree.write(changed, encoding="utf-8")
    with pytest.raises(BackendError):
        fault_channels.materialize_voltage_control_headroom(changed, tmp_path / "derived.pscx")


def test_headroom_repair_converts_explicit_equivalent_units(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET
    project, _, _ = installed_sources
    tree = ET.parse(project)
    replacements = {("976600655", "Vtr_2"): "370000 [V]", ("976600655", "Sbase"): "1000000 [kVA]", ("1167847391", "IvlMax"): "3000 [A]"}
    for component in tree.findall(".//User"):
        for param in component.findall("./paramlist/param"):
            if (key := (component.get("id"), param.get("name"))) in replacements:
                param.set("value", replacements[key])
    changed = tmp_path / "source.pscx"
    tree.write(changed, encoding="utf-8")
    report = fault_channels.materialize_voltage_control_headroom(changed, tmp_path / "derived.pscx")
    assert report["arm_protection_limit_ka"] == 3.0


@pytest.mark.parametrize("operation", ["instrument", "headroom", "native"])
def test_derived_writers_never_replace_a_racing_target(tmp_path, installed_sources, monkeypatch, operation):
    project, library, master = installed_sources
    destination = (tmp_path / "racing.pscx").resolve()
    real_exists = Path.exists
    raced = False
    def exists(path):
        nonlocal raced
        if path == destination and not raced:
            raced = True
            path.write_bytes(b"foreign-owner")
            return False
        return real_exists(path)
    monkeypatch.setattr(Path, "exists", exists)
    with pytest.raises(BackendError) as error:
        if operation == "instrument":
            fault_channels.instrument_fault_channels(project, destination, library=library, master=master)
        elif operation == "headroom":
            fault_channels.materialize_voltage_control_headroom(project, destination)
        else:
            from pscad_mcp.hvdc.builders.mmc.template_native import (
                materialize_template_native_scenario,
            )
            materialize_template_native_scenario(project, destination, dc_fault_time_s=2.5, fault_duration_s=0.2)
    assert error.value.code == "MMC_BUILD_CONFLICT"
    assert destination.read_bytes() == b"foreign-owner"


@pytest.mark.parametrize("operation", ["instrument", "headroom"])
def test_raw_dangling_destination_is_rejected_before_resolution(tmp_path, installed_sources, monkeypatch, operation):
    project, library, master = installed_sources
    alias = tmp_path / "alias.pscx"
    redirected = tmp_path / "redirected.pscx"
    real_resolve, real_symlink = Path.resolve, Path.is_symlink
    monkeypatch.setattr(Path, "resolve", lambda path, *args, **kwargs: redirected if path == alias else real_resolve(path, *args, **kwargs))
    monkeypatch.setattr(Path, "is_symlink", lambda path: True if path == alias else real_symlink(path))
    with pytest.raises(BackendError):
        if operation == "instrument":
            fault_channels.instrument_fault_channels(project, alias, library=library, master=master)
        else:
            fault_channels.materialize_voltage_control_headroom(project, alias)
    assert not redirected.exists()


def test_dc_feedback_filter_changes_only_the_outer_feedback_branch(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET

    from pscad_mcp.hvdc.builders.mmc.template_audit import _components, _parameters
    project, _, master = installed_sources
    destination = tmp_path / "filtered.pscx"
    result = fault_channels.materialize_dc_feedback_filter(project, destination, master=master, time_constant_s=0.005)
    root = ET.parse(destination).getroot()
    users = {item.get("id"): item for item in _components(root)}
    assert dict(_parameters(users["177754199"]))["Name"] == "MmcFilteredVdcPu"
    assert all(dict(_parameters(users[owner]))["Name"] == "Edc_Pu" for owner in ("1379729478", "1453282758"))
    added = users[result["filter_owner"]]
    assert added.get("defn") == "master:realpole"
    assert dict(_parameters(added)) == {"G": "1.0", "T": "0.005 [s]", "Dim": "1", "Limit": "0", "Reset": "2", "YO": "Edc_Pu", "Min": "-10.0", "Max": "10.0", "COM": "MMC DC feedback only"}
    assert result["initialization"] == "reset_to_raw_feedback_at_timezero"
    assert result["raw_feedback_label_owners"] == ["1379729478", "1453282758"]


def test_carrier_diagnostic_changes_only_terminal_two_ratio(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET

    from pscad_mcp.hvdc.builders.mmc.template_audit import _components, _parameters
    project, _, _ = installed_sources
    destination = tmp_path / "carrier.pscx"
    before = {item.get("id"): dict(_parameters(item)) for item in _components(ET.parse(project).getroot())}
    result = fault_channels.materialize_terminal_two_carrier(project, destination)
    after = {item.get("id"): dict(_parameters(item)) for item in _components(ET.parse(destination).getroot())}
    assert after["1268416470"]["Cfreq"] == "23"
    before["1268416470"]["Cfreq"] = "23"
    assert before == after
    assert result["cell_carrier_frequency_hz"] == 1380.0
    assert result["before_ratio"] == 3.0


def test_dc_damping_is_in_power_branch_before_total_current_limit(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET

    from pscad_mcp.hvdc.builders.mmc.template_audit import _components, _parameters
    project, _, master = installed_sources
    filtered = tmp_path / "filtered.pscx"
    fault_channels.materialize_dc_feedback_filter(project, filtered, master=master)
    derived = tmp_path / "damped.pscx"
    result = fault_channels.materialize_dc_port_damping(filtered, derived, master=master)
    root = ET.parse(derived).getroot()
    components = {item.get("id"): item for item in _components(root)}
    assert dict(_parameters(components["1359229547"]))["UL"] == "Imax"
    assert dict(_parameters(components["1610070623"]))["A"] == "1"
    assert result["equation"] == "power_mode_id = Idref1 - 1.5 * (Edc_Pu - MmcFilteredVdcPu)"
    assert result["dc_gain"] == 0.0
    assert result["branch"] == "P_mode_InA_before_Imag_limiter"
    assert components[result["gain_owner"]].get("defn") == "master:gain"
    assert dict(_parameters(components[result["gain_owner"]]))["G"] == "1.5"


@pytest.mark.parametrize("parameter,value", [("G", "0.5"), ("T", "0.006 [s]"), ("Dim", "2"), ("Limit", "1"), ("Reset", "0"), ("YO", "0")])
def test_dc_damping_rejects_a_changed_filter_contract(tmp_path, installed_sources, parameter, value):
    from xml.etree import ElementTree as ET
    project, _, master = installed_sources
    filtered = tmp_path / "filtered.pscx"
    record = fault_channels.materialize_dc_feedback_filter(project, filtered, master=master)
    tree = ET.parse(filtered)
    element = next(item for item in tree.findall(".//User") if item.get("id") == record["filter_owner"])
    next(item for item in element.findall("./paramlist/param") if item.get("name") == parameter).set("value", value)
    tree.write(filtered, encoding="utf-8")
    with pytest.raises(BackendError):
        fault_channels.materialize_dc_port_damping(filtered, tmp_path / "damped.pscx", master=master)


def test_dc_damping_rejects_a_disconnected_filter(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET
    project, _, master = installed_sources
    filtered = tmp_path / "filtered.pscx"
    fault_channels.materialize_dc_feedback_filter(project, filtered, master=master)
    tree = ET.parse(filtered)
    scope = next(item for item in tree.findall("./definitions/Definition") if item.get("name") == "VSCControl2").find("schematic")
    wire = next(item for item in scope.findall("Wire") if item.get("x") == "3528" and item.get("y") == "3402")
    scope.remove(wire)
    tree.write(filtered, encoding="utf-8")
    with pytest.raises(BackendError):
        fault_channels.materialize_dc_port_damping(filtered, tmp_path / "damped.pscx", master=master)


def test_virtual_resistance_uses_measured_arm_current_and_common_voltage_channel(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET

    from pscad_mcp.hvdc.builders.mmc.template_audit import _components, _parameters
    project, _, master = installed_sources
    destination = tmp_path / "virtual_resistance.pscx"
    result = fault_channels.materialize_arm_virtual_resistance(project, destination, master=master)
    root = ET.parse(destination).getroot()
    users = {item.get("id"): item for item in _components(root)}
    assert dict(_parameters(users["166206085"]))["Name"] == "MmcVzEffective"
    assert dict(_parameters(users["1642798056"]))["Name"] == "Vz"
    assert result["resistance_per_arm_ohm"] == 30.0
    assert result["equivalent_dc_resistance_ohm"] == 20.0
    assert result["gain_pu_per_ka"] == 0.09375
    assert result["command_difference_unchanged"] is True
    assert dict(_parameters(users[result["filter_owner"]]))["YO"] == "MmcIcircRaw"
    assert result["dc_gain"] == 0.0


def test_virtual_resistance_instrumentation_freezes_final_cell_definitions(tmp_path, installed_sources):
    project, library, master = installed_sources
    modified = tmp_path / "virtual.pscx"
    fault_channels.materialize_arm_virtual_resistance(project, modified, master=master)
    instrumented = tmp_path / "observed.pscx"
    contract = fault_channels.instrument_fault_channels(modified, instrumented, library=library, master=master)
    assert fault_channels.verify_fault_instrumentation(instrumented, contract)["matched"] is True


def test_instrumentation_requires_every_arm_modulation_source(tmp_path, installed_sources):
    from xml.etree import ElementTree as ET

    from pscad_mcp.hvdc.builders.mmc.template_audit import _parameters
    project, library, master = installed_sources
    tree = ET.parse(project)
    for definition in tree.findall("./definitions/Definition"):
        if definition.get("name") == "MMC_Hb_Pole_PWM":
            canvas = definition.find("schematic")
            for component in list(canvas):
                if component.get("defn") == "master:datalabel" and dict(_parameters(component)).get("Name") == "VrefT":
                    canvas.remove(component)
    changed = tmp_path / "source.pscx"
    tree.write(changed, encoding="utf-8")
    with pytest.raises(BackendError) as error:
        fault_channels.instrument_fault_channels(changed, tmp_path / "derived.pscx", library=library, master=master)
    assert error.value.code == "MMC_ACCEPTANCE_INCOMPLETE"


@pytest.mark.parametrize("missing", ["binding", "sample"])
def test_steady_requires_all_twelve_modulation_bindings_and_samples(missing):
    from tests.test_mmc_fault_evidence_real import _steady
    samples, contract, checks = fault_fixture()
    checks.update(require_modulation_evidence=True, modulation_abs_limit=2.0)
    for item in samples["channels"]:
        item["channel_id"] = item["description"]
    contract["diagnostic_channels"] = []
    for station in ("T1", "T2"):
        for phase in ("A", "B", "C"):
            for arm in ("upper", "lower"):
                channel_id = f"MFE_{station}_{phase}_{arm}_modulation_request"
                contract["diagnostic_channels"].append({"role": "modulation_request", "channel_id": channel_id, "model_scope": f"{station}/{phase}/{arm}"})
                samples["channels"].append({"channel_id": channel_id, "domain": samples["channels"][0]["domain"], "values": [1.0] * len(samples["channels"][0]["domain"]), "output_part": "synthetic_01.out"})
    if missing == "binding":
        contract["diagnostic_channels"].pop()
    else:
        samples["channels"].pop()
    result = _steady(samples, contract, checks)
    assert result["verdict"] == "INCOMPLETE_ANALYSIS"


def test_fault_evaluation_requires_requested_modulation_coverage():
    samples, contract, checks = fault_fixture()
    checks.update(require_modulation_evidence=True, modulation_abs_limit=2.0)
    result = evaluate(samples, contract, checks)
    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert "modulation_coverage" in result["invalid_evidence"]


def test_owned_session_is_cleaned_when_status_raises(monkeypatch):
    import asyncio

    from tests.test_mmc_fault_evidence_real import _with_owned_connection
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    class Backend:
        def __init__(self):
            self.owns_process = True
            self.session_details = {"managed_pid": 42, "mode": "managed-launch"}
    backend = Backend()
    class Service:
        _backend = backend
        quit_called = False
        async def attach_local(self):
            return "owned launch"
        async def status(self):
            raise RuntimeError("status unavailable after owned launch")
        async def quit_pscad(self, **kwargs):
            self.quit_called = True
            backend.owns_process = False
    service = Service()
    report = {}
    async def operation():
        raise AssertionError("must not start case execution")
    with pytest.raises(RuntimeError, match="status unavailable"):
        asyncio.run(_with_owned_connection(service, backend, report, operation, process_reader=list))
    assert service.quit_called
    assert report["launch_ownership"]["session"]["managed_pid"] == 42
    assert report["owned_process_cleaned"] is True


def test_owned_runner_clears_service_pending_launch_without_heartbeat(monkeypatch):
    import asyncio

    from pscad_mcp.core.service import PscadService
    from tests.test_mmc_fault_evidence_real import _with_owned_connection
    from tests.test_service_attach_cleanup import AttachBackend
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    backend = AttachBackend("owned")
    service = PscadService(lambda: backend)
    report = {}
    async def operation():
        raise AssertionError("failed connection must not execute a case")
    with pytest.raises(BackendError, match="could not be closed"):
        asyncio.run(_with_owned_connection(service, backend, report, operation, process_reader=list))
    assert service._pending_cleanup_backend is None
    assert backend.calls == ["attach", "quit", "quit"]
    assert report["owned_process_cleaned"] is True
    assert report["launch_ownership"]["session"]["managed_pid"] == 4242


def test_reanalysis_rejects_a_changed_frozen_channel_contract(tmp_path):
    import importlib.util
    import json
    module_path = Path(__file__).parents[1] / "docs/acceptance/mmc-fault-evidence/reanalyse.py"
    spec = importlib.util.spec_from_file_location("mmc_reanalysis_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    contract_path = tmp_path / "channels.json"
    contract_path.write_text('{"schema_version":1}', encoding="ascii")
    record = {"channel_contract_path": str(contract_path), "channel_contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest()}
    contract_path.write_text('{"schema_version":1,"changed":true}', encoding="ascii")
    with pytest.raises(BackendError):
        module.load_frozen_case(record)
    assert json.loads(contract_path.read_text())["changed"] is True
