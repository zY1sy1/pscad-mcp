"""Report I/O must not abort an owned PWM lifecycle."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[1] / "scripts/run_mmc_pwm_command_probe.py"
    spec = importlib.util.spec_from_file_location("pwm_command_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arguments(monkeypatch, directory, name="PWM_probe"):
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE", "1")
    monkeypatch.setenv("PSCAD_MCP_MMC_ACCEPTANCE", "1")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe",
            "--source",
            str(directory / "source.pscx"),
            "--library",
            str(directory / "intermediate.pslx"),
            "--workspace",
            str(directory / "run"),
            "--case-name",
            name,
        ],
    )


def test_transient_report_sharing_violation_is_retried(probe, monkeypatch, tmp_path):
    arguments(monkeypatch, tmp_path)
    replace = Path.replace
    failures = []

    def locked_once(path, destination):
        if Path(destination).name == "report.json" and not failures:
            failures.append(str(path))
            raise PermissionError(5, "Windows report sharing violation")
        return replace(path, destination)

    async def completed(args, report, checkpoint):
        report["status"] = "PASS"
        checkpoint()

    monkeypatch.setattr(Path, "replace", locked_once)
    monkeypatch.setattr(probe, "run", completed)
    monkeypatch.setattr(probe.robust_executor, "shutdown", lambda: None)
    assert probe.main() == 0
    assert failures
    assert json.loads((tmp_path / "run/report.json").read_text())["status"] == "PASS"


def test_emtdc_namespace_is_validated_before_creating_workspace(
    probe, monkeypatch, tmp_path
):
    arguments(monkeypatch, tmp_path, "P" * 31)
    with pytest.raises(SystemExit, match="2"):
        probe.main()
    assert not (tmp_path / "run").exists()


def test_cleanup_runs_despite_persistent_report_lock(probe):
    calls = []

    class Service:
        async def stop_simulation(self, name):
            calls.append(("stop", name))
            return "stopped"

        async def quit_pscad(self, *, confirm):
            calls.append(("quit", confirm))
            return "exited"

    def locked():
        raise PermissionError("report.json remains locked")

    report = {"status": "FAIL"}
    asyncio.run(probe.cleanup_owned(Service(), "PWM", None, {}, report, locked, True))
    assert calls == [("stop", "PWM"), ("quit", True)]
    assert report["quit_result"] == "exited"
    assert len(report["checkpoint_errors"]) == 2
