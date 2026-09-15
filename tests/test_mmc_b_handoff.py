"""Focused rejection tests for the read-only native handoff gate."""

import asyncio
import copy
import hashlib
import json
from pathlib import PureWindowsPath

import pytest

from tests import mmc_b_handoff as gate


def reference(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.mark.parametrize("change", [None, "id", "parameters", "steps"])
def test_recipe_comparison_does_not_conflate_independent_producers(change):
    b = {"id": "native_full_sort_dc_integral_004_v1", "parameters": {"t1_dc_integral_time_s": 0.04},
         "steps": [{"name": "complete_arm_sorting", "parameters": {}}], "producer_code_hashes": {"B": "old"}}
    public = {"name": b["id"], "parameters": copy.deepcopy(b["parameters"]), "steps": copy.deepcopy(b["steps"]),
              "producer_code_hashes": {"public": "new"}}
    if change == "id":
        b["id"] = "raw"
    elif change == "parameters":
        b["parameters"]["t1_dc_integral_time_s"] = 0.08
    elif change == "steps":
        b["steps"] = []
    if change:
        with pytest.raises(ValueError, match="different model recipes"):
            gate.require_recipe_match(b, public)
    else:
        assert gate.require_recipe_match(b, public)


@pytest.mark.parametrize("change", [None, "parameter", "step", "headroom", "filter", "carrier", "resistance", "sorting", "integral", "master", "library", "fault_start", "fault_duration", "fault_location", "case_mode"])
def test_declared_recipe_is_bound_to_actual_native_stages(tmp_path, change):
    master = reference(tmp_path / "master.pslx", "master")
    library = reference(tmp_path / "library.pslx", "library")
    parameters = {"current_limit_pu": 1.1, "dc_feedback_time_constant_s": 0.005,
                  "terminal_two_carrier_ratio": 23.0, "arm_virtual_resistance_ohm": 30.0,
                  "sort_extent": "Dim", "sort_enable": "existing_Enab", "t1_dc_integral_time_s": 0.04}
    recipe = {"id": "native_full_sort_dc_integral_004_v1", "parameters": parameters,
              "steps": gate._expected_recipe_steps(parameters)}
    case = {"recipe_id": recipe["id"], "case": "fault", "fault": True,
            "native_binding": {"timing_basis": "template_embedded_emt", "bindings": [
                {"owner": "208155720", "name": "Fault Time", "parameter": "Value", "value": "2.5"},
                {"owner": "152486038", "name": "TFlt", "parameter": "TFlt", "value": "2.5"},
                {"owner": "152486038", "name": "FltDur", "parameter": "FltDur", "value": "0.2"},
                {"owner": "1067520513", "name": "DC fault timer", "parameter": "DF", "value": "0.2"},
                {"owner": "1311596185", "name": "Flt Location", "parameter": "Value", "value": "3"},
                {"owner": "983117456", "name": "DC_flt_2_PN", "parameter": "OpCur", "value": "1"}],
                "fault_execution": {"timer_duration_s": 0.2, "timer_owner": "1067520513", "timer_start_signal": "Flt_time",
                                    "fault_location": 3, "fault_switch_owner": "983117456", "fault_switch_signal": "DC_flt_2_PN",
                                    "clearing_policy": "imposed_fault_removed_at_scheduled_time", "actual_state_required": "OPENBR"}},
            "charging_delay_repair": {"before": "Tcharging1", "after": "Tcharging2", "terminal_one_unchanged": True},
            "operating_point_repair": {"parameter": "Imax", "after_pu": 1.1, "freeze_reference": "0.99999 * Imax", "arm_protection_limit_ka": 3.0},
            "feedback_filter": {"time_constant_s": 0.005, "master_sha256": master["sha256"], "raw_voltage_acceptance": True},
            "carrier_diagnostic": {"after_ratio": 23.0, "fundamental_frequency_hz": 60.0},
            "arm_virtual_resistance": {"resistance_per_arm_ohm": 30.0, "master_sha256": master["sha256"], "dc_gain": 0.0,
                                       "command_difference_unchanged": True, "existing_cell_count_saturation_retained": True},
            "complete_sorting": {"sort_extent": "Dim", "library_sha256": library["sha256"], "requested_count_unchanged": True,
                                 "enable_unchanged": True, "current_and_firing_unchanged": True},
            "dc_integral_repair": {"after_s": 0.04, "proportional_gain_unchanged": 12.0,
                                   "terminal_two_unchanged": True, "nominal_and_limits_unchanged": True}}
    if change == "parameter":
        recipe["parameters"]["arm_virtual_resistance_ohm"] = 25.0
    elif change == "step":
        recipe["steps"][4]["parameters"]["resistance_per_arm_ohm"] = 25.0
    elif change == "headroom":
        case["operating_point_repair"]["after_pu"] = 1.05
    elif change == "filter":
        case["feedback_filter"]["time_constant_s"] = 0.01
    elif change == "carrier":
        case["carrier_diagnostic"]["after_ratio"] = 3.0
    elif change == "resistance":
        case["arm_virtual_resistance"]["resistance_per_arm_ohm"] = 25.0
    elif change == "sorting":
        case["complete_sorting"]["sort_extent"] = "NS"
    elif change == "integral":
        case["dc_integral_repair"]["after_s"] = 0.08
    elif change == "master":
        case["feedback_filter"]["master_sha256"] = "0" * 64
    elif change == "library":
        case["complete_sorting"]["library_sha256"] = "0" * 64
    elif change == "fault_start":
        case["native_binding"]["bindings"][0]["value"] = "2.4"
    elif change == "fault_duration":
        case["native_binding"]["fault_execution"]["timer_duration_s"] = 0.1
    elif change == "fault_location":
        case["native_binding"]["fault_execution"]["fault_location"] = 2
    elif change == "case_mode":
        case["fault"] = False
        case["native_binding"]["bindings"][0]["value"] = "10"
        case["native_binding"]["bindings"][1]["value"] = "10"
    if change:
        with pytest.raises(ValueError, match="recipe|fault"):
            gate._verify_recipe_evidence(recipe, case, {"master": master, "library": library}, gate.default_fault_checks())
    else:
        gate._verify_recipe_evidence(recipe, case, {"master": master, "library": library}, gate.default_fault_checks())


@pytest.mark.parametrize(("status", "scope", "cleaned"), [
    ("FAIL", "steady_and_dc_fault_recovery", True),
    ("PASS", "steady_only_diagnostic", True),
    ("PASS", "steady_and_dc_fault_recovery", False),
])
def test_incomplete_native_evidence_never_reads_output(tmp_path, status, scope, cleaned):
    report = reference(tmp_path / "run" / "acceptance-report.json",
                       {"status": status, "scope": scope, "owned_process_cleaned": cleaned})
    handoff = tmp_path / "handoff.json"
    reference(handoff, {"schema_version": 1, "scope": "template_native_dc_fault", "evidence": {"acceptance_report": report}})
    calls = []

    async def reader(*args, **kwargs):
        calls.append("read")

    with pytest.raises(ValueError, match="has not completed"):
        asyncio.run(gate.validate_b_handoff(handoff, reader))
    assert calls == []


@pytest.mark.parametrize("concurrent", [False, True])
@pytest.mark.parametrize("change", ["launch_owns", "runtime_owns", "pid", "executable", "mode", "missing_pid", "boolean_pid", "zero_pid"])
def test_historical_ownership_is_required_independently_of_loader_environment(tmp_path, monkeypatch, concurrent, change):
    if concurrent:
        monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    else:
        monkeypatch.delenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", raising=False)
    identity = {"owns_process": True, "session": {"mode": "managed-launch", "managed_pid": 123,
                 "managed_executable": str(tmp_path / "pscad.exe")}}
    launch, runtime = copy.deepcopy(identity), copy.deepcopy(identity)
    runtime.update(licensed=True, backend="legacy", version="4.6.2")
    if change == "launch_owns":
        launch["owns_process"] = False
    elif change == "runtime_owns":
        runtime["owns_process"] = False
    elif change == "pid":
        runtime["session"]["managed_pid"] = 456
    elif change == "executable":
        runtime["session"]["managed_executable"] = str(tmp_path / "other" / "pscad.exe")
    elif change == "mode":
        launch["session"]["mode"] = "attached"
    elif change == "missing_pid":
        launch["session"].pop("managed_pid")
    elif change == "boolean_pid":
        launch["session"]["managed_pid"] = True
    elif change == "zero_pid":
        launch["session"]["managed_pid"] = 0
    sources = {name: reference(tmp_path / "inputs" / (name + ".json"), name) for name in ("project", "library", "master")}
    checks = gate.default_fault_checks()
    report = {"status": "PASS", "scope": "steady_and_dc_fault_recovery", "owned_process_cleaned": True,
              "commit": "a" * 40, "root": str(tmp_path / "run"), "runtime": runtime, "launch_ownership": launch,
              "checks_contract": checks, "source_hashes": sources, "source_hashes_after": sources}
    report_ref = reference(tmp_path / "run" / "acceptance-report.json", report)
    handoff = tmp_path / "handoff.json"
    reference(handoff, {"schema_version": 1, "scope": "template_native_dc_fault", "producer_revision": "a" * 40,
                       "evidence": {"acceptance_report": report_ref}, "required_checks": checks,
                       "source_hashes": sources, "recipe": {}})
    calls = []

    def unsafe_progress(*args):
        calls.append("producer")
        raise ValueError("The producer stage was reached")

    monkeypatch.setattr(gate, "_verify_producers", unsafe_progress)
    with pytest.raises(ValueError, match="owned PSCAD"):
        asyncio.run(gate.validate_b_handoff(handoff))
    assert calls == []


def test_file_reference_rejects_content_drift_and_foreign_case(tmp_path):
    ref = reference(tmp_path / "run" / "data.json", {"value": 1})
    assert gate._check_ref(ref, within=tmp_path / "run") == ref
    with pytest.raises(ValueError, match="outside"):
        gate._check_ref(ref, within=tmp_path / "other")
    with pytest.raises(ValueError, match="different case"):
        gate._check_ref(ref, expected=tmp_path / "other.json")
    (tmp_path / "run" / "data.json").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="identity changed"):
        gate._check_ref(ref)


