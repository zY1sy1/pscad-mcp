"""Software lifecycle tests. No licensed acceptance is established here."""

import asyncio
import copy
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.hvdc.builders.mmc.blank_service import _recipe_contract
from pscad_mcp.hvdc.builders.mmc.fault_channels import (
    default_fault_checks,
    finalize_fault_instrumentation,
    snapshot_output_dataset,
)
from pscad_mcp.hvdc.builders.mmc.journal import AtomicJournal
from pscad_mcp.hvdc.builders.mmc.template_audit import discover_official_mmc_template
from tests.mmc_timing_fault_case import (
    _digest,
    _identity,
    _verify_first_saved_model,
    prepare_joint_case,
)


def _module():
    spec = importlib.util.find_spec("tests.mmc_joint_acceptance")
    assert spec is not None, "The gated public/joint acceptance runner is missing"
    return importlib.import_module(spec.name)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_missing_license_opt_in_cannot_construct_a_service(tmp_path, monkeypatch):
    monkeypatch.delenv("PSCAD_MCP_MMC_ACCEPTANCE", raising=False)
    calls = []
    result = asyncio.run(
        _module().run_public_joint_acceptance(
            tmp_path / "missing.json",
            tmp_path / "run",
            service_factory=lambda _: calls.append("service"),
        )
    )
    assert result["status"] == "FAIL"
    assert result["error"]["code"] == "MMC_ACCEPTANCE_OPT_IN_REQUIRED"
    assert result["owned_process_cleaned"] is True
    assert calls == []


@pytest.mark.parametrize(
    "report",
    [
        {
            "status": "FAIL",
            "scope": "steady_and_dc_fault_recovery",
            "owned_process_cleaned": True,
        },
        {
            "status": "PASS",
            "scope": "steady_only_diagnostic",
            "owned_process_cleaned": True,
        },
        {
            "status": "PASS",
            "scope": "steady_and_dc_fault_recovery",
            "owned_process_cleaned": False,
        },
    ],
)
def test_incomplete_b_acceptance_never_constructs_a_service(
    tmp_path, monkeypatch, report
):
    monkeypatch.setenv("PSCAD_MCP_MMC_ACCEPTANCE", "1")
    accepted = _write(tmp_path / "b" / "acceptance-report.json", report)
    handoff = tmp_path / "b" / "channels-handoff.json"
    _write(
        handoff,
        {
            "schema_version": 1,
            "scope": "template_native_dc_fault",
            "evidence": {"acceptance_report": accepted},
        },
    )
    calls = []
    result = asyncio.run(
        _module().run_public_joint_acceptance(
            handoff, tmp_path / "run", service_factory=lambda _: calls.append("service")
        )
    )
    assert result["status"] == "FAIL"
    assert result["error"]["code"] == "MMC_B_HANDOFF_NOT_ACCEPTED"
    assert calls == []
    assert Path(result["report_path"]).is_file()


@pytest.mark.parametrize("changed", [None, "parameters", "steps"])
def test_recipe_binding_keeps_b_and_public_producer_provenance_separate(changed):
    public = _recipe_contract("native_full_sort_dc_integral_004_v1")
    b_recipe = {
        "id": public["name"],
        "parameters": copy.deepcopy(public["parameters"]),
        "steps": copy.deepcopy(public["steps"]),
        "producer_code_hashes": {
            "fault_channels": {"path": "B/fault_channels.py", "sha256": "b" * 64}
        },
    }
    if changed == "parameters":
        b_recipe["parameters"]["t1_dc_integral_time_s"] = 0.08
    elif changed == "steps":
        b_recipe["steps"] = list(reversed(b_recipe["steps"]))
    if changed:
        with pytest.raises(ValueError):
            _module().require_recipe_match(b_recipe, public)
    else:
        assert _module().require_recipe_match(b_recipe, public) is True


