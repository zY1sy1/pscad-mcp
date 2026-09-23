"""Publication recovery checks do not launch or operate PSCAD."""

import asyncio
import copy
import importlib
import json
from types import SimpleNamespace

import pytest


def _module():
    spec = importlib.util.find_spec("tests.mmc_publication_resume")
    assert spec is not None, "The publication-only recovery entry point is missing"
    return importlib.import_module(spec.name)


def _terminal_records():
    replay = {"status": "PASS", "owned_process_cleaned": True, "cleanup_pending": False, "worker_exit_code": 0}
    build = {
        "build_id": "a" * 32, "state": "failed", "run_completed": True,
        "error": {"code": "MMC_BUILD_FAILED", "details": {"exception": "FileNotFoundError"}, "message": "[WinError 206] path too long: publication-candidate"},
        "history": [{"state": state} for state in ("simulated", "outputs_frozen", "evaluated", "verifying_reload", "failed")],
        "containment": {"confirmed": True},
        "result": {"acceptance": {"verdict": "PASS"}, "reload": replay},
    }
    phase = {
        "build": copy.deepcopy(build), "build_id": build["build_id"], "reload": copy.deepcopy(replay),
        "owned_process_cleaned": True, "cleanup_pending": False,
        "builder_cleanup_pending": False, "pending_vendor_calls": [],
        "service_cleanup": {"owned_process_cleaned": True, "cleanup_pending": False},
    }
    coordinator = {
        "scope": "public_and_joint_mmc", "status": "FAIL",
        "history": ["preflight", "public_closed", "finalizing", "finished"],
        "owned_process_cleaned": True, "cleanup_pending": False,
        "lease_retained": False, "finalization_errors": [],
        "error": {"code": "MMC_PUBLIC_ACCEPTANCE_FAILED"}, "public": phase,
    }
    return coordinator, build


@pytest.mark.parametrize("changed", [None, "unfinished", "coordinator_cleanup", "lease", "finalization", "joint_started", "wrong_failure", "build_incomplete", "build_lease", "build_vendor_calls", "build_cleanup", "public_physics", "replay_physics", "replay_cleanup", "build_snapshot"])
def test_publication_recovery_requires_closed_attempt_and_exact_publication_failure(changed):
    coordinator, build = _terminal_records()
    if changed == "unfinished":
        coordinator["history"].pop()
    elif changed == "coordinator_cleanup":
        coordinator["cleanup_pending"] = True
    elif changed == "lease":
        coordinator["lease_retained"] = True
    elif changed == "finalization":
        coordinator["finalization_errors"] = [{"stage": "lease_release"}]
    elif changed == "joint_started":
        coordinator["joint"] = {"status": "FAIL"}
    elif changed == "wrong_failure":
        build["error"]["message"] = "Native fault compilation failed"
    elif changed == "build_incomplete":
        build["run_completed"] = False
    elif changed == "build_lease":
        build["lease_retained"] = True
    elif changed == "build_vendor_calls":
        build["pending_vendor_calls"] = 1
    elif changed == "build_cleanup":
        build["cleanup_pending"] = True
    elif changed == "public_physics":
        build["result"]["acceptance"]["verdict"] = "FAIL"
    elif changed == "replay_physics":
        build["result"]["reload"]["status"] = "FAIL"
    elif changed == "replay_cleanup":
        build["result"]["reload"]["cleanup_pending"] = True
    elif changed == "build_snapshot":
        coordinator["public"]["build"]["build_id"] = "b" * 32
    if changed and changed != "build_snapshot":
        coordinator["public"]["build"] = copy.deepcopy(build)
        coordinator["public"]["reload"] = copy.deepcopy(build["result"]["reload"])
    if changed is None:
        assert _module()._validate_terminal_records(coordinator, build) is True
    else:
        with pytest.raises(ValueError):
            _module()._validate_terminal_records(coordinator, build)


