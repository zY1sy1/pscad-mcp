"""Independent checks for the existing static research utility."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


def optimizer():
    path = (
        Path(__file__).resolve().parents[1] / "scripts" / "optimize_arrester_energy.py"
    )
    spec = importlib.util.spec_from_file_location("arrester_energy_optimizer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_observed_energy_increments_determine_stage_powers(tmp_path):
    schedule = tmp_path / "schedule.json"
    schedule.write_text(json.dumps({"stage_dwell_ms": [2, 4]}))
    channels = tmp_path / "channels.csv"
    channels.write_text("time_s,E1,E2\n0,0,0\n0.002,4,0\n0.006,8,4\n")
    matrix = optimizer().observed_power_matrix(channels, schedule, 2)
    np.testing.assert_allclose(matrix, [[2, 1], [0, 1]], rtol=0, atol=1e-12)


def test_max_min_schedule_reaches_known_common_energy_without_exceeding_limits(
    tmp_path,
):
    curve = tmp_path / "curve.dat"
    curve.write_text("0.01 0.1 /\n1.0 1.0 /\nENDFILE:\n", encoding="ascii")
    powers = np.asarray([[2.0, 1.0], [0.0, 1.0]])
    result = optimizer().optimize(
        [50, 50], [0, 1], curve, 120, 20, 10, 8, 10, observed_powers=powers
    )
    assert result["predicted_common_floor_kJ"] == pytest.approx(8)
    assert result["predicted_energy_kJ"] == pytest.approx([8, 8])
    assert result["stage_dwell_ms"] == pytest.approx([0, 8])
    assert sum(result["stage_dwell_ms"]) <= 10
    assert result["hard_limit_satisfied"] is True
    assert "Static pre-solver" in result["note"]


def test_invalid_branch_order_is_rejected(tmp_path):
    curve = tmp_path / "curve.dat"
    curve.write_text("0.01 0.1 /\n1.0 1.0 /\nENDFILE:\n", encoding="ascii")
    with pytest.raises(ValueError, match="permutation"):
        optimizer().optimize([50, 50], [0, 0], curve, 120, 20, 10, 8, 10)
