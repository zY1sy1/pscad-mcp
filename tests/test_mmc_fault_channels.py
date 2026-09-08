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
    times = [round(index * 0.01, 8) for index in range(101)]
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
        "schema_version": 1, "time_basis": "EMTDC", "time_units": "s", "output_step_s": 0.01,
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
