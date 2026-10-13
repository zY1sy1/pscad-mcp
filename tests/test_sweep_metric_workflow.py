"""Physical analysis uses immutable campaign outputs through the public tool."""

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.main import create_server
from pscad_mcp.tools import sweep_tools
from pscad_mcp.workflows.sweep.store import file_hash
from tests.test_sweep_workflow import (
    FakeSession,
    create,
    finish,
)
from tests.test_sweep_workflow import (
    campaign as _campaign_fixture,
)

campaign = _campaign_fixture


class OutSession(FakeSession):
    async def run_project(self, name):
        self.run_called = True
        current = float(self.parameters[7]["R"])
        (self.work / "case.inf").write_text(
            'PGB(1) Output Desc="V" Group="Main" Units="kV"\nPGB(2) Output Desc="I" Group="Main" Units="kA"\n'
        )
        (self.work / "case_01.out").write_text(
            f"0 2 {current}\n0.5 2 {current}\n1 2 {current}\n"
        )


def definitions():
    return [
        {
            "name": "energy",
            "kind": "energy",
            "output_path": "case_01.out",
            "voltage_channel": "Main/V",
            "current_channel": "Main/I",
            "mode": "positive",
            "window": [0.1, 0.8],
        },
        {
            "name": "stress",
            "kind": "i2t",
            "output_path": "case_01.out",
            "current_channel": "Main/I",
            "window": [0.1, 0.8],
        },
    ]


async def completed(campaign):
    service, spec, sessions, _ = campaign
    spec["outputs"] = [{"path": "case_01.out", "channels": ["Main/V", "Main/I"]}]
    service.session_factory = lambda: OutSession(sessions)
    cid = create(service, spec)
    await service.start(cid, confirm=True)
    await finish(service, cid)
    return service, cid


@pytest.mark.asyncio
async def test_physical_metric_selection_is_read_only_and_has_replayable_provenance(
    campaign, monkeypatch
):
    service, cid = await completed(campaign)
    root = service.store.campaign_path(cid)
    checkpoint_before = file_hash(root / "checkpoint.json")
    monkeypatch.setattr(sweep_tools, "_service", lambda: service)
    server = create_server(environ={"PSCAD_MCP_TOOL_PROFILE": "sweep"})
    tool = server._tool_manager.get_tool("analyze_parameter_sweep")
    result = await tool.fn(
        cid,
        metrics=definitions(),
        objective={"metric": "energy", "direction": "maximize"},
        constraints=[{"metric": "stress", "operator": "<=", "value": 3e6}],
    )
    assert result["best"]["name"] == "double"
    assert result["best"]["objective_value"] == pytest.approx(2.8e6)
    assert result["infeasible_count"] == 1
    assert result["metric_definitions_sha256"]
    scenarios = result["report"]["scenarios"]
    assert scenarios[0]["metrics"][0]["comparison"]["absolute_delta"] == 0
    assert scenarios[1]["metrics"][0]["comparison"]["relative_delta"] == pytest.approx(
        1
    )
    for scenario in scenarios:
        for metric in scenario["metrics"]:
            assert metric["evidence"] and all(
                item["sha256"] for item in metric["evidence"]
            )
    assert file_hash(root / "checkpoint.json") == checkpoint_before


@pytest.mark.asyncio
async def test_metrics_refuse_output_or_channel_not_collected_by_the_campaign(campaign):
    service, cid = await completed(campaign)
    for change in ({"output_path": "other.out"}, {"voltage_channel": "Unselected"}):
        metrics = definitions()
        metrics[0].update(change)
        with pytest.raises(BackendError) as error:
            service.analyze(cid, metrics=metrics)
        assert error.value.code == "SWEEP_INVALID_ANALYSIS"


@pytest.mark.asyncio
async def test_metrics_reject_tampered_retained_outputs(campaign):
    service, cid = await completed(campaign)
    artifact = service.status(cid, include_report=True)["report"]["scenarios"][0][
        "artifacts"
    ][0]
    from pathlib import Path

    Path(artifact["path"]).write_text("tampered")
    with pytest.raises(BackendError) as error:
        service.analyze(cid, metrics=definitions())
    assert error.value.code == "SWEEP_EVIDENCE_CHANGED"