def test_joint_replay_verifies_two_distinct_vendor_root_rebindings(tmp_path):
    master = Path("C:/Program Files (x86)/PSCAD46/master.pslx")
    if not master.is_file():
        pytest.skip("Installed Master metadata is unavailable")
    source, library = discover_official_mmc_template()
    preparation = asyncio.run(
        prepare_joint_case(
            tmp_path / "first",
            source=source,
            library=library,
            master=master,
            model_recipe="native_full_sort_dc_integral_004_v1",
        )
    )
    project = Path(preparation["project"]["path"])
    tree = ET.parse(project)
    root_call = tree.find("./hierarchy/call")
    initial_link = int(root_call.get("link"))
    root_call.set("link", str(initial_link + 1))
    tree.find("./paramlist[@name='Settings']/param[@name='time_duration']").set(
        "value", "5.0"
    )
    tree.write(project, encoding="utf-8")
    first = finalize_fault_instrumentation(project, preparation["fault_contract"])
    b_ref = _write(
        tmp_path / "handoff.json", {"fixture": "already verified by coordinator"}
    )
    context = {
        "schema_version": 1,
        "scope": "joint_timing_fault",
        "b_handoff": b_ref,
        "preparation": preparation,
        "first_saved_model": _identity(project),
        "first_saved_fault_contract": first,
    }
    child = tmp_path / "child" / project.name
    child.parent.mkdir()
    tree.find("./hierarchy/call").set("link", str(initial_link + 2))
    tree.write(child, encoding="utf-8")
    seed = copy.deepcopy(first)
    seed["project_path"] = str(child)
    seed["readback"]["project_path"] = str(child)
    seed["vendor_finalized"] = False
    seed.pop("virtual_root_rebinding", None)
    seed["replay_parent_contract_sha256"] = _digest(first)
    final = finalize_fault_instrumentation(child, seed)
    before = copy.deepcopy((context, final))
    result = _module().verify_joint_saved_child(context, child, final)
    assert result["verdict"] == "PASS"
    assert result["raw_to_first_saved_sha256"] != result["first_to_child_saved_sha256"]
    assert (context, final) == before
    wrong = copy.deepcopy(final)
    wrong["virtual_root_rebinding"]["before"] = first["virtual_root_rebinding"][
        "before"
    ]
    with pytest.raises(ValueError):
        _module().verify_joint_saved_child(context, child, wrong)


