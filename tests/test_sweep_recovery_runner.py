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


def test_owned_attempt_work_is_a_directory_not_a_required_output_file(tmp_path):
    directory = tmp_path / "attempts/scenario/attempt-1/work"
    directory.mkdir(parents=True)
    assert (
        gate.attempt_work_directory(tmp_path, {"path": "attempts/scenario/attempt-1"})
        == directory
    )


@pytest.mark.parametrize("kind", ["missing", "file", "escape"])
def test_owned_attempt_directory_rejects_missing_files_and_escape(tmp_path, kind):
    from pscad_mcp.core.backend.base import BackendError

    relative = "attempts/scenario/attempt-1"
    if kind == "file":
        path = tmp_path / relative / "work"
        path.parent.mkdir(parents=True)
        path.write_text("not a directory")
    elif kind == "escape":
        relative = "../foreign"
    with pytest.raises(BackendError):
        gate.attempt_work_directory(tmp_path, {"path": relative})


def test_cleanup_waits_for_native_launcher_exit_without_terminating_it(
    tmp_path, monkeypatch
):
    helper_file = tmp_path / "cmd.exe"
    helper_file.write_text("system helper")
    work = tmp_path / "attempt/work"
    work.mkdir(parents=True)
    alive = True
    snapshots = 0
    terminated = []

    def descendants(recursive):
        nonlocal snapshots
        snapshots += 1
        return [SimpleNamespace(exe=lambda: str(helper_file))] if snapshots == 1 else []

    def terminate():
        nonlocal alive
        alive = False
        terminated.append(123)

    instance = SimpleNamespace(
        create_time=lambda: 1,
        exe=lambda: "pscad.exe",
        name=lambda: "PSCAD.exe",
        children=descendants,
        terminate=terminate,
        wait=lambda timeout: None,
    )
    monkeypatch.setattr(gate, "process_alive", lambda identity: alive)
    monkeypatch.setattr(gate.psutil, "Process", lambda pid: instance)
    result = gate.terminate_owned_instance(
        {"vendor_pid": 123, "create_time": 1, "exe": "pscad.exe"}, work
    )
    assert result["session_absent"]
    assert snapshots >= 2 and terminated == [123]
