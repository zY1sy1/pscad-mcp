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
        def plan_model(self, *args, **kwargs):
            calls.append(("plan", args, kwargs))
            return {"plan_hash": "h", "blueprint": {"name": "cigre_lcc_monopole_v1"}}

        async def build_model(self, *args, **kwargs):
            calls.append(("build", args, kwargs))
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


def test_blank_lcc_wrapper_keeps_request_fields_with_environment_template(monkeypatch):
    calls = []

    class Fake:
        def plan_model(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"plan_hash": "h"}

    monkeypatch.setattr(blank_builder_tools, "_lcc_service", lambda: Fake())
    request = {
        "project_name": "P",
        "ratings": {"power_mw": 1000.0},
        "operation_modes": ["rectifier", "inverter"],
    }

    asyncio.run(blank_builder_tools.plan_blank_lcc_model(request))

    assert calls[0][1]["request"].to_dict()["ratings"]["power_mw"] == 1000.0


def test_blank_lcc_wrapper_forwards_official_template_path(monkeypatch):
    calls = []

    class Fake:
        def plan_model(self, *args, **kwargs):
            calls.append(("plan", args, kwargs))
            return {"plan_hash": "h"}

    monkeypatch.setattr(blank_builder_tools, "_lcc_service", lambda: Fake())
    request = {
        "project_name": "P",
        "folder": "F",
        "template_path": "C:/examples/Cigre_LCC_Bidirectional.pscx",
    }

    asyncio.run(blank_builder_tools.plan_blank_lcc_model(request))

    assert calls[0][2]["template_path"] == request["template_path"]


def test_blank_builder_singletons_are_shutdown_without_initialization(monkeypatch):
    calls = []

    class Fake:
        async def shutdown(self, *, timeout_s):
            calls.append(timeout_s)

    monkeypatch.setattr(blank_builder_tools, "_lcc_instance", Fake())
    monkeypatch.setattr(blank_builder_tools, "_mmc_instance", Fake())
    monkeypatch.setattr(blank_builder_tools, "_backend", object())

    asyncio.run(blank_builder_tools.shutdown_blank_builder_services(timeout_s=0.25))

    assert calls == [0.25, 0.25]
    assert blank_builder_tools._lcc_instance is None
    assert blank_builder_tools._mmc_instance is None


def test_blank_plan_wrappers_preserve_native_fault_contract(monkeypatch):
    class FakeLcc:
        def plan_model(self, *args, **kwargs):
            return {
                "plan_hash": "h",
                "fault": {"kind": "inverter_ac_three_phase", "time_s": 0.8, "duration_s": 0.1},
            }

    class FakeMmc:
        def plan_model(self, *args, **kwargs):
            return {
                "plan_hash": "m",
                "fault": {"kind": "dc_pole_to_pole", "time_s": 0.3, "removal_time_s": 0.5},
                "capabilities": {"template_native_timing": True},
            }

    monkeypatch.setattr(blank_builder_tools, "_lcc_service", lambda: FakeLcc())
    lcc = asyncio.run(blank_builder_tools.plan_blank_lcc_model({"project_name": "P"}))
    monkeypatch.setattr(blank_builder_tools, "_mmc_service", lambda: FakeMmc())
    mmc = asyncio.run(blank_builder_tools.plan_blank_mmc_model({"project_name": "P"}))

    assert lcc["fault_events"][0]["time_s"] == 0.8
    assert mmc["fault_events"][0]["removal_time_s"] == 0.5
    assert mmc["capabilities"]["template_native_timing"] is True


def test_blank_mmc_validation_forwards_template_pair(monkeypatch):
    calls = []

    class Fake:
        def validate_model(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"valid": True}

    monkeypatch.setattr(blank_builder_tools, "_mmc_service", lambda: Fake())

    result = asyncio.run(
        blank_builder_tools.validate_blank_mmc_model(
            "MMC_CASE",
            output_file="MMC_CASE.out",
            template_path="C:/examples/MMC.pscx",
            library_path="C:/examples/intermediate.pslx",
        )
    )

    assert result == {"valid": True}
    assert calls[0][1] == {
        "template_path": "C:/examples/MMC.pscx",
        "library_path": "C:/examples/intermediate.pslx",
    }
