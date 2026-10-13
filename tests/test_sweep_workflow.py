"""Behavioral checks for isolated, durable sweep execution."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import ConfirmationRequired
from pscad_mcp.workflows.sweep.service import SweepService
from pscad_mcp.workflows.sweep.store import WorkspaceLease, atomic_json, tree_inventory


class FakeSession:
    def __init__(
        self,
        sessions,
        *,
        fail_build=False,
        fail_restore=False,
        fail_shutdown=False,
        hold=False,
        missing_output=False,
    ):
        self.sessions = sessions
        self.sessions.append(self)
        self.fail_build = fail_build
        self.fail_restore = fail_restore
        self.fail_shutdown = fail_shutdown
        self.hold = hold
        self.missing_output = missing_output
        self.parameters = {7: {"R": "1.0"}}
        self.writes = []
        self.closed = False
        self.run_called = False
        self.stopped = False
        self.work = None
        self.executor = None
        self.backend = self
        self.name = "legacy"
        self.version = "4.6.2"

    async def attach_local(self):
        return "owned"

    async def status(self):
        return {
            "owns_process": True,
            "session": {"managed_pid": os.getpid()},
            "backend": "legacy",
            "version": "4.6.2",
        }

    async def load_projects(self, paths):
        self.work = Path(paths[-1]).parent

    async def list_projects(self):
        return [{"name": "case", "type": "Case"}]

    async def get_component_parameters(self, name, component_id):
        return dict(self.parameters[component_id])

    async def validate_component_parameters(self, name, component_id, parameters):
        return {k: {"valid": float(v) >= 0} for k, v in parameters.items()}

    async def set_component_parameters(self, name, component_id, parameters):
        if self.fail_restore and self.run_called and parameters.get("R") == "1.0":
            raise RuntimeError("restore rejected")
        self.writes.append((component_id, dict(parameters)))
        self.parameters[component_id].update({k: str(v) for k, v in parameters.items()})

    async def save_project(self, name, *, confirm=False):
        if confirm is not True:
            raise ConfirmationRequired("save_project")

    async def build_project(self, name):
        if self.fail_build:
            raise BackendError("BUILD_FAILED", "deliberate", "fake", "build")

    async def get_project_output(self, name, **kwargs):
        return []

    async def run_project(self, name):
        self.run_called = True
        if not self.missing_output:
            value = float(self.parameters[7]["R"])
            (self.work / "result.psout").write_text(
                json.dumps([value, value * 2, value * 3])
            )

    async def get_run_status(self, name):
        return {"status": "running" if self.hold and not self.stopped else "complete"}

    async def stop_simulation(self, name):
        self.stopped = True

    async def read_output_file(self, path, max_samples=10000, **kwargs):
        return {
            "channels": [
                {
                    "path": "Main/Voltage",
                    "values": json.loads(Path(path).read_text()),
                    "domain": [0, 1, 2],
                }
            ]
        }

    async def shutdown(self):
        if self.fail_shutdown:
            raise RuntimeError("shutdown rejected")
        self.closed = True


@pytest.fixture
def campaign(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "case.pscx").write_text('<project name="case"/>')
    (source / "result.psout").write_text("old source result")
    sessions = []
    spec = {
        "source_root": str(source),
        "entry_file": "case.pscx",
        "project_name": "case",
        "scenarios": [
            {"name": name, "updates": [{"component_id": 7, "parameters": {"R": value}}]}
            for name, value in [("base", 1), ("double", 2), ("triple", 3)]
        ],
        "outputs": [{"path": "result.psout", "channels": ["Main/Voltage"]}],
        "baseline_scenario": "base",
        "poll_interval_seconds": 0.1,
        "output_stability_seconds": 0.1,
    }
    service = SweepService(
        PathPolicy(str(tmp_path)),
        session_factory=lambda: FakeSession(sessions),
        process_alive=lambda identity: any(not s.closed for s in sessions),
    )
    return service, spec, sessions, source


def create(service, spec):
    plan = service.plan(spec)
    return service.create(spec, expected_plan_hash=plan["plan_hash"], confirm=True)[
        "campaign_id"
    ]


async def finish(service, campaign_id):
    await service.wait(campaign_id, timeout=5)
    return service.status(campaign_id, include_report=True)


@pytest.mark.asyncio
async def test_complete_sweep_uses_fresh_copies_restores_and_compares(campaign):
    service, spec, sessions, source = campaign
    before = tree_inventory(source)
    cid = create(service, spec)
    assert not sessions
    started = await service.start(cid, confirm=True)
    assert started["state"] == "running"
    result = await finish(service, cid)
    assert result["state"] == "completed"
    assert result["counts"]["succeeded"] == 3
    assert len({s.work for s in sessions}) == 3
    assert all(s.closed and s.parameters[7]["R"] == "1.0" for s in sessions)
    assert tree_inventory(source) == before
    second = result["report"]["scenarios"][1]
    channel = second["outputs"][0]["channels"][0]
    assert channel["statistics"]["mean"] == 4
    assert channel["comparison"]["mean"] == {"absolute_delta": 2, "relative_delta": 1}


def test_plan_hash_binds_source_and_creation_requires_confirmation(campaign):
    service, spec, sessions, source = campaign
    plan = service.plan(spec)
    with pytest.raises(BackendError, match="confirm"):
        service.create(spec, expected_plan_hash=plan["plan_hash"])
    (source / "new.txt").write_text("changed")
    with pytest.raises(BackendError) as error:
        service.create(spec, expected_plan_hash=plan["plan_hash"], confirm=True)
    assert error.value.code == "SWEEP_PLAN_STALE"
    assert not sessions


@pytest.mark.asyncio
async def test_recoverable_build_failure_continues_and_explicit_retry_preserves_evidence(
    campaign,
):
    service, spec, sessions, _ = campaign
    service.session_factory = lambda: FakeSession(
        sessions, fail_build=len(sessions) == 1
    )
    cid = create(service, spec)
    await service.start(cid, confirm=True)
    result = await finish(service, cid)
    assert result["state"] == "completed_with_failures"
    assert [s["state"] for s in result["scenarios"]] == [
        "succeeded",
        "failed",
        "succeeded",
    ]
    await service.resume(cid, retry_scenarios=["double"], confirm=True)
    result = await finish(service, cid)
    assert result["state"] == "completed"
    assert len(sessions) == 4
    assert result["scenarios"][1]["attempt_count"] == 2
    assert (
        service.store.campaign_path(cid)
        .joinpath(
            "attempts",
            result["scenarios"][1]["directory_key"],
            "attempt-1",
            "result.json",
        )
        .is_file()
    )


@pytest.mark.asyncio
async def test_cancel_stops_only_own_run_and_resume_skips_successful_attempts(campaign):
    service, spec, sessions, _ = campaign
    service.session_factory = lambda: FakeSession(sessions, hold=len(sessions) == 1)
    cid = create(service, spec)
    await service.start(cid, confirm=True)
    for _ in range(100):
        if len(sessions) == 2 and sessions[1].run_called:
            break
        await asyncio.sleep(0.01)
    await service.cancel(cid, confirm=True)
    result = await finish(service, cid)
    assert result["state"] == "cancelled"
    assert sessions[1].stopped and sessions[1].closed
    service.session_factory = lambda: FakeSession(sessions)
    await service.resume(cid, confirm=True)
    result = await finish(service, cid)
    assert result["state"] == "completed"
    assert result["scenarios"][0]["attempt_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["fail_restore", "fail_shutdown"])
async def test_unverified_cleanup_blocks_later_scenarios(campaign, failure):
    service, spec, sessions, _ = campaign
    service.session_factory = lambda: FakeSession(sessions, **{failure: True})
    cid = create(service, spec)
    await service.start(cid, confirm=True)
    result = await finish(service, cid)
    assert result["state"] == "blocked"
    assert len(sessions) == 1
    assert result["scenarios"][0]["state"] == "needs_review"


@pytest.mark.asyncio
async def test_invalid_parameter_and_missing_output_are_not_success(campaign):
    service, spec, sessions, _ = campaign
    spec["scenarios"][0]["updates"][0]["parameters"]["R"] = -1
    service.session_factory = lambda: FakeSession(sessions, missing_output=True)
    cid = create(service, spec)
    await service.start(cid, confirm=True)
    result = await finish(service, cid)
    assert result["counts"]["succeeded"] == 0
    assert not sessions[0].writes
    assert all(s.closed for s in sessions)


@pytest.mark.asyncio
async def test_ranking_applies_constraints_and_does_not_claim_unsampled_optimum(
    campaign,
):
    service, spec, _, _ = campaign
    cid = create(service, spec)
    await service.start(cid, confirm=True)
    await finish(service, cid)
    metric = {
        "output_path": "result.psout",
        "channel": "Main/Voltage",
        "statistic": "mean",
    }
    result = service.analyze(
        cid,
        objective={**metric, "direction": "maximize"},
        constraints=[{**metric, "operator": "<=", "value": 5}],
    )
    assert result["best"]["name"] == "double"
    assert result["optimization_scope"] == "evaluated_scenarios"
    assert result["infeasible_count"] == 1
    with pytest.raises(BackendError):
        service.analyze(
            cid, objective={**metric, "statistic": "eval(x)", "direction": "minimize"}
        )


@pytest.mark.asyncio
async def test_live_workspace_lease_rejects_a_second_service_without_launch(campaign):
    service, spec, sessions, _ = campaign
    service.session_factory = lambda: FakeSession(sessions, hold=True)
    cid = create(service, spec)
    second = SweepService(
        service.path_policy, session_factory=lambda: FakeSession(sessions)
    )
    other = create(second, spec)
    await service.start(cid, confirm=True)
    with pytest.raises(BackendError) as error:
        await second.start(other, confirm=True)
    assert error.value.code == "SWEEP_BUSY"
    await service.cancel(cid, confirm=True)
    await finish(service, cid)


@pytest.mark.asyncio
async def test_result_artifact_tampering_invalidates_analysis(campaign):
    service, spec, _, _ = campaign
    cid = create(service, spec)
    await service.start(cid, confirm=True)
    result = await finish(service, cid)
    path = Path(result["report"]["scenarios"][0]["artifacts"][0]["path"])
    path.write_text("tampered")
    with pytest.raises(BackendError) as error:
        service.analyze(cid)
    assert error.value.code == "SWEEP_EVIDENCE_CHANGED"


def test_source_links_external_dependencies_and_campaign_traversal_are_rejected(
    campaign,
):
    service, spec, _, source = campaign
    (source / "case.pscx").write_text(
        '<project name="case"><param name="File" value="../outside.csv"/></project>'
    )
    with pytest.raises(BackendError):
        service.plan(spec)
    with pytest.raises(BackendError):
        service.status("../../outside")


@pytest.mark.asyncio
async def test_restart_at_nonrunning_boundary_resumes_without_duplicate_completion(
    campaign,
):
    service, spec, sessions, _ = campaign
    cid = create(service, spec)
    await service.start(cid, confirm=True)
    await finish(service, cid)
    _manifest, checkpoint = service.store.load(cid)
    checkpoint["state"] = "running"
    checkpoint["scenarios"][2]["state"] = "pending"
    checkpoint["scenarios"][2]["results"] = []
    service.store.save(cid, checkpoint)
    second = SweepService(
        service.path_policy,
        session_factory=lambda: FakeSession(sessions),
        process_alive=lambda identity: False,
    )
    await second.resume(cid, confirm=True)
    result = await finish(second, cid)
    assert result["state"] == "completed"
    assert len(sessions) == 4
    assert [s["attempt_count"] for s in result["scenarios"]] == [1, 1, 2]


@pytest.mark.asyncio
async def test_live_orphan_blocks_resume_without_contacting_its_process(campaign):
    service, spec, sessions, _ = campaign
    cid = create(service, spec)
    _manifest, checkpoint = service.store.load(cid)
    checkpoint["state"] = "running"
    checkpoint["active_attempt"] = {
        "index": 0,
        "number": 1,
        "path": "attempts/unused/attempt-1",
        "owned_session": {"pid": os.getpid(), "create_time": 1},
        "phase": "running",
    }
    checkpoint["scenarios"][0]["state"] = "running"
    service.store.save(cid, checkpoint)
    second = SweepService(
        service.path_policy,
        session_factory=lambda: FakeSession(sessions),
        process_alive=lambda identity: bool(identity),
    )
    with pytest.raises(BackendError) as error:
        await second.resume(cid, confirm=True)
    assert error.value.code == "SWEEP_NEEDS_REVIEW"
    assert not sessions
    assert second.status(cid)["state"] == "blocked"


def test_tampered_baseline_is_rejected_before_launch(campaign):
    service, spec, sessions, _ = campaign
    cid = create(service, spec)
    service.store.campaign_path(cid).joinpath("baseline", "case.pscx").write_text(
        "changed"
    )
    with pytest.raises(BackendError) as error:
        asyncio.run(service.start(cid, confirm=True))
    assert error.value.code == "SWEEP_EVIDENCE_CHANGED"
    assert not sessions


def test_external_checkpoint_edit_cannot_mark_unrun_scenarios_succeeded(campaign):
    service, spec, _sessions, _ = campaign
    cid = create(service, spec)
    path = service.store.campaign_path(cid) / "checkpoint.json"
    checkpoint = json.loads(path.read_text())
    checkpoint["scenarios"][0]["state"] = "succeeded"
    atomic_json(path, checkpoint)
    with pytest.raises(BackendError) as error:
        service.status(cid)
    assert error.value.code == "SWEEP_EVIDENCE_CHANGED"


def test_lease_is_exclusive_in_another_python_process(campaign):
    import subprocess
    import sys

    service, spec, _sessions, _ = campaign
    cid = create(service, spec)
    lease = WorkspaceLease(service.store.root)
    lease.acquire(cid)
    script = """import sys
