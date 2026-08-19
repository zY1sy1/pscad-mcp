from __future__ import annotations

import asyncio

from pscad_mcp.main import create_server
from pscad_mcp.tools import mmc_tools


def test_mmc_stage_a_tools_are_registered_without_stage_c_design_tool():
    names = {tool.name for tool in create_server()._tool_manager.list_tools()}

    assert {"plan_mmc_model", "build_mmc_model", "get_mmc_build_status", "validate_mmc_model"} <= names
    assert "design_mmc_model" not in names
    assert len(names) == 81


def test_mmc_wrappers_forward_values_through_builder_service(monkeypatch):
    calls = []

    class FakeBuilder:
        def plan_model(self, *args):
            calls.append(("plan", args))
            return {"plan_hash": "hash"}

        async def build_model(self, *args):
            calls.append(("build", args))
            return {"build_id": "build"}

        def get_build_status(self, *args):
            calls.append(("status", args))
            return {"state": "published"}

        def validate_model(self, *args):
            calls.append(("validate", args))
            return {"valid": True}

    monkeypatch.setattr(mmc_tools, "_service", lambda: FakeBuilder())

    assert asyncio.run(mmc_tools.plan_mmc_model("Project", "Folder", 2.0, "bp")) == {"plan_hash": "hash"}
    assert asyncio.run(mmc_tools.build_mmc_model("Project", "hash", "Folder", 2.0, "bp", True)) == {"build_id": "build"}
    assert asyncio.run(mmc_tools.get_mmc_build_status("build")) == {"state": "published"}
    assert asyncio.run(mmc_tools.validate_mmc_model("Project", "bp", "output.psout")) == {"valid": True}
    assert calls == [
        ("plan", ("Project", "Folder", 2.0, "bp")),
        ("build", ("Project", "hash", "Folder", 2.0, "bp", True)),
        ("status", ("build",)),
        ("validate", ("Project", "bp", "output.psout")),
    ]
