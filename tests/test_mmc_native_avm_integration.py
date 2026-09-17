from __future__ import annotations

import asyncio
import importlib
import math
from types import SimpleNamespace

import pytest

from pscad_mcp.hvdc.builders.mmc.native_bundle import FIXTURE_CHANNELS


@pytest.fixture
def runner():
    return importlib.import_module("scripts.run_mmc_native_avm_integration")


def _trace():
    time = [index * 0.0001 for index in range(5001)]
    sequence = [1.0 if value < 0.1 else 2.0 if value < 0.3 else 3.0 for value in time]
    trace = {
        "time": time,
        "P_VDC": [640.0 * min(1.0, value / 0.08) for value in time],
        "V_VDC": [635.0 * min(1.0, value / 0.08) for value in time],
        "P_A_UPPER_I": [0.1 * math.sin(2 * math.pi * 60 * value) for value in time],
        "P_A_UPPER_W": [3.0 * min(1.0, value / 0.08) for value in time],
        "V_A_UPPER_I": [0.11 * math.sin(2 * math.pi * 60 * value) for value in time],
        "V_A_UPPER_W": [3.1 * min(1.0, value / 0.08) for value in time],
        "P_SEQUENCE": sequence,
        "V_SEQUENCE": sequence,
        "P_P": [800.0] * len(time),
        "P_Q": [20.0] * len(time),
        "P_IDC": [1.25] * len(time),
        "V_P": [-790.0] * len(time),
        "V_Q": [-18.0] * len(time),
        "V_IDC": [-1.24] * len(time),
        "P_ANGLE_COMMAND": [-10.0] * len(time),
        "P_MODULATION_COMMAND": [0.8] * len(time),
        "V_ANGLE_COMMAND": [8.0] * len(time),
        "V_MODULATION_COMMAND": [0.82] * len(time),
    }
    assert set(trace) == {"time", *FIXTURE_CHANNELS}
    return trace


def test_integration_analyzer_accepts_complete_bounded_sequence(runner):
    result = runner.analyze_integration_trace(_trace())
    assert result["status"] == "PASS"
    assert result["measurement_complete"] is True
    assert result["metrics"]["sample_count"] == 5001
    assert result["failed_checks"] == []


@pytest.mark.parametrize("mutation", ["missing", "sequence", "current", "energy", "time", "nan"])
def test_integration_analyzer_rejects_incomplete_or_nonphysical_trace(runner, mutation):
    trace = _trace()
    if mutation == "missing":
        del trace["P_VDC"]
    elif mutation == "sequence":
        trace["P_SEQUENCE"] = [1.0] * len(trace["time"])
    elif mutation == "current":
        trace["V_A_UPPER_I"][3500] = 21.0
    elif mutation == "energy":
        trace["P_A_UPPER_W"][3500] = -0.1
    elif mutation == "time":
        trace["time"][-1] = trace["time"][-2]
    else:
        trace["P_VDC"][3500] = math.nan
    assert runner.analyze_integration_trace(trace)["status"] == "FAIL"


def test_runner_requires_explicit_component_optin_before_creating_runtime(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE", "1")
    monkeypatch.delenv("PSCAD_MCP_NATIVE_AVM_INTEGRATION_ACCEPTANCE", raising=False)
    with pytest.raises(PermissionError, match="NATIVE_AVM_INTEGRATION"):
        asyncio.run(runner.run_attempt(SimpleNamespace(), tmp_path / "unused"))
    assert not (tmp_path / "unused").exists()


def test_runner_scope_cannot_claim_complete_model_acceptance(runner):
    assert runner.SCOPE == "native_two_station_twelve_arm_avm_assembly"
    source = runner.Path(runner.__file__).read_text(encoding="utf-8")
    assert 'report["model_accepted"] = False' in source
    assert "Closed-loop P/Q/Vdc control" in source