@pytest.mark.parametrize("change", ["format", "time_step", "controller"])
def test_first_joint_save_allows_numeric_formatting_but_not_changed_values(
    tmp_path, change
):
    original = tmp_path / "before.pscx"
    saved = tmp_path / "after.pscx"
    original.write_text(
        '<project><paramlist name="Settings"><param name="time_duration" value="5"/><param name="time_step" value="25"/><param name="sample_step" value="250"/><param name="PlotType" value="1"/><param name="StartType" value="0"/></paramlist><control value="0.04"/></project>'
    )
    tree = ET.parse(original)
    tree.find("./paramlist/param[@name='time_duration']").set("value", "5.0")
    if change == "time_step":
        tree.find("./paramlist/param[@name='time_step']").set("value", "50")
    elif change == "controller":
        tree.find("control").set("value", "0.08")
    tree.write(saved, encoding="utf-8")
    if change == "format":
        assert _verify_first_saved_model(original, saved, {}) is True
    else:
        with pytest.raises(ValueError):
            _verify_first_saved_model(original, saved, {})


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "public_attach",
        "public_run",
        "public_cleanup",
        "public_task_journal",
        "public_task_cancelled",
        "public_shutdown_io",
        "public_status_unreadable",
        "public_retained_lease",
        "public_task_clean",
        "public_close_drift",
        "joint_run",
        "joint_replay",
        "joint_replay_exception",
        "joint_replay_false_clean",
        "joint_cleanup",
        "joint_model_close_drift",
        "joint_output_close_drift",
    ],
)
def test_owned_lifecycle_orders_phases_and_retains_uncertain_cleanup(
    tmp_path, monkeypatch, failure
):
    module = _module()
    monkeypatch.setenv("PSCAD_MCP_MMC_ACCEPTANCE", "1")
    monkeypatch.delenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", raising=False)
    calls = []
    b_ref = _write(tmp_path / "b-handoff.json", {"fixture": "synthetic lifecycle"})
    sources = {
        name: _write(tmp_path / "sources" / (name + ".json"), {"source": name})
        for name in ("project", "library", "master")
    }
    recipe = _recipe_contract("native_full_sort_dc_integral_004_v1")
    accepted = {
        "file": b_ref,
        "source_hashes": sources,
        "recipe": {
            "id": recipe["name"],
            "parameters": recipe["parameters"],
            "steps": recipe["steps"],
        },
    }

    async def validate(path):
        calls.append("validate_b")
        return accepted

    class Builder:
        def __init__(self, service, *, workspace_root):
            self.service, self.root, self._tasks = service, Path(workspace_root), {}
            self._leases = (
                {"test": object()} if failure == "public_retained_lease" else {}
            )

        def plan_model(self, request):
            return {
                "plan_hash": "a" * 64,
                "target_path": str(self.root / "Public.pscx"),
                "model_recipe": recipe,
                "source_identities": sources,
                "settings": {
                    "simulation_duration_s": 5.0,
                    "time_step_s": 25e-6,
                    "output_step_s": 250e-6,
                },
            }

        async def build_model(self, request, plan_hash, *, confirm):
            assert confirm is True and plan_hash == "a" * 64
            calls.append("public_build")

            async def task():
                if failure == "public_task_cancelled":
                    raise asyncio.CancelledError("cancelled after replay launch")
                if failure in {
                    "public_task_journal",
                    "public_status_unreadable",
                    "public_retained_lease",
                    "public_task_clean",
                }:
                    raise OSError("journal failure after replay launch")
                await asyncio.sleep(0)

            self._tasks["test"] = asyncio.create_task(task())
            return {"build_id": "test"}

        def get_build_status(self, build_id):
            calls.append("builder_status")
            if failure == "public_status_unreadable":
                raise OSError("builder status journal is unreadable")
            replay_pending = failure in {"public_task_journal", "public_task_cancelled"}
            return {
                "state": "failed" if failure == "public_run" else "published",
                "result": {
                    "reload": {
                        "status": "PASS",
                        "cleanup_pending": replay_pending,
                        "owned_process_cleaned": not replay_pending,
                    }
                },
            }

        def validate_model(self, path):
            calls.append("public_validate")
            return {
                "accepted": not (
                    failure == "public_close_drift"
                    and calls.count("public_validate") > 1
                )
            }

        async def shutdown(self, timeout_s):
            calls.append("builder_shutdown")
            if failure in {"public_task_journal", "public_task_cancelled"}:
                from pscad_mcp.runtime import PendingCleanupError

                raise PendingCleanupError((asyncio.get_running_loop().create_future(),))
            if failure == "public_shutdown_io":
                raise OSError("builder shutdown journal failed")

    async def prepare(root, **kwargs):
        root = Path(root)
        root.mkdir(parents=True)
        project = root / "JointFaultCase.pscx"
        project.write_text("<project/>")
        return {
            "project": _identity(project),
            "joint_parents": {"B": {"accepted": False}},
            "fault_contract": {},
            "checks": default_fault_checks(),
            "public_plan": Builder(None, workspace_root=root).plan_model({}),
        }

    class Service:
        def __init__(self, root):
            self.root = Path(root)
            self.name = Path(root).name
            self._backend = self._pending_cleanup_backend = None
            self.pid = 101 if self.name == "public" else 102
            calls.append("create:" + self.name)

        async def attach_local(self):
            calls.append("attach:" + self.name)
            backend = SimpleNamespace(owns_process=True)
            if failure == "public_attach" and self.name == "public":
                self._pending_cleanup_backend = backend
                raise RuntimeError("synthetic attach failure")
            self._backend = backend

        async def status(self):
            return {"fixture": "synthetic owned lifecycle"}

        async def get_master_library_identity(self):
            return {
                "master_path": sources["master"]["path"],
                "master_sha256": sources["master"]["sha256"],
                "pscad_version": "4.6.2",
            }

        async def quit_pscad(self, *, confirm):
            calls.append("quit:" + self.name)
            if failure == self.name + "_cleanup":
                raise RuntimeError("synthetic quit failure")
            if self.name == "joint" and failure == "joint_model_close_drift":
                (self.root / "JointFaultCase.pscx").write_text("<changed/>")
            if self.name == "joint" and failure == "joint_output_close_drift":
                (self.root / "JointFaultCase_01.out").write_text("0 99\n5 99\n")
            self._backend = self._pending_cleanup_backend = None

        async def read_output_file(self, *args, **kwargs):
            raise AssertionError("The lifecycle fixture has no real waveform reader")

    def capture(service, request_hash):
        if service._backend is None and service._pending_cleanup_backend is None:
            return None
        return {"pid": service.pid, "created_at": 42.0, "request_sha256": request_hash}

    class Process:
        def create_time(self):
            return 42.0

        def wait(self, timeout):
            return 0

    async def unresolved(ownership):
        return {"owned_process_cleaned": False, "cleanup_pending": True}

    async def run_case(
        service,
        project,
        library,
        contract,
        checks,
        settings,
        evidence,
        record,
        checkpoint,
    ):
        calls.append("joint_run")
        if failure == "joint_run":
            raise RuntimeError("synthetic joint failure")
        ref = _write(evidence / "channels.json", {"fixture": "saved contract"})
        record["result"].update(
            {
                "channel_contract_path": ref["path"],
                "channel_contract_sha256": ref["sha256"],
            }
        )
        checkpoint("saved_and_bound")
        output = project.parent / (project.stem + "_01.out")
        output.write_text("0 0\n5 0\n")
        output.with_name(project.stem + ".inf").write_text("synthetic metadata")
        output.with_name(project.stem + ".infx").write_text(
            "synthetic compiler metadata"
        )
        return {"fixture": "saved contract"}, {
            "identity": snapshot_output_dataset(output)
        }

    async def evaluate(*args):
        return {"verdict": "PASS", "fixture": "synthetic dataset gate"}

    async def replay(*args):
        calls.append("joint_replay")
        if failure == "joint_replay_exception":
            raise OSError("synthetic replay exception")
        return {
            "status": "FAIL" if failure == "joint_replay" else "PASS",
            "owned_process_cleaned": failure != "joint_replay_false_clean",
            "cleanup_pending": False,
        }

    monkeypatch.setattr(module, "_validate_b", validate)
    monkeypatch.setattr(module, "BlankMmcBuilderService", Builder)
    monkeypatch.setattr(module, "prepare_joint_case", prepare)
    monkeypatch.setattr(
        module, "verify_joint_preparation", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(module.native_fault_replay, "_capture_ownership", capture)
    monkeypatch.setattr(
        module.native_fault_replay, "_terminate_owned_pscad", unresolved
    )
    monkeypatch.setattr(module.psutil, "Process", lambda _: Process())
    monkeypatch.setattr(module, "_run_native_fault_case", run_case)
    monkeypatch.setattr(module, "evaluate_joint_dataset", evaluate)
    monkeypatch.setattr(module, "run_joint_replay", replay)
    result = asyncio.run(
        module.run_public_joint_acceptance(
            b_ref["path"], tmp_path / "run", service_factory=Service
        )
    )
    assert result["status"] == ("PASS" if failure is None else "FAIL"), result.get(
        "error"
    )
    assert calls.index("validate_b") < calls.index("create:public")
    assert "quit:public" in calls
    if failure is not None and failure.startswith("public_"):
        assert "create:joint" not in calls
    else:
        assert calls.index("quit:public") < calls.index("create:joint")
        assert "quit:joint" in calls
    pending = failure in {
        "public_cleanup",
        "public_task_journal",
        "public_task_cancelled",
        "public_shutdown_io",
        "public_status_unreadable",
        "public_retained_lease",
        "joint_cleanup",
        "joint_replay_exception",
        "joint_replay_false_clean",
    }
    assert result["cleanup_pending"] is pending
    assert result["lease_retained"] is pending
    if failure == "public_task_journal":
        assert "builder_status" in calls
        assert result["public"]["builder_cleanup_pending"] is True
        assert result["public"]["reload"]["cleanup_pending"] is True
        assert result["public"]["service_cleanup"]["owned_process_cleaned"] is True
    if failure in {
        "public_task_cancelled",
        "public_shutdown_io",
        "public_status_unreadable",
        "public_retained_lease",
    }:
        assert result["public"]["builder_cleanup_pending"] is True
        assert result["public"]["service_cleanup"]["owned_process_cleaned"] is True
    if failure == "public_task_clean":
        assert result["public"]["builder_cleanup_pending"] is False
    assert (
        json.loads(Path(result["report_path"]).read_text())["status"]
        == result["status"]
    )
    assert "PSCAD_MCP_ACCEPTANCE_CONCURRENT" not in module.os.environ


@pytest.mark.parametrize("failure", ["release", "journal", "primary_and_journal"])
def test_finalizer_restores_environment_and_never_leaves_unconfirmed_pass(
    tmp_path, monkeypatch, failure
):
    module = _module()
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    journal = AtomicJournal(tmp_path, "finalizer-test")
    write = journal.write

    def fail_final_write(payload):
        if failure.endswith("journal") and payload["history"][-1] == "finished":
            raise OSError("final journal denied")
        return write(payload)

    monkeypatch.setattr(journal, "write", fail_final_write)
    report = {
        "status": "PASS",
        "physical_acceptance_verified": True,
        "history": [],
        "public": {"cleanup_pending": False, "owned_process_cleaned": True},
        "joint": {"cleanup_pending": False, "owned_process_cleaned": True},
    }
    if failure == "primary_and_journal":
        report.update(
            {
                "status": "FAIL",
                "physical_acceptance_verified": False,
                "error": {"message": "primary failure"},
            }
        )

    class Lease:
        token = "test"

        def release(self, token):
            if failure == "release":
                raise OSError("lease unlink denied")

    assert callable(getattr(module, "_finalize_run", None))
    module._finalize_run(report, Lease(), journal, None)
    assert report["status"] == "FAIL"
    assert report["physical_acceptance_verified"] is False
    assert report["owned_process_cleaned"] is True
    assert report["cleanup_pending"] is False
    assert report["lease_retained"] is (failure == "release")
    assert "PSCAD_MCP_ACCEPTANCE_CONCURRENT" not in module.os.environ
    assert json.loads(journal.path.read_text())["status"] == "FAIL"
    assert report["finalization_errors"]
    if failure == "primary_and_journal":
        assert report["error"]["message"] == "primary failure"


@pytest.mark.parametrize("settled", [False, True])
def test_attach_without_a_handle_cannot_confirm_owned_cleanup(tmp_path, settled):
    module = _module()
    token = SimpleNamespace(
        settled=settled, operation_id=1, generation=0, operation="launch"
    )

    class Service:
        _backend = _pending_cleanup_backend = None

        def __init__(self):
            self.executor = SimpleNamespace(
                pending_settlements_for=lambda owner: () if token.settled else (token,)
            )

        async def attach_local(self):
            raise RuntimeError("EXECUTOR_TIMEOUT before launch ownership returned")

    report = {}

    async def exercise():
        with pytest.raises(RuntimeError, match="EXECUTOR_TIMEOUT"):
            await module._owned_phase(
                tmp_path,
                "public",
                "a" * 64,
                {},
                None,
                report,
                lambda stage: None,
                lambda _: Service(),
            )

    asyncio.run(exercise())
    assert report["public"]["cleanup_pending"] is True
    assert report["public"]["owned_process_cleaned"] is False
    assert report["public"]["attach_outcome_uncertain"] is True


def test_joint_child_rejects_preflight_without_calling_native_worker(
    tmp_path, monkeypatch
):
    module = _module()
    monkeypatch.setenv("PSCAD_MCP_MMC_ACCEPTANCE", "1")
    b_ref = _write(tmp_path / "b.json", {"fixture": "unaccepted"})
    request_path = tmp_path / "replay" / "request.json"
    ref = _write(
        request_path,
        {
            "verification_context": {
                "schema_version": 1,
                "scope": "joint_timing_fault",
                "b_handoff": b_ref,
            }
        },
    )
    calls = []

    async def unaccepted(*args):
        raise ValueError("B is not accepted")

    async def forbidden(*args, **kwargs):
        calls.append("native_worker")
        raise AssertionError("Native execution must not start")

    monkeypatch.setattr(module, "_validate_b", unaccepted)
    monkeypatch.setattr(module.native_fault_replay, "_worker", forbidden)
    result = asyncio.run(module._joint_worker(request_path, ref["sha256"]))
    assert result["python_pid"] == module.os.getpid()
    assert result["worker_parent_pid"] == module.os.getppid()
    assert result["status"] == "FAIL"
    assert result["phase"] == "preflight"
    assert result["owned_process_cleaned"] is True
    assert result["cleanup_pending"] is False
    assert calls == []
    assert (request_path.parent / "worker" / "report.json").is_file()


def test_fault_only_replay_pass_cannot_replace_joint_reanalysis(tmp_path, monkeypatch):
    module = _module()
    project = tmp_path / "Joint.pscx"
    project.write_text("<project/>")
    bundle = project.with_suffix(".bundle")
    bundle.mkdir()
    dependency = _write(bundle / "dependency.json", {"fixture": "dependency"})
    b_ref = _write(tmp_path / "b.json", {"fixture": "already verified"})
    preparation = {
        "project": _identity(project),
        "checks": default_fault_checks(),
        "public_plan": {"settings": {}, "source_identities": {}},
        "dependency_copies": [
            {"path": dependency["path"], "sha256": dependency["sha256"]}
        ],
    }

    async def fault_pass(**kwargs):
        assert kwargs["worker_module"] == "tests.mmc_joint_acceptance"
        return {
            "status": "PASS",
            "owned_process_cleaned": True,
            "cleanup_pending": False,
            "replay_channel_contract": {},
            "output_identity": {},
            "supplemental_evidence": {"verdict": "PASS"},
        }

    def invalid_timing(*args):
        raise ValueError("Child event waveform was not the planned pulse")

    monkeypatch.setattr(
        module, "verify_joint_preparation", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        module.native_fault_replay, "verify_native_fault_replay", fault_pass
    )
    monkeypatch.setattr(module, "verify_joint_child_dataset", invalid_timing)
    result = asyncio.run(
        module.run_joint_replay(preparation, {}, b_ref, tmp_path / "replay")
    )
    assert result["status"] == "FAIL"
    assert result["owned_process_cleaned"] is True
    assert result["cleanup_pending"] is False
    assert "waveform" in result["joint_supervisor_error"]["message"]