@pytest.mark.parametrize("windows_paths", [False, True])
def test_producer_must_be_the_code_recorded_by_the_native_run(tmp_path, windows_paths):
    refs = {name: reference(tmp_path / (name + ".py"), name) for name in ("fault_channels", "template_native")}
    recipe = {"producer_code_hashes": refs}
    report = {"code_hashes": {f"pscad_mcp/hvdc/builders/mmc/{name}.py": ref["sha256"] for name, ref in refs.items()}}
    if windows_paths:
        report["code_hashes"] = {str(PureWindowsPath(key)): digest for key, digest in report["code_hashes"].items()}
    gate._verify_producers(recipe, report)
    key = next(key for key in report["code_hashes"] if key.endswith("fault_channels.py"))
    report["code_hashes"][key] = "0" * 64
    with pytest.raises(ValueError, match="producer differs"):
        gate._verify_producers(recipe, report)


@pytest.mark.parametrize("change", [None, "source", "missing", "file"])
def test_recipe_lineage_must_connect_actual_frozen_files(tmp_path, change):
    refs = [reference(tmp_path / (str(index) + ".pscx"), {"stage": index}) for index in range(len(gate._STAGES) + 1)]
    case = {name: {"source": refs[index]["path"], "source_sha256": refs[index]["sha256"],
                   "destination": refs[index + 1]["path"], "destination_sha256": refs[index + 1]["sha256"]}
            for index, name in enumerate(gate._STAGES)}
    contract = {"source_hashes": {"project": refs[-1]}}
    if change == "source":
        case["feedback_filter"].update(source=refs[0]["path"], source_sha256=refs[0]["sha256"])
    elif change == "missing":
        case.pop("feedback_filter")
    elif change == "file":
        (tmp_path / "3.pscx").write_text("changed", encoding="utf-8")
    if change:
        with pytest.raises(ValueError):
            gate._verify_lineage(case, contract, tmp_path)
    else:
        gate._verify_lineage(case, contract, tmp_path)


