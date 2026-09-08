import asyncio
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.hvdc.builders.mmc import native_fault_replay as replay
from pscad_mcp.hvdc.builders.mmc.fault_channels import (
    default_fault_checks,
    snapshot_output_dataset,
)


def _request(tmp_path, monkeypatch):
    project = tmp_path / "SavedCase.pscx"
    project.write_text("<project name='SavedCase'/>")
    bundle = tmp_path / "SavedCase.bundle"
    bundle.mkdir()
    (bundle / "library.pslx").write_text("library")
    monkeypatch.setattr(replay, "verify_fault_instrumentation", lambda *_: {"matched": True})
    return {"project": project, "bundle": bundle, "channel_contract": {"project_path": str(project)},
            "checks_contract": default_fault_checks(), "settings": {}, "source_identities": {},
            "dependency_files": {"library.pslx": replay._hash(bundle / "library.pslx")}, "workspace": tmp_path / "replay"}


def test_missing_replay_opt_in_keeps_failure_report_without_pending_ownership(tmp_path, monkeypatch):
    monkeypatch.delenv("PSCAD_MCP_MMC_ACCEPTANCE", raising=False)
    result = asyncio.run(replay.verify_native_fault_replay(**_request(tmp_path, monkeypatch)))
    assert result["status"] == "FAIL"
    assert result["error"]["code"] == "MMC_RELOAD_OPT_IN_REQUIRED"
    assert result["owned_process_cleaned"] is True
    assert result["worker_launched"] is False
    assert result["cleanup_pending"] is False
    assert Path(result["supervisor_report_path"]).is_file()


def test_worker_exit_without_report_is_preserved_as_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("PSCAD_MCP_MMC_ACCEPTANCE", "1")
    request = _request(tmp_path, monkeypatch)

    class Process:
        pid = 731
        returncode = 0

        async def communicate(self):
            return b"worker exited without report", None

    async def launch(*args, **kwargs):
        assert kwargs["env"]["PSCAD_MCP_ACCEPTANCE_CONCURRENT"] == "1"
        return Process()

    monkeypatch.setattr(replay.asyncio, "create_subprocess_exec", launch)
    result = asyncio.run(replay.verify_native_fault_replay(**request))
    assert result["status"] == "FAIL"
    assert result["worker_exit_code"] == 0
    assert result["cleanup_pending"] is True
    assert "report" in result["error"]["message"].lower()
    assert (Path(request["workspace"]) / "worker.log").read_bytes() == b"worker exited without report"
    assert json.loads(Path(result["supervisor_report_path"]).read_text())["status"] == "FAIL"


def test_owned_cleanup_refuses_reused_pid_without_terminating_it(monkeypatch):
    calls = []

    class Process:
        def create_time(self):
            return 20.0

        def terminate(self):
            calls.append("terminate")

    monkeypatch.setattr(replay.psutil, "Process", lambda _: Process())
    assert callable(getattr(replay, "_terminate_owned_pscad", None))
    result = asyncio.run(replay._terminate_owned_pscad({"pid": 100, "created_at": 10.0, "executable": "PSCAD.exe"}))
    assert result["owned_process_cleaned"] is True
    assert result["ownership_status"] == "original_process_exited"
    assert calls == []


def test_owned_cleanup_escalates_only_the_verified_process(monkeypatch):
    calls = []

    class Process:
        def create_time(self):
            return 10.0

        def exe(self):
            return "C:/PSCAD/bin/PSCAD.exe"

        def terminate(self):
            calls.append("terminate")

        def kill(self):
            calls.append("kill")

        def wait(self, timeout):
            calls.append("wait")
            if "kill" not in calls:
                raise replay.psutil.TimeoutExpired(timeout, pid=100)
            return 0

    monkeypatch.setattr(replay.psutil, "Process", lambda _: Process())
    assert callable(getattr(replay, "_terminate_owned_pscad", None))
    result = asyncio.run(replay._terminate_owned_pscad({"pid": 100, "created_at": 10.0, "executable": "C:/PSCAD/bin/PSCAD.exe"}))
    assert result["owned_process_cleaned"] is True
    assert calls == ["terminate", "wait", "kill", "wait"]


@pytest.mark.parametrize("changed_control", [False, True])
def test_replay_save_allows_only_verified_virtual_root_rebinding(tmp_path, changed_control):
    original = tmp_path / "original.pscx"
    saved = tmp_path / "saved.pscx"
    original.write_text('<project name="case"><hierarchy><call name="Station" link="10"/></hierarchy><param name="Kp" value="1"/></project>')
    root = ET.parse(original).getroot()
    root.find("./hierarchy/call").set("link", "20")
    if changed_control:
        root.find("param").set("value", "2")
    ET.ElementTree(root).write(saved)
    contract = {"virtual_root_rebinding": {"before": "Station[10]", "after": "Station[20]"}}
    assert callable(getattr(replay, "_verify_replay_saved_model", None))
    if changed_control:
        with pytest.raises(ValueError, match="model"):
            replay._verify_replay_saved_model(original, saved, contract)
    else:
        assert replay._verify_replay_saved_model(original, saved, contract) is True


