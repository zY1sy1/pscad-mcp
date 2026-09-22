"""Software-only continuation gates; these fixtures establish no licensed PASS."""

import asyncio
import copy
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pscad_mcp.hvdc.builders.mmc.blank_service import _recipe_contract
from pscad_mcp.hvdc.builders.mmc.fault_channels import (
    default_fault_checks,
    snapshot_output_dataset,
)


def _module():
    spec = importlib.util.find_spec("tests.mmc_joint_after_publication")
    assert spec is not None, "The fresh joint continuation runner is missing"
    return importlib.import_module(spec.name)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_license_opt_in_precedes_receipt_verification_and_service(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.delenv("PSCAD_MCP_MMC_ACCEPTANCE", raising=False)
    calls = []

    async def unexpected(_):
        calls.append("receipt")
        raise AssertionError("No receipt operation is permitted before opt-in")

    monkeypatch.setattr(module.publication, "validate_publication_recovery", unexpected)
    result = asyncio.run(module.run_joint_after_publication({}, {}, tmp_path / "run", service_factory=lambda _: calls.append("service")))
    assert result["status"] == "FAIL"
    assert result["error"]["code"] == "MMC_ACCEPTANCE_OPT_IN_REQUIRED"
    assert result["physical_acceptance_verified"] is False
    assert result["owned_process_cleaned"] is True
    assert calls == []
    assert json.loads(Path(result["report_path"]).read_text())["status"] == "FAIL"


@pytest.fixture
def continuation(tmp_path, monkeypatch):
    module = _module()
    lifecycle = module.lifecycle
    monkeypatch.setenv("PSCAD_MCP_MMC_ACCEPTANCE", "1")
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "original-value")
    calls = []
    faults = {}
    sources = {name: _write(tmp_path / "source" / (name + ".json"), {"source": name}) for name in ("project", "library", "master")}
    receipt = _write(tmp_path / "recovery" / "receipt.json", {"scope": "public_mmc_publication_recovery", "status": "PASS", "fixture": "synthetic"})
    b_ref = _write(tmp_path / "b.json", {"fixture": "accepted B proof is a prerequisite only"})
    recipe = _recipe_contract("native_full_sort_dc_integral_004_v1")
    accepted = {"file": b_ref, "source_hashes": sources, "recipe": {"id": recipe["name"], "parameters": recipe["parameters"], "steps": recipe["steps"]}}
    old_plan = {"source_identities": sources, "model_recipe": copy.deepcopy(recipe)}
    old_plan["model_recipe"]["producer_code_hashes"] = {"blank_service": {"path": "historical", "sha256": "a" * 64}}
    published = {
        "receipt": receipt,
        "project": _write(tmp_path / "published" / "Public.pscx", {"fixture": "published project"}),
        "manifest": _write(tmp_path / "published" / "Public.manifest.json", {"fixture": "published manifest"}),
        "plan": old_plan,
        "b_handoff": b_ref,
        "validation": {"accepted": True},
    }

    async def validate_publication(reference):
        calls.append("receipt")
        assert reference == receipt
        if faults.get("receipt_error") or (faults.get("receipt_after_close") and calls.count("receipt") > 1):
            raise ValueError("Publication recovery validation failed")
        return copy.deepcopy(published)

    async def validate_b(path):
        calls.append("b")
        assert Path(path) == Path(b_ref["path"])
        if faults.get("b_error"):
            raise ValueError("B proof rejected")
        return copy.deepcopy(accepted)

    async def prepare(root, **kwargs):
        calls.append("prepare")
        assert kwargs == {"source": sources["project"]["path"], "library": sources["library"]["path"], "master": sources["master"]["path"], "model_recipe": recipe["name"]}
        root = Path(root)
        assert not root.exists()
        project = _write(root / "JointFaultCase.pscx", {"fixture": "fresh current preparation"})
        return {"schema_version": 1, "status": "PASS", "project": project, "joint_parents": {"B": {"accepted": False}}, "fault_contract": {}, "checks": default_fault_checks(), "public_plan": {"source_identities": copy.deepcopy(sources), "model_recipe": copy.deepcopy(recipe), "settings": {"simulation_duration_s": 5.0, "time_step_s": 25e-6, "output_step_s": 250e-6}}}

    def verify_preparation(preparation, **kwargs):
        calls.append("verify_preparation")
        if faults.get("stale_preparation"):
            raise ValueError("A frozen joint code or model input changed")
        assert preparation["public_plan"]["model_recipe"]["producer_code_hashes"] == recipe["producer_code_hashes"]
        return True

    class Service:
        def __init__(self, root):
            calls.append("service")
            self.root = Path(root)

        async def attach_local(self):
            calls.append("attach")
            if faults.get("attach_error"):
                raise RuntimeError("Synthetic attach failure")

        async def status(self):
            return {"fixture": "synthetic owned runtime"}

        async def read_output_file(self, *args, **kwargs):
            raise AssertionError("The software fixture must not read licensed waveforms")

    async def close_owned(service, ownership, phase):
        calls.append("close")
        pending = faults.get("cleanup_pending", False)
        phase.update({"owned_process_cleaned": not pending, "cleanup_pending": pending})
        if faults.get("model_close_drift"):
            (service.root / "JointFaultCase.pscx").write_text("changed", encoding="utf-8")

    async def master(*args):
        return sources["master"]

    async def run_case(service, project, library, contract, checks, settings, evidence, phase, checkpoint):
        calls.append("fresh_joint")
        if faults.get("joint_failure"):
            raise ValueError("Fresh joint physics failed")
        ref = _write(evidence / "channels.json", {"fixture": "saved joint contract"})
        phase["result"].update({"channel_contract_path": ref["path"], "channel_contract_sha256": ref["sha256"]})
        checkpoint("saved_and_bound")
        out = project.with_name(project.stem + "_01.out")
        out.write_text("0 0\n5 0\n", encoding="utf-8")
        out.with_name(project.stem + ".inf").write_text("synthetic INF", encoding="utf-8")
        out.with_name(project.stem + ".infx").write_text("synthetic INFX", encoding="utf-8")
        return {"fixture": "saved joint contract"}, {"identity": snapshot_output_dataset(out)}

    async def analyze(*args):
        return {"verdict": "FAIL" if faults.get("joint_analysis") else "PASS", "fixture": "synthetic"}

    async def replay(*args):
        calls.append("fixed_joint_replay")
        if faults.get("replay_exception"):
            raise RuntimeError("Replay cleanup is unconfirmed")
        return {"status": "FAIL" if faults.get("replay_failure") else "PASS", "owned_process_cleaned": not faults.get("replay_pending", False), "cleanup_pending": faults.get("replay_pending", False)}

    monkeypatch.setattr(module.publication, "validate_publication_recovery", validate_publication)
    monkeypatch.setattr(lifecycle, "_validate_b", validate_b)
    monkeypatch.setattr(lifecycle, "prepare_joint_case", prepare)
    monkeypatch.setattr(lifecycle, "verify_joint_preparation", verify_preparation)
    monkeypatch.setattr(lifecycle, "_verify_runtime_master", master)
    monkeypatch.setattr(lifecycle.native_fault_replay, "_capture_ownership", lambda service, request: {"pid": 123, "created_at": 42.0, "request_sha256": request})
    monkeypatch.setattr(lifecycle, "_close_owned_service", close_owned)
    monkeypatch.setattr(lifecycle, "_run_native_fault_case", run_case)
    monkeypatch.setattr(lifecycle, "evaluate_joint_dataset", analyze)
    monkeypatch.setattr(lifecycle, "run_joint_replay", replay)
    return SimpleNamespace(module=module, calls=calls, faults=faults, receipt=receipt, b_ref=b_ref, published=published, accepted=accepted, service=Service, root=tmp_path / "new-joint")


