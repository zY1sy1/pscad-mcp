"""Explicitly opted-in licensed PSCAD acceptance for the generic blueprint builder."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("PSCAD_MCP_BLUEPRINT_ACCEPTANCE") != "1",
    reason="requires PSCAD_MCP_BLUEPRINT_ACCEPTANCE=1 and licensed PSCAD inputs",
)


def _required_path(name: str, *, directory: bool = False) -> Path:
    raw = os.getenv(name)
    if not raw:
        pytest.fail(f"{name} is required for blueprint licensed acceptance")
    path = Path(raw).expanduser().resolve()
    if (directory and not path.is_dir()) or (not directory and not path.is_file()):
        pytest.fail(f"{name} does not identify the required {'directory' if directory else 'file'}")
    return path


def test_generic_blueprint_builder_live_acceptance():
    from pscad_mcp.builders.blueprint.service import BlueprintBuilderService
    from pscad_mcp.core.connection_manager import pscad_manager

    workspace = _required_path("PSCAD_MCP_WORKSPACE", directory=True)
    source = _required_path("PSCAD_MCP_BLUEPRINT_SOURCE", directory=True)
    blueprint_path = _required_path("PSCAD_MCP_BLUEPRINT_JSON")
    target = os.getenv("PSCAD_MCP_BLUEPRINT_TARGET", "BlueprintAcceptance")
    blueprint = json.loads(blueprint_path.read_text(encoding="utf-8"))
    service = BlueprintBuilderService(pscad_manager.service, workspace_root=workspace)

    async def run() -> dict:
        planned = await service.plan_project(blueprint, str(source), target)
        started = await service.build_project(planned["plan_hash"], blueprint, str(source), target, confirm=True)
        return await service.wait_for_build(started["build_id"])

    result = asyncio.run(run())
    assert result["state"] in {"acceptance_passed", "published"}
    assert result["result"]["source_integrity"] is True
    assert result["result"]["run_through_acceptance"] is True