@pytest.mark.parametrize("changed", [None, "python_pid", "checks_sha256", "copied_bundle_hashes", "parent_channel_contract_sha256", "replay_saved_model_verified"])
def test_replay_supervisor_requires_complete_matching_worker_evidence(tmp_path, monkeypatch, changed):
    monkeypatch.setenv("PSCAD_MCP_MMC_ACCEPTANCE", "1")
    arguments = _request(tmp_path, monkeypatch)

    class Process:
        pid = 731
        returncode = 0

        async def communicate(self):
            return b"completed synthetic replay protocol", None

    async def launch(*args, **kwargs):
        request_path = Path(args[args.index("--request") + 1])
        request = json.loads(request_path.read_text())
        worker = request_path.parent / "worker"
        worker.mkdir()
        (worker / "SavedCase.pscx").write_bytes(Path(request["project"]["path"]).read_bytes())
        output = worker / "SavedCase_01.out"
        output.write_text("0 0\n5 0\n")
        (worker / "SavedCase.inf").write_text("metadata")
        report = {"status": "PASS", "python_pid": Process.pid, "request_sha256": replay._hash(request_path),
                  "owned_process_cleaned": True, "copied_project_sha256": request["project"]["sha256"],
                  "copied_bundle_hashes": request["bundle"]["files"], "parent_channel_contract_sha256": request["channel_contract_sha256"],
                  "checks_sha256": request["checks_sha256"], "replay_saved_model_verified": True,
                  "acceptance": {"verdict": "PASS"}, "output_identity": snapshot_output_dataset(output),
                  "replay_channel_contract": {"project_path": str(worker / "SavedCase.pscx")}}
        if changed:
            report[changed] = "changed"
        (worker / "report.json").write_text(json.dumps(report))
        return Process()

    monkeypatch.setattr(replay.asyncio, "create_subprocess_exec", launch)
    result = asyncio.run(replay.verify_native_fault_replay(**arguments))
    assert result["status"] == ("FAIL" if changed else "PASS")
    assert result["worker_exit_code"] == 0
    if changed is None:
        assert result["artifacts"]["request.json"]["sha256"]
        assert result["artifacts"]["worker/SavedCase_01.out"]["sha256"]
        assert result["artifacts"]["supervisor-report.json"]["sha256"]


@pytest.mark.parametrize("verdict", ["PASS", "FAIL"])
def test_independent_worker_uses_frozen_dependencies_and_cleans_its_own_session(tmp_path, monkeypatch, verdict):
    from pscad_mcp.hvdc.builders.mmc import blank_service

    monkeypatch.setenv("PSCAD_MCP_MMC_ACCEPTANCE", "1")
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    arguments = _request(tmp_path, monkeypatch)
    source_bundle = arguments["bundle"]
    stale = source_bundle / "library.gf42"
    stale.mkdir()
    (stale / "stale.obj").write_text("must not seed an independent build")
    request_path = tmp_path / "replay" / "request.json"
    request = {"project": {"path": str(arguments["project"]), "sha256": replay._hash(arguments["project"])},
               "bundle": {"path": str(source_bundle), "files": arguments["dependency_files"], "source_snapshot": replay._files(source_bundle)},
               "channel_contract": {"project_path": str(arguments["project"]), "readback": {}},
               "checks_contract": default_fault_checks(), "settings": {}, "source_identities": {"master": {}, "library": {"path": str(source_bundle / "library.pslx")}}}
    request["channel_contract_sha256"] = replay._json_hash(request["channel_contract"])
    request["checks_sha256"] = replay._json_hash(request["checks_contract"])
    replay._write(request_path, request)
    calls = []

    class Backend:
        owns_process = True

        def __init__(self):
            self.session_details = {"managed_pid": 100, "managed_executable": "C:/PSCAD/bin/PSCAD.exe"}

    class Service:
        _backend = None

        async def attach_local(self):
            calls.append("attach")
            self._backend = Backend()

        async def status(self):
            return {"session": self._backend.session_details}

        async def quit_pscad(self, *, confirm):
            assert confirm is True
            calls.append("quit")

    class Process:
        def create_time(self):
            return 10.0

        def exe(self):
            return "C:/PSCAD/bin/PSCAD.exe"

        def wait(self, timeout):
            calls.append("wait_owned")
            return 0

    async def runtime_master(*args):
        return {"master_sha256": "synthetic"}

    async def run(service, project, library, contract, checks, settings, evidence, record, checkpoint):
        assert not (library.parent / "library.gf42").exists()
        assert project.name == arguments["project"].name
        channel_path = evidence / "channels.json"
        replay._write(channel_path, contract)
        record["result"]["channel_contract_path"] = str(channel_path)
        checkpoint("saved_and_bound")
        output = project.parent / "SavedCase_01.out"
        output.write_text("0 0\n5 0\n")
        (output.parent / "SavedCase.inf").write_text("metadata")
        return contract, {"identity": snapshot_output_dataset(output)}

    monkeypatch.setattr(replay, "_service", lambda _: Service())
    monkeypatch.setattr(replay.psutil, "Process", lambda _: Process())
    monkeypatch.setattr(blank_service, "_verify_runtime_master", runtime_master)
    monkeypatch.setattr(blank_service, "_run_native_fault_case", run)
    monkeypatch.setattr(replay, "evaluate_template_native_dc_fault", lambda *args, **kwargs: {"verdict": verdict})
    result = asyncio.run(replay._worker(request_path, replay._hash(request_path)))
    assert result["status"] == verdict, result.get("error")
    assert result["owned_process_cleaned"] is True
    assert result["replay_saved_model_verified"] is True
    assert calls == ["attach", "quit", "wait_owned"]
