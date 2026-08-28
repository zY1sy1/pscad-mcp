from __future__ import annotations

import asyncio

from pscad_mcp.main import create_server
from pscad_mcp.tools import blueprint_tools


BLUEPRINT_TOOLS = {
    "plan_pscad_project_build",
    "build_pscad_project",
    "get_pscad_project_build_status",
    "validate_pscad_project_build",
}


def test_blueprint_tools_are_registered_with_exact_names():
    names = {tool.name for tool in create_server()._tool_manager.list_tools()}
    assert BLUEPRINT_TOOLS <= names
    assert len(names) == 97


def test_blueprint_wrappers_forward_complete_values(monkeypatch):
    calls = []

    class FakeBuilder:
        async def plan_project(self, *args):
            calls.append(("plan", args))
            return {"plan_hash": "hash"}

        async def build_project(self, *args, **kwargs):
            calls.append(("build", args, kwargs))
            return {"build_id": "build"}

        def get_build_status(self, *args):
            calls.append(("status", args))
            return {"state": "published"}

        async def validate_project_build(self, **kwargs):
            calls.append(("validate", kwargs))
            return {"valid": True}

    monkeypatch.setattr(blueprint_tools, "_service", lambda: FakeBuilder())
    blueprint = {"identity": {"name": "bp"}}
    overrides = {"breaker": {"Name": "BRK"}}

    assert asyncio.run(blueprint_tools.plan_pscad_project_build(blueprint, "source", "Target", overrides)) == {"plan_hash": "hash"}
    assert asyncio.run(blueprint_tools.build_pscad_project("hash", blueprint, "source", "Target", overrides, True)) == {"build_id": "build"}
    assert asyncio.run(blueprint_tools.get_pscad_project_build_status("build")) == {"state": "published"}
    assert asyncio.run(blueprint_tools.validate_pscad_project_build("build", None)) == {"valid": True}
    assert calls == [
        ("plan", (blueprint, "source", "Target", overrides)),
        ("build", ("hash", blueprint, "source", "Target", overrides), {"confirm": True}),
        ("status", ("build",)),
        ("validate", {"build_id": "build", "staging_path": None}),
    ]
