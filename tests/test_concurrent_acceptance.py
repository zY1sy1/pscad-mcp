"""Acceptance must distinguish another worker from its own leaked instance."""

import asyncio

import pytest

from pscad_mcp.acceptance.preflight import run_licensed_session_preflight
from tests.test_lcc_mmc_preflight import SessionService, clean_git, request
from pscad_mcp.acceptance.preflight import run_static_preflight


def test_concurrent_static_preflight_keeps_foreign_process_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    value = request(tmp_path)
    foreign = [{"pid": 900, "name": "PSCAD.exe"}]
    report = run_static_preflight(
        value,
        git_reader=lambda root: clean_git(value),
        module_finder=lambda name: True,
        process_reader=lambda: foreign,
    )
    assert report["status"] == "PASS"
    assert report["external_pscad_processes"] == foreign
    assert report["process_scope"] == "owned-instance"


@pytest.mark.parametrize("leak", [False, True])
def test_overlapping_preflights_only_inspect_their_own_instance(monkeypatch, tmp_path, leak):
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")

    async def exercise():
        processes = {900: {"pid": 900, "name": "PSCAD.exe"}}
        first_status = asyncio.Event()
        second_status = asyncio.Event()
        first_quit = asyncio.Event()

        class Worker(SessionService):
            def __init__(self, pid):
                super().__init__()
                self.pid = pid

            async def attach_local(self):
                processes[self.pid] = {"pid": self.pid, "name": "PSCAD.exe"}

            async def status(self):
                value = await super().status()
                value["session"] = {"managed_pid": self.pid}
                (first_status if self.pid == 101 else second_status).set()
                await (second_status if self.pid == 101 else first_status).wait()
                return value

            async def quit_pscad(self, *, confirm):
                assert confirm is True
                if self.pid == 202:
                    await first_quit.wait()
                else:
                    assert 202 in processes
                if not leak or self.pid != 101:
                    del processes[self.pid]
                if self.pid == 101:
                    first_quit.set()

        workers = []
        for pid in (101, 202):
            folder = tmp_path / str(pid)
            folder.mkdir()
            workers.append(run_licensed_session_preflight(
                Worker(pid), workspace_root=folder,
                process_reader=lambda: list(processes.values()),
            ))
        reports = await asyncio.wait_for(asyncio.gather(*workers), 2)
        assert reports[0]["status"] == ("FAIL" if leak else "PASS")
        assert reports[1]["status"] == "PASS"
        assert reports[0]["remaining_processes"] == (
            [{"pid": 101, "name": "PSCAD.exe"}] if leak else []
        )
        assert 900 in processes

    asyncio.run(exercise())


def test_concurrent_preflight_missing_managed_pid_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    report = asyncio.run(run_licensed_session_preflight(
        SessionService(), workspace_root=tmp_path, process_reader=list,
    ))
    assert report["status"] == "FAIL"
    assert report["checks"]["runtime"] == "FAIL"


@pytest.mark.parametrize("owned_leak", [False, True])
def test_dynamic_runner_concurrent_scope_keeps_foreign_instance(monkeypatch, tmp_path, owned_leak):
    from tests import test_lcc_dynamic_runner as dynamic

    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    value, staging = dynamic.valid_request(tmp_path)
    service = dynamic._ConfigurableService(staging, managed_pid=42)
    foreign = {"pid": 900, "name": "PSCAD.exe"}
    def inventory():
        return [foreign] + ([{"pid": 42}] if owned_leak and service.attached else [])
    report = asyncio.run(dynamic.run_fixed_lcc_dynamic_acceptance(
        value, service=service, builder=dynamic.PassingDynamicBuilder(staging),
        process_reader=inventory, poll_interval_s=0,
    ))
    assert report["status"] == ("FAIL" if owned_leak else "INCOMPLETE_ANALYSIS")
    assert report["runtime"]["remaining_processes"] == ([{"pid": 42}] if owned_leak else [])
    assert service.quit_called
    assert foreign in inventory()


