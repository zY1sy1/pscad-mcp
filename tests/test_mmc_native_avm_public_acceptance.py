from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest
from pscad_mcp.core.backend.base import BackendError


@pytest.fixture
def runner():
    return importlib.import_module("scripts.run_mmc_native_avm_public_acceptance")


def test_public_runner_requires_its_explicit_optin(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE", "1")
    monkeypatch.delenv("PSCAD_MCP_NATIVE_AVM_PUBLIC_ACCEPTANCE", raising=False)
    with pytest.raises(PermissionError, match="NATIVE_AVM_PUBLIC"):
        asyncio.run(runner.run_attempt(SimpleNamespace(), tmp_path / "unused"))
    assert not (tmp_path / "unused").exists()


def test_public_runner_cannot_claim_complete_model_acceptance(runner):
    assert runner.SCOPE == "public_native_cable_avm_assembly"
    source = runner.Path(runner.__file__).read_text(encoding="utf-8")
    assert 'report["model_accepted"] = False' in source
    assert "fault and portable reload acceptance remain pending" in source


def test_public_plan_gate_requires_native_hashes_and_conservative_capabilities(runner):
    sources = {"master": "a" * 64, "cable_donor": "b" * 64, "tline": "c" * 64}
    child = {
        "engine": "average_value",
        "source_hashes": sources,
        "capabilities": {
            "native_physical_assembly": True,
            "native_cable_constants": True,
            "control_kind": "closed_loop",
            "model_accepted": False,
        },
    }
    assert runner._require_public_plan({"engine_plans": [child]}, sources) is child
    for mutation in ("hash", "native", "accepted"):
        changed = {**child, "capabilities": dict(child["capabilities"])}
        if mutation == "hash":
            changed["source_hashes"] = {**sources, "master": "d" * 64}
        elif mutation == "native":
            changed["capabilities"]["native_physical_assembly"] = False
        else:
            changed["capabilities"]["model_accepted"] = True
        with pytest.raises(ValueError):
            runner._require_public_plan({"engine_plans": [changed]}, sources)


def test_interrupted_runtime_is_rejected_before_a_precharge_verdict(runner):
    with pytest.raises(BackendError) as raised:
        runner._require_complete_trace({"time": [0.0, 0.0901]}, {"output_step_s": 0.0001, "simulation_duration_s": 3.9})
    assert raised.value.code == "MMC_RUN_INCOMPLETE"
    assert runner._public_failure_category("read_and_analyze", raised.value, []) == "process_or_runtime"
    assert runner._public_failure_category("run", ValueError("runtime"), [{"text": "WinSock Error #10048"}]) == "environment_contention"
    runner._require_complete_trace({"time": [0.0, 3.9]}, {"output_step_s": 0.0001, "simulation_duration_s": 3.9})
