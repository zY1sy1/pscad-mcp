"""Safety and independent arithmetic contracts for the licensed recovery gate."""

from types import SimpleNamespace

import pytest

from scripts import run_sweep_recovery_acceptance as gate


def test_recovery_gate_requires_explicit_optin_before_creating_anything(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("PSCAD_MCP_ACCEPTANCE", raising=False)
    with pytest.raises(RuntimeError, match="PSCAD_MCP_ACCEPTANCE=1"):
        gate.run_acceptance(tmp_path, tmp_path / "request.json")
    assert not list(tmp_path.iterdir())


def test_orphan_cleanup_refuses_reused_pid_or_foreign_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "process_alive", lambda identity: True)
    for created, exe, name in [
        (2, "pscad.exe", "PSCAD.exe"),
        (1, "other.exe", "PSCAD.exe"),
        (1, "pscad.exe", "other.exe"),
    ]:
        monkeypatch.setattr(
            gate.psutil,
            "Process",
            lambda pid, created=created, exe=exe, name=name: SimpleNamespace(
                create_time=lambda: created, exe=lambda: exe, name=lambda: name
            ),
        )
        with pytest.raises(RuntimeError, match="identity or executable"):
            gate.terminate_owned_instance(
                {"vendor_pid": 123, "create_time": 1, "exe": "pscad.exe"}, tmp_path
            )


def test_independent_simpson_calculator_matches_analytic_quadratic():
    assert gate.independent_integral(
        [0, 0.25, 1], [0, 0.25, 1], [0, 0.25, 1]
    ) == pytest.approx(1 / 3)