def test_dynamic_concurrent_run_requires_verified_ownership(monkeypatch, tmp_path):
    from tests import test_lcc_dynamic_runner as dynamic

    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    value, staging = dynamic.valid_request(tmp_path)
    service = dynamic.PassingDynamicService(staging)
    builder = dynamic.PassingDynamicBuilder(staging)
    report = asyncio.run(dynamic.run_fixed_lcc_dynamic_acceptance(
        value, service=service, builder=builder,
        process_reader=lambda: [{"pid": 900}], poll_interval_s=0,
    ))
    assert report["status"] == "FAIL"
    assert report["failure"]["stage"] == "attach"
    assert builder.plan_calls == []
    assert service.quit_called


def test_dynamic_real_cleanup_probes_the_owned_pid_directly(monkeypatch):
    from pscad_mcp.acceptance import process_scope
    from pscad_mcp.core.process_inventory import list_pscad_processes
    from pscad_mcp.hvdc.builders.lcc.dynamic_runner import _remaining_runtime_processes

    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    monkeypatch.setattr(process_scope.psutil, "pid_exists", lambda pid: pid == 42)
    assert asyncio.run(_remaining_runtime_processes({"managed_pid": 42}, list_pscad_processes)) == [{"pid": 42}]


def test_dynamic_concurrent_terminator_never_targets_foreign_pid(monkeypatch, tmp_path):
    from tests import test_lcc_dynamic_runner as dynamic

    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    value, staging = dynamic.valid_request(tmp_path)
    processes = {900: {"pid": 900}}
    terminated = []
    class Service(dynamic._ConfigurableService):
        async def attach_local(self):
            await super().attach_local()
            processes[42] = {"pid": 42}
    def terminate(pid):
        assert pid == 42
        terminated.append(pid)
        del processes[pid]
    report = asyncio.run(dynamic.run_fixed_lcc_dynamic_acceptance(
        value, service=Service(staging, managed_pid=42),
        builder=dynamic.PassingDynamicBuilder(staging),
        process_reader=lambda: list(processes.values()), process_terminator=terminate,
        poll_interval_s=0,
    ))
    assert report["status"] == "INCOMPLETE_ANALYSIS"
    assert terminated == [42]
    assert processes == {900: {"pid": 900}}


@pytest.mark.parametrize("enabled, expected", [("1", "allow"), ("0", "reject")])
def test_dynamic_factory_passes_instance_launch_policy(monkeypatch, tmp_path, enabled, expected):
    from types import SimpleNamespace
    from pscad_mcp.hvdc.builders.lcc import dynamic_acceptance_cli as cli

    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", enabled)
    captured = {}
    monkeypatch.setattr(cli, "LegacyBackend", lambda *args, **kwargs: captured.update(kwargs))
    monkeypatch.setattr(cli, "PscadService", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "LccBuilderService", lambda *args, **kwargs: object())
    cli._service_factory(SimpleNamespace(master_path=tmp_path / "master.pslx", workspace_root=tmp_path))
    assert captured["legacy_existing_policy"] == expected


