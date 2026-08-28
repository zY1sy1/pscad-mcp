from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from pscad_mcp.builders.blueprint.corpus_extractor import extract_project
from pscad_mcp.builders.blueprint.corpus_models import CorpusSource
from pscad_mcp.builders.blueprint.corpus_schema import parse_corpus_spec
from pscad_mcp.builders.blueprint.corpus_verifier import verify_live_inventory
from pscad_mcp.builders.blueprint.corpus_writer import canonical_json


ROOT = Path(__file__).parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "blueprint_corpus" / "minimal.pscx"
SPEC_PATH = ROOT / "pscad_mcp" / "assets" / "corpora" / "moxing_v1" / "source-spec.json"
_LIVE_ENV = ("PSCAD_MCP_CORPUS_SOURCE", "PSCAD_MCP_WORKSPACE", "PSCAD_MCP_VERSION")


def fixture_graph(tmp_path: Path):
    source_path = tmp_path / "minimal.pscx"
    shutil.copyfile(FIXTURE, source_path)
    content = source_path.read_bytes()
    source = CorpusSource(
        project_id="minimal",
        basename=source_path.name,
        byte_length=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        pscad_versions=("4.6.2",),
        dependencies=(),
    )
    return extract_project(tmp_path, source)


def matching_inventory(graph) -> dict:
    definition_map = {definition.key: definition for definition in graph.definitions}
    definitions = {}
    for definition in graph.definitions:
        definitions[definition.key] = {
            "parameters": {
                parameter.name: {"resolved": True, "units": parameter.units or None}
                for parameter in definition.parameters
            },
            "ports": {
                port.name: {
                    "kind": port.type or port.model or port.mode or "unknown",
                    "dimension": port.dimension,
                }
                for port in definition.ports
            },
        }
    components = []
    for runtime_id, component in enumerate(graph.components, 1):
        definition = definition_map.get(component.definition_key)
        parameter_metadata = {
            name: {
                "resolved": True,
                "units": next(
                    (
                        parameter.units or None
                        for parameter in definition.parameters
                        if parameter.name == name
                    ),
                    None,
                )
                if definition is not None
                else None,
            }
            for name in component.parameters
        }
        ports = {
            port.name: {
                "name": port.name,
                "x": component.location[0] + port.offset[0],
                "y": component.location[1] + port.offset[1],
                "kind": port.type or port.model or port.mode or "unknown",
                "dimension": port.dimension,
            }
            for port in (() if definition is None else definition.ports)
        }
        definitions.setdefault(component.definition_key, {"parameters": {}, "ports": {}})
        components.append(
            {
                "id": runtime_id,
                "logical_id": component.key,
                "name": component.name,
                "definition": component.definition_key,
                "canvas": component.canvas_key,
                "location": list(component.location),
                "orientation": component.orientation,
                "parameters": dict(component.parameters),
                "parameter_metadata": parameter_metadata,
                "ports": ports,
                "resolved": component.resolved,
            }
        )
    return {
        "pscad_version": graph.pscad_version,
        "definitions": definitions,
        "components": components,
    }


class MatchingInspectionService:
    def __init__(self, graph) -> None:
        self.inventory = matching_inventory(graph)
        self.calls: list[tuple] = []

    async def status(self):
        self.calls.append(("status",))
        return {"backend": "fake", "version": self.inventory["pscad_version"], "licensed": True}

    async def get_blueprint_inventory(self, project_name: str, inspection_profile: str | None):
        self.calls.append(("get_blueprint_inventory", project_name, inspection_profile))
        return copy.deepcopy(self.inventory)


@pytest.mark.asyncio
async def test_live_verification_matches_without_mutating_offline_graph(tmp_path):
    graph = fixture_graph(tmp_path)
    service = MatchingInspectionService(graph)
    before = canonical_json(graph.to_dict())

    result = await verify_live_inventory(graph, service, project_name=graph.name)

    assert result.live_verified is True
    assert result.status == "verified"
    assert all(check.status == "matched" for check in result.checks)
    assert {check.kind for check in result.checks} >= {
        "project",
        "pscad_version",
        "definitions",
        "components",
        "canvases",
        "parameters",
        "ports",
    }
    assert service.calls == [
        ("status",),
        ("get_blueprint_inventory", graph.name, "corpus-existing-project-v1"),
    ]
    assert canonical_json(graph.to_dict()) == before


@pytest.mark.asyncio
async def test_live_mismatch_is_explicit_and_never_rewrites_offline_graph(tmp_path):
    graph = fixture_graph(tmp_path)
    service = MatchingInspectionService(graph)
    service.inventory["components"][0]["parameters"]["Kp"] = "changed"
    before = canonical_json(graph.to_dict())

    result = await verify_live_inventory(graph, service, project_name=graph.name)

    assert result.live_verified is False
    assert result.status == "failed"
    assert any(check.kind == "parameters" and check.status == "mismatched" for check in result.checks)
    assert canonical_json(graph.to_dict()) == before


@pytest.mark.skipif(
    os.getenv("PSCAD_MCP_CORPUS_LIVE") != "1" or not all(os.getenv(name) for name in _LIVE_ENV),
    reason="requires PSCAD_MCP_CORPUS_LIVE=1, source root, workspace, and explicit PSCAD version",
)
def test_live_moxing_inventory_is_read_only_and_source_preserving():
    from pscad_mcp.core.connection_manager import PSCADConnectionManager

    source_root = Path(os.environ["PSCAD_MCP_CORPUS_SOURCE"]).resolve(strict=True)
    workspace = Path(os.environ["PSCAD_MCP_WORKSPACE"]).resolve(strict=True)
    assert source_root == workspace or workspace in source_root.parents
    spec = parse_corpus_spec(json.loads(SPEC_PATH.read_text(encoding="ascii")))
    assert os.environ["PSCAD_MCP_VERSION"] in {
        version for source in spec.entry_points for version in source.pscad_versions
    }
    before = {
        source.basename: hashlib.sha256((source_root / source.basename).read_bytes()).hexdigest()
        for source in spec.entry_points
    }

    async def run() -> None:
        manager = PSCADConnectionManager()
        service = manager.service
        await manager.attach_local()
        status = await service.status()
        try:
            assert status["licensed"] is True
            await service.load_projects([str(source_root / source.basename) for source in spec.entry_points])
            for source in spec.entry_points:
                graph = extract_project(source_root, source)
                result = await verify_live_inventory(graph, service, project_name=graph.name)
                assert result.live_verified is True, result.to_dict()
        finally:
            if status.get("owns_process"):
                await service.quit_pscad(confirm=True)
            else:
                await service.disconnect()

    asyncio.run(run())
    after = {
        source.basename: hashlib.sha256((source_root / source.basename).read_bytes()).hexdigest()
        for source in spec.entry_points
    }
    assert after == before
