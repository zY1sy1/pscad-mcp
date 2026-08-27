from unittest.mock import AsyncMock

import pytest

from pscad_mcp.core.service import PscadService
from pscad_mcp.topology.hashing import topology_sha256
from pscad_mcp.topology.models import TopologySnapshot
from pscad_mcp.topology.service import TopologyService
from tests.topology_fakes import (
    ReadOnlyRecordingBackend,
    topology_with_nearby_dangling_endpoint,
    topology_with_seeded_defects,
)


MINIMAL_PROJECT_XML = """<project name="case" version="4.6.2">
<Definition name="Main"><schematic>
<User classid="UserCmp" id="7" name="R1" defn="master:resistor" x="0" y="0">
<Port name="A" kind="electrical" dim="1" x="0" y="0" />
</User><Wire id="8"><vertex x="0" y="0"/><vertex x="18" y="0"/></Wire>
</schematic></Definition></project>"""


@pytest.mark.asyncio
async def test_service_combines_live_and_saved_without_mutation(tmp_path):
    project = tmp_path / "case.pscx"
    project.write_text(MINIMAL_PROJECT_XML, encoding="utf-8")
    backend = ReadOnlyRecordingBackend(project)
    service = TopologyService(backend)

    result = await service.inspect("case", "Main", mode="conservative")

    assert result.project_name == "case"
    assert result.nets
    assert backend.calls == ["inspect_canvas_topology"]
    assert dict(result.timings_ms).keys() == {
        "live_capture",
        "file_parse",
        "reconcile",
        "connectivity",
    }


@pytest.mark.asyncio
async def test_pscad_service_caches_topology_service_per_connected_backend(tmp_path):
    first_project = tmp_path / "first.pscx"
    second_project = tmp_path / "second.pscx"
    first_project.write_text(MINIMAL_PROJECT_XML, encoding="utf-8")
    second_project.write_text(MINIMAL_PROJECT_XML, encoding="utf-8")
    first_backend = ReadOnlyRecordingBackend(first_project)
    second_backend = ReadOnlyRecordingBackend(second_project)
    candidates = iter((first_backend, second_backend))
    service = PscadService(lambda: next(candidates))

    with pytest.raises(RuntimeError, match="not connected"):
        service.topology_service

    await service.attach_local()
    first = service.topology_service
    assert first is service.topology_service

    await service.disconnect()
    assert service._topology_service is None
    with pytest.raises(RuntimeError, match="not connected"):
        service.topology_service

    await service.attach_local()
    second = service.topology_service
    assert second is not first
    assert second.live_provider.backend is second_backend


@pytest.mark.asyncio
async def test_infer_mode_adds_candidates_without_changing_confirmed_hash():
    source = topology_with_nearby_dangling_endpoint(grid_step=18)
    snapshot = TopologySnapshot(
        "live",
        source.project_name,
        pscad_version=source.pscad_version,
        components=source.components,
        conductors=source.conductors,
        grid_step=source.grid_step,
    )
    backend = AsyncMock()
    backend.inspect_canvas_topology.return_value = snapshot
    service = TopologyService(backend)

    conservative = await service.inspect("case", "Main", mode="conservative")
    inferred = await service.inspect("case", "Main", mode="infer")

    assert conservative.candidate_edges == ()
    assert inferred.candidate_edges
    assert topology_sha256(conservative) == topology_sha256(inferred)


@pytest.mark.asyncio
async def test_diagnose_reports_validity_summary_hash_and_rule_timing():
    topology = topology_with_seeded_defects()
    service = TopologyService(AsyncMock())
    service.inspect = AsyncMock(return_value=topology)

    report = await service.diagnose("case", "Main", mode="conservative")

    assert not report.valid
    assert report.topology_hash == topology_sha256(topology)
    assert dict(report.summary) == {"error": 10, "info": 1, "warning": 5}
    assert "generic_rules" in dict(report.timings_ms)
    service.inspect.assert_awaited_once_with(
        "case",
        "Main",
        mode="conservative",
    )
