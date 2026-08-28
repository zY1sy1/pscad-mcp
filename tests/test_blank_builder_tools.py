import asyncio

from pscad_mcp.main import create_server
from pscad_mcp.tools import blank_builder_tools


def test_blank_lifecycle_tools_are_registered():
    names = {tool.name for tool in create_server(environ={})._tool_manager.list_tools()}
    assert {
        "plan_blank_lcc_model", "build_blank_lcc_model", "get_blank_lcc_build_status", "validate_blank_lcc_model",
        "plan_blank_mmc_model", "build_blank_mmc_model", "get_blank_mmc_build_status", "validate_blank_mmc_model",
    } <= names


def test_blank_lcc_wrapper_forwards_request_and_confirmation(monkeypatch):
    calls = []

    class Fake:
        def plan_model(self, *args):
            calls.append(("plan", args))
            return {"plan_hash": "h", "blueprint": {"name": "cigre_lcc_monopole_v1"}}

        async def build_model(self, *args):
            calls.append(("build", args))
            return {"build_id": "b"}

        def get_build_status(self, *args):
            calls.append(("status", args))
            return {"state": "published"}

        def validate_model(self, *args):
            calls.append(("validate", args))
            return {"valid": True}

    monkeypatch.setattr(blank_builder_tools, "_lcc_service", lambda: Fake())
    request = {"project_name": "P", "folder": "F", "topology": "single_pole_12_pulse"}
    assert asyncio.run(blank_builder_tools.plan_blank_lcc_model(request))["plan_hash"] == "h"
    assert asyncio.run(blank_builder_tools.build_blank_lcc_model(request, "h", True)) == {"build_id": "b"}
    assert calls[0][0] == "plan" and calls[1][0] == "build"