@pytest.mark.parametrize("kind", ["fixed", "native"])
@pytest.mark.parametrize("remaining_pid, expected", [(900, "PASS"), (42, "FAIL")])
def test_lcc_cleanup_distinguishes_foreign_and_owned_processes(
    monkeypatch, tmp_path, kind, remaining_pid, expected,
):
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    from tests import test_lcc_fixed_acceptance as fixed
    from tests import test_lcc_native_acceptance as native

    if kind == "fixed":
        value = fixed.fixed_request(tmp_path)
        operation = fixed.run_fixed_lcc_acceptance(
            value, service=fixed.FakePscadService(),
            builder=fixed.FakeFixedBuilder(value.workspace_root),
            companion_gate_action=lambda *a, **k: fixed._component_gate_for_run(value),
            master_audit_action=fixed._fake_master_audit,
            process_reader=lambda: [{"pid": remaining_pid}], poll_interval_s=0,
        )
    else:
        value = native.native_request(tmp_path)
        from pscad_mcp.hvdc.builders.lcc.native_acceptance import run_native_lcc_acceptance
        operation = run_native_lcc_acceptance(
            value, service=native.FakePscadService(),
            builder=native.FakeBuilder(value.workspace_root, value.template_path),
            process_reader=lambda: [{"pid": remaining_pid}], poll_interval_s=0,
        )
    report = asyncio.run(operation)
    assert report["status"] == expected
    assert report["runtime"]["remaining_processes"] == (
        [{"pid": 42}] if remaining_pid == 42 else []
    )


def test_legacy_acceptance_records_vendor_pid_not_global_process_delta(monkeypatch):
    from types import SimpleNamespace
    from tests import test_legacy_acceptance as legacy

    monkeypatch.setattr(legacy, "_pscad_processes", lambda: {42: "PSCAD.exe", 900: "PSCAD.exe"})

    class Backend:
        session_details = {"managed_pid": 42}

        async def attach(self):
            return SimpleNamespace(alive=True, licensed=True, owns_process=True)

    case = legacy.LegacyAcceptanceCase()
    case.owned_processes = {}
    asyncio.run(case._attach_and_record(Backend()))
    assert case.owned_processes == {42: "PSCAD.exe"}


def test_real_cleanup_checks_owned_pid_even_when_inventory_is_truncated(monkeypatch):
    from pscad_mcp.acceptance import process_scope as scope

    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    monkeypatch.setattr(scope, "list_pscad_processes", lambda: [{"pid": i} for i in range(1, 17)], raising=False)
    import psutil
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid == 17)
    result = scope.remaining_acceptance_processes(
        {"managed_pid": 17}, scope.list_pscad_processes,
    )
    assert result == [{"pid": 17}]


def test_setup_failure_still_closes_the_owned_instance(monkeypatch):
    import unittest
    from types import SimpleNamespace
    from tests import test_legacy_acceptance as legacy

    monkeypatch.setattr(legacy, "_pscad_processes", dict)
    calls = []

    class Backend:
        owns_process = True
        session_details = {"managed_pid": None}

        async def attach(self):
            calls.append("attach")
            return SimpleNamespace(alive=True, licensed=True, owns_process=True)

        async def quit(self):
            calls.append("quit")
            self.owns_process = False

        async def disconnect(self):
            calls.append("disconnect")

    class BrokenOwnership(legacy.LegacyAcceptanceCase):
        def _new_backend(self):
            return Backend()

        async def test_body(self):
            raise AssertionError("Must not reach a test after failed setup.")

    result = unittest.TestResult()
    BrokenOwnership("test_body").run(result)
    assert not result.wasSuccessful()
    assert calls == ["attach", "quit", "disconnect"]


@pytest.mark.parametrize("reused", [False, True])
def test_live_test_supervisor_only_cleans_verified_process_identity(monkeypatch, tmp_path, reused):
    import json
    from tests import test_concurrent_acceptance_real as live

    calls = []
    (tmp_path / "ready.json").write_text(json.dumps({"pid": 42, "created_at": 100}))

    class Worker:
        def poll(self):
            return 0

    class Process:
        def create_time(self):
            return 200 if reused else 100

        def terminate(self):
            calls.append("terminate")

        def wait(self, *, timeout):
            calls.append("wait")

    monkeypatch.setattr(live.psutil, "Process", lambda pid: Process())
    result = live._cleanup_worker(Worker(), tmp_path)
    assert calls == ([] if reused else ["terminate", "wait"])
    assert result["forced_cleanup"] is (not reused)
    assert (tmp_path / "supervisor-cleanup.json").is_file()