@pytest.mark.parametrize("changed", [None, "threshold", "execution", "global"])
def test_historical_code_compatibility_permits_only_reviewed_publication_changes(changed):
    before = '''LIMIT = 20.0
def _materialize_native_mmc_case():
    return LIMIT
def _native_replay_workspace():
    return "old paths"
def _publish_tested_fault_case():
    return "old publication"
async def _execute_native_mmc_plan():
    contract = materialize()
    result = _publish_tested_fault_case(plan, project, bundle, contract, record, replay_workspace=replay_workspace)
    return result
'''
    after = before.replace('return "old paths"', 'return "reviewed path helper"').replace('return "old publication"', 'return "new publication"')
    after = after.replace('    contract = materialize()', '''    publication_workspace = _native_attempt_workspace(plan, workspace, build_id, "mmc-publications")
    record["result"]["publication_workspace"] = str(publication_workspace)
    contract = materialize()''')
    after = after.replace('replay_workspace=replay_workspace)', 'replay_workspace=replay_workspace, publication_workspace=publication_workspace)')
    after += '\ndef _native_attempt_workspace():\n    return "reviewed new helper"\n'
    after += '\ndef _preflight_publication_layout():\n    return "reviewed length guard"\n'
    if changed == "threshold":
        after = after.replace('return LIMIT', 'return 9999.0')
    elif changed == "execution":
        after = after.replace('contract = materialize()', 'contract = unchecked_model()')
    elif changed == "global":
        after = after.replace('LIMIT = 20.0', 'LIMIT = 9999.0')
    if changed is None:
        assert _module()._verify_shared_model_logic(before, after) is True
    else:
        with pytest.raises(ValueError, match="shared model"):
            _module()._verify_shared_model_logic(before, after)


def test_historical_snapshot_must_match_exact_recorded_bytes_and_git_source(tmp_path):
    module = _module()
    snapshot = tmp_path / "historical.py"
    snapshot.write_bytes(b"first\r\nsecond\n")
    identity = {"path": "original/blank_service.py", "sha256": module.blank_service._sha256(snapshot)}
    assert module._verify_historical_snapshot(identity, snapshot, b"first\nsecond\n")["sha256"] == identity["sha256"]
    with pytest.raises(ValueError):
        module._verify_historical_snapshot(identity, snapshot, b"different\n")
    snapshot.write_bytes(b"first\nsecond\n")
    with pytest.raises(ValueError):
        module._verify_historical_snapshot(identity, snapshot, b"first\nsecond\n")


@pytest.mark.parametrize("changed_window", [False, True])
def test_physical_revalidation_compares_complete_json_contract_including_windows(monkeypatch, changed_window):
    module = _module()
    archived = {"channels": [{"values": [1.0]}], "identity": {"primary": "case.out", "started_after": 1}}
    expected = {"verdict": "PASS", "check_results": [{"name": "physical_check", "window": [2.5, 2.7], "observed": 1.0}]}
    observed = copy.deepcopy(expected)
    observed["check_results"][0]["window"] = (2.5, 2.8 if changed_window else 2.7)

    async def read(*args, **kwargs):
        return copy.deepcopy(archived)

    monkeypatch.setattr(module, "_reader", lambda: None)
    monkeypatch.setattr(module.blank_service, "read_fault_output_dataset", read)
    monkeypatch.setattr(module.blank_service, "evaluate_template_native_dc_fault", lambda *args, **kwargs: observed)
    monkeypatch.setattr(module.blank_service, "verify_output_dataset", lambda _: None)
    context = {"plan": {"checks_contract": {"fault_current_limit_ka": 20.0}, "request": {"submodule_topology": "full_bridge"}}, "cases": {"public": {"index": archived["identity"], "contract": {}, "archived": archived, "acceptance": expected}}, "ledger": SimpleNamespace(recheck=lambda: None)}
    if changed_window:
        with pytest.raises(ValueError, match="physical evaluation"):
            asyncio.run(module.reevaluate_completed_cases(context))
    else:
        assert asyncio.run(module.reevaluate_completed_cases(context))["public"]["verdict"] == "PASS"


