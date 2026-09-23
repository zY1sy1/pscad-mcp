"""Focused protocol tests; no licensed PSCAD process is started."""

import asyncio
import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _module():
    spec = importlib.util.find_spec("tests.mmc_joint_replay_resume")
    assert spec is not None, "The independent joint replay recovery runner is missing"
    return importlib.import_module(spec.name)


def _closed_records():
    worker = {
        "schema_version": 1, "status": "FAIL", "owned_process_cleaned": True,
        "cleanup_pending": False, "pending_vendor_calls": [],
        "history": [{"stage": "frozen_copy_verified"}],
        "error": {"type": "ValueError", "message": "The replay saved model differs beyond the verified virtual document root and vendor save metadata"},
        "result": {"channel_contract_path": "channels.json", "tested_project_sha256": "a" * 64},
    }
    phase = {
        "status": "FAIL", "owned_process_cleaned": True, "cleanup_pending": False,
        "pending_vendor_calls": [], "run_completed": True,
        "history": ["saved_and_bound", "compiled", "running", "simulated", "outputs_frozen"],
        "analysis": {"verdict": "PASS", "fault": {"verdict": "PASS", "check_results": [{"status": "PASS"}]}, "timing": {"measured_events": [1, 2]}},
        "service_cleanup": {"owned_process_cleaned": True, "cleanup_pending": False},
        "reload": {"status": "FAIL", "owned_process_cleaned": True, "cleanup_pending": False, "worker_exit_code": 1, "error": copy.deepcopy(worker["error"])},
    }
    report = {
        "schema_version": 1, "scope": "fresh_joint_after_publication", "status": "FAIL",
        "history": ["joint_replay_requested", "joint_closed", "finalizing", "finished"],
        "owned_process_cleaned": True, "cleanup_pending": False, "lease_retained": False,
        "finalization_errors": [], "error": {"code": "MMC_JOINT_ACCEPTANCE_FAILED"}, "joint": phase,
    }
    return report, worker


@pytest.mark.parametrize("change", [None, "unfinished", "lease", "outer_cleanup", "physical", "timing", "worker_cleanup", "worker_started", "worker_compiled", "wrong_error", "output_evidence", "pending_calls"])
def test_only_the_closed_saved_model_replay_failure_is_resumable(change):
    report, worker = _closed_records()
    if change == "unfinished":
        report["history"].pop()
    elif change == "lease":
        report["lease_retained"] = True
    elif change == "outer_cleanup":
        report["joint"]["cleanup_pending"] = True
    elif change == "physical":
        report["joint"]["analysis"]["fault"]["verdict"] = "FAIL"
    elif change == "timing":
        report["joint"]["analysis"]["timing"]["measured_events"] = []
    elif change == "worker_cleanup":
        worker["owned_process_cleaned"] = False
    elif change == "worker_started":
        worker["run_started"] = True
    elif change == "worker_compiled":
        worker["history"].append({"stage": "compiled"})
    elif change == "wrong_error":
        worker["error"]["message"] = "Physical checks failed"
    elif change == "output_evidence":
        worker["result"]["output_index_path"] = "outputs.json"
    elif change == "pending_calls":
        worker["pending_vendor_calls"] = [{"operation": "save"}]
    if change is None:
        assert _module()._validate_closed_failure(report, worker) is True
    else:
        with pytest.raises(ValueError):
            _module()._validate_closed_failure(report, worker)


@pytest.mark.parametrize("change", [None, "comparison", "helper_call", "other_function", "extra_call"])
def test_native_code_compatibility_allows_only_the_reviewed_hierarchy_change(change):
    before = '''def _verify_saved_model_roots(before, after, contract):
    _normalize_new_sticky_styles(before, after)
    return canonical(before) == canonical(after)
def worker():
    return "fixed worker"
'''
    after = before.replace('    _normalize_new_sticky_styles(before, after)', '    _normalize_new_sticky_styles(before, after)\n    _normalize_hierarchy_call_order(before, after)')
    after += '\ndef _normalize_hierarchy_call_order(before, after):\n    return "reviewed helper"\n'
    if change == "comparison":
        after = after.replace('canonical(before) == canonical(after)', 'True')
    elif change == "helper_call":
        after = after.replace('_normalize_hierarchy_call_order(before, after)\n', '_normalize_hierarchy_call_order(after, before)\n', 1)
    elif change == "other_function":
        after = after.replace('"fixed worker"', '"different worker"')
    elif change == "extra_call":
        after += '\n_normalize_hierarchy_call_order(before, after)\n'
    if change is None:
        assert _module()._verify_native_code_change(before, after) is True
    else:
        with pytest.raises(ValueError):
            _module()._verify_native_code_change(before, after)


