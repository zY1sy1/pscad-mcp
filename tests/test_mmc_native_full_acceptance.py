from copy import deepcopy

import pytest

from scripts.run_mmc_native_avm_full_acceptance import FAULT_KINDS, verify_suite


def accepted_records():
    base = {"status": "PASS", "diagnostic_control_kind": "dq_current", "source_inputs_immutable": True,
            "source_code_immutable": True, "cleanup": {"owned_process_cleaned": True, "errors": []},
            "code_before": {"commit": "a" * 40}, "request": {"rating": 1000},
            "plan": {"engine_plans": [{"capabilities": {"native_producer_hashes": {"native.py": "a" * 64}},
                                      "candidates": [{"parameters": {"voltage": 640}}]}]},
            **{name: True for name in ("assembly_accepted", "precharge_accepted", "steady_operating_accepted", "network_identities_accepted", "control_envelope_accepted", "dynamic_envelope_accepted")}}
    records = {name: {**deepcopy(base), "fault_kind": None if name == "normal" else name,
                      "fault_envelope_accepted": name != "normal", "fault_envelope": {"status": "PASS"}}
               for name in ("normal", *FAULT_KINDS)}
    replay = {"status": "PASS", "scope": "native_avm_independent_portable_reload", "source_inputs_immutable": True,
              "source_code_immutable": True, "cleanup": {"owned_process_cleaned": True, "errors": []},
              "portable_copy": {"compiled_artifacts_copied": False},
              "analysis": {k: {"status": "PASS"} for k in ("precharge", "steady", "network", "controls", "dynamics")}}
    return records, replay


def test_complete_suite_requires_all_physical_cases_and_independent_reload():
    report = verify_suite(*accepted_records())
    assert report["status"] == "PASS" and report["model_accepted"] is True
    assert report["intrinsic_dc_fault_blocking"] is False


@pytest.mark.parametrize("mutation", ("missing", "failed", "gate", "fault", "rating", "revision", "ownership", "replay", "compiled"))
def test_suite_cannot_promote_partial_changed_or_uncleaned_evidence(mutation):
    records, replay = accepted_records()
    case = records[FAULT_KINDS[0]]
    if mutation == "missing":
        del records[FAULT_KINDS[0]]
    elif mutation == "failed":
        case["status"] = "FAIL"
    elif mutation == "gate":
        case["control_envelope_accepted"] = False
    elif mutation == "fault":
        case["fault_envelope_accepted"] = False
    elif mutation == "rating":
        case["plan"]["engine_plans"][0]["candidates"][0]["parameters"]["voltage"] = 500
    elif mutation == "revision":
        case["code_before"]["commit"] = "b" * 40
    elif mutation == "ownership":
        case["cleanup"]["owned_process_cleaned"] = False
    elif mutation == "replay":
        replay["analysis"]["network"]["status"] = "FAIL"
    else:
        replay["portable_copy"]["compiled_artifacts_copied"] = True
    result = verify_suite(records, replay)
    assert result["status"] == "FAIL" and result["model_accepted"] is False


def test_legacy_path_overflow_is_refused_before_workspace_or_vendor_call(tmp_path, monkeypatch):
    from scripts import run_mmc_native_avm_full_acceptance as runner

    root = tmp_path / ("long-acceptance-root-" * 4)
    calls = []
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE", "1")
    monkeypatch.setenv("PSCAD_MCP_NATIVE_AVM_FULL_ACCEPTANCE", "1")
    monkeypatch.setattr(runner.sys, "argv", ["suite", "--workspace-root", str(root)])

    def vendor_call(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("must not launch a vendor process")

    monkeypatch.setattr(runner.subprocess, "run", vendor_call)
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2
    assert calls == []
    assert not root.exists()