@pytest.mark.parametrize("failure", [None, "receipt_error", "b_error", "stale_preparation", "attach_error", "joint_failure", "joint_analysis", "replay_failure", "replay_exception", "replay_pending", "cleanup_pending", "model_close_drift", "receipt_after_close"])
def test_fresh_joint_uses_reviewed_lifecycle_and_never_inherits_parent_pass(continuation, failure):
    h = continuation
    if failure:
        h.faults[failure] = True
    result = asyncio.run(h.module.run_joint_after_publication(h.receipt, h.b_ref, h.root, service_factory=h.service))
    assert result["status"] == ("FAIL" if failure else "PASS"), result.get("error")
    assert result["scope"] == "fresh_joint_after_publication"
    assert (h.root / "request.json").is_file() == (failure not in {"receipt_error", "b_error", "stale_preparation"})
    assert h.module.os.environ["PSCAD_MCP_ACCEPTANCE_CONCURRENT"] == "original-value"
    if failure in {"receipt_error", "b_error", "stale_preparation"}:
        assert "service" not in h.calls
    else:
        assert h.calls.index("receipt") < h.calls.index("prepare") < h.calls.index("service")
        assert "close" in h.calls
    if failure is None:
        assert h.calls.count("fresh_joint") == h.calls.count("fixed_joint_replay") == 1
        assert h.calls.index("fresh_joint") < h.calls.index("fixed_joint_replay") < h.calls.index("close")
        assert h.calls[-1] == "receipt"
        assert "public" not in result
        request = json.loads((h.root / "request.json").read_text())
        assert request["publication_receipt"] == h.receipt
        assert request["b_handoff"] == h.b_ref
        assert result["physical_acceptance_verified"] is True
    pending = failure in {"replay_exception", "replay_pending", "cleanup_pending"}
    assert result["cleanup_pending"] is pending
    assert result["lease_retained"] is pending
    assert json.loads(Path(result["report_path"]).read_text())["status"] == result["status"]