@pytest.mark.parametrize("failure", [None, "pending", "false_release", "release_error", "checkpoint_error", "final_write_error"])
def test_finalizer_retains_pending_replay_and_requires_true_lease_release(failure):
    module = _module()
    calls, persisted = [], []

    class Lease:
        token = "owned"

        def release(self, token):
            assert token == self.token
            calls.append("release")
            if failure == "release_error":
                raise OSError("cannot release")
            return failure != "false_release"

    class Journal:
        count = 0

        def write(self, value):
            self.count += 1
            if failure == "checkpoint_error" and self.count == 1 or failure == "final_write_error" and self.count == 2:
                raise OSError("cannot write")
            persisted.append(copy.deepcopy(value))

    report = {"status": "FAIL", "history": [], "cleanup_pending": failure == "pending", "owned_process_cleaned": failure != "pending", "physical_acceptance_verified": False}
    module._finalize_replay(report, [Lease()], Journal(), True)
    assert calls == ([] if failure == "pending" else ["release"])
    assert report["status"] == ("PASS" if failure is None else "FAIL")
    assert report["physical_acceptance_verified"] is (failure is None)
    assert report["lease_retained"] is (failure in {"pending", "false_release", "release_error"})
    assert persisted[-1]["status"] == report["status"]


def test_missing_license_opt_in_never_loads_first_dataset_or_starts_replay(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.delenv("PSCAD_MCP_MMC_ACCEPTANCE", raising=False)
    old_root = tmp_path / "old"
    old_root.mkdir()
    old_report = old_root / "report.json"
    old_report.write_text(json.dumps({"root": str(old_root)}))
    ref = {"path": str(old_report), "sha256": module.blank_service._sha256(old_report)}
    calls = []
    monkeypatch.setattr(module, "load_previous_joint", lambda *_: calls.append("load"))
    monkeypatch.setattr(module.lifecycle, "run_joint_replay", lambda *_: calls.append("replay"))
    result = asyncio.run(module.resume_joint_replay(ref, tmp_path / "new"))
    assert result["status"] == "FAIL"
    assert result["error"]["code"] == "MMC_ACCEPTANCE_OPT_IN_REQUIRED"
    assert result["owned_process_cleaned"] is True
    assert calls == []


def test_archived_first_run_is_reevaluated_with_independent_same_dataset_timing(monkeypatch):
    module = _module()
    fault = {"verdict": "PASS", "check_results": [{"status": "PASS", "window": [2.5, 2.7]}]}
    timing = {"measured_events": [1.0, 1.2]}
    calls = []
    monkeypatch.setattr(module.blank_service, "evaluate_template_native_dc_fault", lambda *args, **kwargs: {**fault, "check_results": [{"status": "PASS", "window": (2.5, 2.7)}]})
    monkeypatch.setattr(module.lifecycle.timed_control, "read_event_evidence", lambda *args, **kwargs: calls.append("timing") or timing)
    monkeypatch.setattr(module.lifecycle, "require_same_dataset", lambda *args: calls.append("same_dataset"))
    monkeypatch.setattr(module.lifecycle, "verify_output_dataset", lambda *_: None)
    monkeypatch.setattr(module.lifecycle, "verify_joint_preparation", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.lifecycle, "evaluate_joint_dataset", lambda *_: pytest.fail("must not write old analysis evidence"))
    context = {"preparation": {"project": {"path": "case.pscx"}, "schedule": {}, "checks": {"fault_current_limit_ka": 20.0}}, "contract": {}, "index": {"files": {"case_01.out": {"path": "case_01.out"}}, "started_after": 1}, "samples": {"channels": []}, "analysis": {"fault": fault, "timing": timing}, "ledger": SimpleNamespace(recheck=lambda: None)}
    assert module.revalidate_first_run(context)["verdict"] == "PASS"
    assert calls == ["timing", "same_dataset"]


@pytest.mark.parametrize("outcome", ["pass", "raised", "pending", "bad_lineage", "wrong_dataset", "release_false", "checkpoint_error"])
def test_runner_runs_only_one_new_replay_and_preserves_pending_ownership(tmp_path, monkeypatch, outcome):
    module = _module()
    monkeypatch.setenv("PSCAD_MCP_MMC_ACCEPTANCE", "1")
    old_root = tmp_path / "old"
    old_root.mkdir()
    old_report = old_root / "report.json"
    old_report.write_text(json.dumps({"root": str(old_root)}))
    previous = {"path": str(old_report), "sha256": module.blank_service._sha256(old_report)}
    first_model = {"path": str(old_root / "JointFaultCase.pscx"), "sha256": "a" * 64}
    preparation = {"project": first_model, "checks_sha256": "c" * 64, "public_plan": {"line_constants": {"inputs": []}}}
    contract, replay_context = {"frozen": "first-contract"}, {"frozen": "joint-context"}
    calls = []
    context = {
        "preparation": preparation, "contract": contract, "b_ref": {"path": "B.json", "sha256": "b" * 64},
        "provenance": {"fixture": "already checked"}, "replay_context": replay_context,
        "previous_report": {"joint_preparation": {"path": "old-prepare.json", "sha256": "d" * 64}, "joint": {"first_saved_model": first_model, "first_saved_snapshot": first_model}},
        "ledger": SimpleNamespace(files={}, recheck=lambda: calls.append("recheck")),
    }
    original_preparation = copy.deepcopy(preparation)
    monkeypatch.setattr(module, "load_previous_joint", lambda *_: context)
    monkeypatch.setattr(module, "_verify_committed_execution", lambda *_: None)
    monkeypatch.setattr(module, "revalidate_first_run", lambda *_: calls.append("first_revalidation") or {"verdict": "PASS"})
    monkeypatch.setattr(module.lifecycle, "verify_output_dataset", lambda *_: None)
    monkeypatch.setattr(module.lifecycle, "verify_joint_preparation", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.lifecycle, "_run_joint", lambda *_: pytest.fail("must not rerun the first model"))
    if outcome == "checkpoint_error":
        write = module.AtomicJournal.write

        def interrupted_checkpoint(journal, report):
            if report["history"][-1] == "fresh_replay_requested":
                raise OSError("pending checkpoint could not be persisted")
            return write(journal, report)

        monkeypatch.setattr(module.AtomicJournal, "write", interrupted_checkpoint)

    class Lease:
        token = "owned"

        def release(self, token):
            calls.append("release")
            return outcome != "release_false"

    monkeypatch.setattr(module.WorkspaceBuildLease, "acquire", lambda *_: Lease())

    async def replay(observed_preparation, observed_contract, b_ref, workspace):
        calls.append("replay")
        assert observed_preparation == original_preparation and observed_contract == contract
        assert workspace == tmp_path / "new/replay"
        if outcome == "raised":
            raise OSError("worker connection outcome is uncertain")
        identity = {"fixture": "fresh output"}
        return {
            "status": "FAIL" if outcome == "pending" else "PASS",
            "owned_process_cleaned": outcome != "pending", "cleanup_pending": outcome == "pending", "worker_exit_code": 0,
            "project_sha256": "wrong" if outcome == "bad_lineage" else first_model["sha256"],
            "checks_sha256": preparation["checks_sha256"], "parent_channel_contract_sha256": module.lifecycle._digest(contract),
            "verification_context_sha256": module.lifecycle._digest(replay_context),
            "acceptance": {"verdict": "PASS"}, "supplemental_saved_validation": {"verdict": "PASS"},
            "supplemental_evidence": {"verdict": "PASS", "output_identity": {"other": "dataset"} if outcome == "wrong_dataset" else identity},
            "output_identity": identity,
        }

    monkeypatch.setattr(module.lifecycle, "run_joint_replay", replay)
    result = asyncio.run(module.resume_joint_replay(previous, tmp_path / "new"))
    assert calls.count("replay") == (0 if outcome == "checkpoint_error" else 1)
    if outcome != "checkpoint_error":
        assert calls.index("first_revalidation") < calls.index("replay")
    assert preparation == original_preparation
    assert module.blank_service._sha256(old_report) == previous["sha256"]
    assert result["status"] == ("PASS" if outcome == "pass" else "FAIL")
    assert result["physical_acceptance_verified"] is (outcome == "pass")
    assert result["cleanup_pending"] is (outcome in {"pending", "raised"})
    assert result["lease_retained"] is (outcome in {"pending", "raised", "release_false"})
    assert ("release" in calls) is (outcome not in {"pending", "raised"})


def test_new_workspace_cannot_touch_previous_evidence_or_frozen_source_tree(tmp_path):
    module = _module()
    old_root = tmp_path / "old"
    old_root.mkdir()
    source = tmp_path / "frozen-source"
    prep = old_root / "preparation.json"
    prep.write_text(json.dumps({"code_identities": [{"path": str(source / "pscad_mcp/producer.py"), "sha256": "a" * 64}]}))
    parent = old_root / "report.json"
    parent.write_text(json.dumps({"root": str(old_root), "joint_preparation": {"path": str(prep), "sha256": module.blank_service._sha256(prep)}}))
    ref = {"path": str(parent), "sha256": module.blank_service._sha256(parent)}
    for candidate in (old_root / "new", source / "new"):
        with pytest.raises(ValueError, match="overlaps"):
            module._workspace_root(candidate, ref)
        assert not candidate.exists()


@pytest.mark.parametrize("protected", ["published_bundle", "recovery_root", "public_attempt"])
def test_new_workspace_cannot_pollute_any_publication_input_tree(tmp_path, protected):
    module = _module()

    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return {"path": str(path), "sha256": module.blank_service._sha256(path)}

    old_public = tmp_path / "old-public"
    public_ref = write(old_public / "report.json", {"root": str(old_public)})
    recovery = tmp_path / "recovery"
    published_project = tmp_path / "published/Case.pscx"
    published_bundle = published_project.with_suffix(".bundle")
    manifest = write(published_bundle / "manifest.json", {"frozen": True})
    receipt = write(recovery / "report.json", {"source_attempt": {"coordinator": public_ref}, "published_project": {"path": str(published_project), "sha256": "a" * 64}})
    old_joint = tmp_path / "old-joint"
    previous = write(old_joint / "report.json", {"root": str(old_joint), "publication_receipt": receipt})
    destination = {"published_bundle": published_bundle, "recovery_root": recovery, "public_attempt": old_public}[protected] / "new-run"
    with pytest.raises(ValueError, match="overlaps"):
        module._workspace_root(destination, previous)
    assert not destination.exists()
    assert module.blank_service._sha256(Path(manifest["path"])) == manifest["sha256"]