@pytest.mark.parametrize("failure", [None, "checkpoint", "lease", "lease_false", "final_write", "all_writes"])
def test_recovery_finalizer_releases_leases_and_cannot_persist_pass_after_failure(failure):
    module = _module()
    events, persisted = [], []

    class Lease:
        token = "owned"

        def release(self, token):
            assert token == self.token
            events.append("release")
            if failure == "lease":
                raise OSError("release failed")
            return failure != "lease_false"

    class Journal:
        calls = 0

        def write(self, report):
            self.calls += 1
            events.append("write:" + report["status"])
            if failure == "all_writes" or failure == "checkpoint" and self.calls == 1 or failure == "final_write" and self.calls == 2:
                raise OSError("journal failed")
            persisted.append(copy.deepcopy(report))

    report = {"status": "PASS", "history": [], "lease_retained": True}
    module._finalize_recovery(report, [Lease()], Journal(), True)
    assert "release" in events
    assert events[0] == "write:FAIL"
    assert report["lease_retained"] is (failure in {"lease", "lease_false"})
    assert report["status"] == ("PASS" if failure is None else "FAIL")
    if failure:
        assert all(item["status"] != "PASS" for item in persisted)
    else:
        assert persisted[-1]["status"] == "PASS"
    if failure is None:
        assert events.index("release") < events.index("write:PASS")


def test_recovery_ledger_rechecks_inputs_and_rejects_conflicting_identities(tmp_path):
    module = _module()
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps({"frozen": True}))
    digest = module.blank_service._sha256(path)
    ledger = module._Ledger()
    assert ledger.read(path, digest) == {"frozen": True}
    path.write_text(json.dumps({"frozen": False}))
    with pytest.raises(ValueError, match="changed"):
        ledger.recheck()
    with pytest.raises(ValueError, match="conflicting"):
        ledger.check(path, module.blank_service._sha256(path))


@pytest.mark.parametrize("changed", ["status", "scope", "unfinished", "pending_lease", "launched_pscad", "error"])
def test_joint_intake_rejects_incomplete_recovery_receipts_before_evidence_reads(tmp_path, changed):
    module = _module()
    receipt = {"schema_version": 1, "scope": "public_mmc_publication_recovery", "status": "PASS", "history": ["finished"], "lease_retained": False, "pscad_launched": False}
    if changed in ("status", "scope"):
        receipt[changed] = "FAIL"
    elif changed == "unfinished":
        receipt["history"] = ["finalizing"]
    elif changed == "pending_lease":
        receipt["lease_retained"] = True
    elif changed == "launched_pscad":
        receipt["pscad_launched"] = True
    else:
        receipt["error"] = {"message": "failed"}
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        asyncio.run(module.validate_publication_recovery({"path": str(path), "sha256": module.blank_service._sha256(path)}))


@pytest.mark.parametrize("replace_handoff", [False, True])
def test_recovery_receipt_b_handoff_must_match_original_coordinator_and_request(tmp_path, replace_handoff):
    module = _module()

    def write(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return {"path": str(path), "sha256": module.blank_service._sha256(path)}

    original = write("b-original.json", {"accepted": True})
    other = write("b-unrelated.json", {"accepted": True})
    coordinator, build = _terminal_records()
    build["plan"] = {"immutable": "original-plan"}
    coordinator["public"]["build"] = copy.deepcopy(build)
    coordinator["public_plan"] = build["plan"]
    coordinator["root"] = str(tmp_path)
    coordinator["b_handoff"] = {"file": original}
    coordinator["request_sha256"] = write("request.json", {"b_handoff": original, "public_plan": build["plan"]})["sha256"]
    receipt = {"source_attempt": {"coordinator": write("coordinator.json", coordinator), "public_build": write("build.json", build)}, "b_handoff": other if replace_handoff else original}
    if replace_handoff:
        with pytest.raises(ValueError, match="B handoff"):
            module._validate_recovery_sources(receipt, module._Ledger())
    else:
        assert module._validate_recovery_sources(receipt, module._Ledger()) == (coordinator, build)
