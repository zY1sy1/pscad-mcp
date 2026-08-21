from __future__ import annotations

import asyncio

from pscad_mcp.main import create_server
from pscad_mcp.tools import lcc_tools


def test_lcc_tools_are_registered_with_exact_names():
    names = {tool.name for tool in create_server()._tool_manager.list_tools()}

    assert {"plan_lcc_model", "build_lcc_model", "get_lcc_build_status", "validate_lcc_model"} <= names
    assert len(names) == 83


def test_lcc_wrappers_forward_values_through_builder_service(monkeypatch):
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

    monkeypatch.setattr(lcc_tools, "_service", lambda: FakeBuilder())

    assert asyncio.run(lcc_tools.plan_lcc_model("Project", "Folder", 2.0, "bp")) == {"plan_hash": "hash"}
    assert asyncio.run(lcc_tools.build_lcc_model("Project", "hash", "Folder", 2.0, "bp", True)) == {"build_id": "build"}
    assert asyncio.run(lcc_tools.get_lcc_build_status("build")) == {"state": "published"}
    assert asyncio.run(lcc_tools.validate_lcc_model("Project", "bp", "output.pscx")) == {"valid": True}
    assert calls == [
        ("plan", ("Project", "Folder", 2.0, "bp")),
        ("build", ("Project", "hash", "Folder", 2.0, "bp", True)),
        ("status", ("build",)),
        ("validate", ("Project", "bp", "output.pscx")),
    ]