@pytest.mark.parametrize("change", [None, "role", "part", "count", "missing", "duplicate", "metadata_sha256",
                                    "compiler_metadata_file", "compiler_metadata_sha256", "call_id", "compiled_identity", "definition_name", "nominal", "nominal_role"])
def test_handoff_channels_keep_bindings_and_observed_data_identity(change):
    binding = {"channel_id": "fault", "role": "fault_active", "model_scope": "T2", "owner_id": "7",
               "instance_path": "Main/T2", "definition": "master:pgb", "signal_source": {"kind": "physical_state"},
               "selector": {"description": "fault"}, "units": "1", "dimension": 1, "polarity": {"active": 1, "inactive": 0},
               "definition_name": "Main", "nominal": 1, "nominal_role": "physical_state"}
    observed = {"channel_id": "fault", "output_part": "case_01.out", "metadata_file": "case.inf", "sample_count": 20001,
                "time_bounds_s": [0, 5], "hash": "a" * 64, "metadata_sha256": "b" * 64,
                "compiler_metadata_file": "case.infx", "compiler_metadata_sha256": "c" * 64,
                "call_id": 1, "compiled_identity": {"id": "7:0", "index": "0"}}
    rows = [{**copy.deepcopy(binding), **observed}]
    if change == "role":
        rows[0]["role"] = "control_command"
    elif change == "part":
        rows[0]["output_part"] = "other_01.out"
    elif change == "count":
        rows[0]["sample_count"] = 3
    elif change == "missing":
        rows = []
    elif change == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif change:
        rows[0][change] = "changed"
    if change:
        with pytest.raises(ValueError):
            gate._verify_channel_handoff(rows, {"channels": [binding]}, {"channels": [observed]})
    else:
        gate._verify_channel_handoff(rows, {"channels": [binding]}, {"channels": [observed]})


@pytest.mark.parametrize("change", [None, "time", "proportional", "missing"])
def test_actual_pi_parameters_must_match_the_recipe(change):
    channels = []
    for terminal, role, value in (("T1", "proportional_gain", 12), ("T1", "integral_time", 0.04),
                                  ("T2", "proportional_gain", 0.2), ("T2", "integral_time", 0.2)):
        channels.append({"channel_id": f"MFE_{terminal}_controller_dc_{role}", "domain": [2, 3, 5], "values": [value] * 3})
    if change == "time":
        channels[1]["values"] = [0.08] * 3
    elif change == "proportional":
        channels[0]["values"] = [24] * 3
    elif change == "missing":
        channels.pop()
    args = ({"channels": channels}, {"parameters": {"t1_dc_integral_time_s": 0.04}},
            {"prefault_window_s": [2, 2.4], "recovery_window_s": [4.6, 5]})
    if change:
        with pytest.raises(ValueError):
            gate._verify_pi(*args)
    else:
        gate._verify_pi(*args)