@pytest.mark.parametrize("changed", ["receipt_hash", "b_hash", "returned_receipt", "returned_b", "validation", "sources", "recipe"])
def test_receipt_and_b_bindings_cannot_be_replaced_before_launch(continuation, changed):
    h = continuation
    receipt, b_ref = copy.deepcopy(h.receipt), copy.deepcopy(h.b_ref)
    if changed == "receipt_hash":
        receipt["sha256"] = "0" * 64
    elif changed == "b_hash":
        b_ref["sha256"] = "0" * 64
    elif changed == "returned_receipt":
        h.published["receipt"]["sha256"] = "0" * 64
    elif changed == "returned_b":
        h.published["b_handoff"]["sha256"] = "0" * 64
    elif changed == "validation":
        h.published["validation"]["accepted"] = "true"
    elif changed == "sources":
        h.published["plan"]["source_identities"] = {}
    else:
        h.published["plan"]["model_recipe"]["parameters"]["t1_dc_integral_time_s"] = 0.08
    result = asyncio.run(h.module.run_joint_after_publication(receipt, b_ref, h.root, service_factory=h.service))
    assert result["status"] == "FAIL"
    assert "service" not in h.calls and "prepare" not in h.calls


@pytest.mark.parametrize("where", ["original", "receipt", "bundle"])
def test_continuation_rejects_evidence_overlap_before_writing(tmp_path, where):
    module = _module()
    original = tmp_path / "original"
    original.mkdir()
    coordinator = _write(original / "coordinator.json", {"root": str(original)})
    project = _write(tmp_path / "published" / "Case.pscx", {"saved": True})
    bundle = Path(project["path"]).with_suffix(".bundle")
    bundle.mkdir()
    receipt = _write(tmp_path / "recovery" / "receipt.json", {
        "source_attempt": {"coordinator": coordinator}, "published_project": project,
    })
    destinations = {"original": original / "replay" / "new", "receipt": tmp_path / "recovery" / "new", "bundle": bundle / "new"}
    root = destinations[where]
    before = {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = asyncio.run(module.run_joint_after_publication(receipt, {}, root))
    assert result["status"] == "FAIL"
    assert result["error"]["code"] == "MMC_JOINT_WORKSPACE_INVALID"
    assert result["report_path"] is None and not root.exists()
    assert {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_cli_requires_explicit_frozen_parent_hashes(monkeypatch):
    module = _module()
    monkeypatch.setattr("sys.argv", ["mmc_joint_after_publication", "--receipt", "receipt.json", "--handoff", "b.json", "--workspace", "run"])
    with pytest.raises(SystemExit) as raised:
        module.main()
    assert raised.value.code == 2