from pathlib import Path
from pscad_mcp.workflows.sweep.store import WorkspaceLease
try:
    WorkspaceLease(Path(sys.argv[1])).acquire(sys.argv[2])
except Exception as error:
    print(error.code)
"""
    try:
        result = subprocess.run(
            [sys.executable, "-B", "-c", script, str(service.store.root), cid],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "SWEEP_BUSY"
    finally:
        lease.release()


def test_duplicate_output_paths_and_selectors_are_rejected(campaign):
    service, spec, _sessions, _ = campaign
    spec["outputs"].append(spec["outputs"][0])
    with pytest.raises(BackendError):
        service.plan(spec)
    spec["outputs"] = spec["outputs"][:1]
    spec["outputs"][0]["channels"] *= 2
    with pytest.raises(BackendError):
        service.plan(spec)


@pytest.mark.asyncio
async def test_checkpoint_write_failure_still_restores_and_closes_owned_session(
    campaign, monkeypatch
):
    service, spec, sessions, _ = campaign
    cid = create(service, spec)
    original = service.store.save
    failed = False

    def save(cid, checkpoint):
        nonlocal failed
        if (checkpoint.get("active_attempt") or {}).get(
            "phase"
        ) == "restoring" and not failed:
            failed = True
            raise OSError("checkpoint write failed")
        return original(cid, checkpoint)

    monkeypatch.setattr(service.store, "save", save)
    await service.start(cid, confirm=True)
    await finish(service, cid)
    assert sessions[0].closed
    assert sessions[0].parameters[7]["R"] == "1.0"
    assert len(sessions) == 1


@pytest.mark.asyncio
async def test_tampering_during_campaign_prevents_completed_verdict(campaign):
    service, spec, sessions, _ = campaign
    cid = create(service, spec)

    class TamperingSession(FakeSession):
        async def shutdown(self):
            await super().shutdown()
            retained = self.work.parent / "outputs" / "result.psout"
            if retained.exists():
                retained.write_text("modified after collection")

    service.session_factory = lambda: TamperingSession(sessions)
    await service.start(cid, confirm=True)
    await service.wait(cid, timeout=5)
    status = service.status(cid)
    assert status["state"] == "blocked"
    assert status["error"]["code"] == "SWEEP_EVIDENCE_CHANGED"
    assert all(s.closed for s in sessions)
