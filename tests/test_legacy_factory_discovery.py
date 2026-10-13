from types import SimpleNamespace

import pytest

from pscad_mcp.core import connection_manager
from tests.backend_fakes import ImmediateExecutor


@pytest.mark.asyncio
async def test_repeated_discovery_handles_sdk_replacing_controller_factory_with_module(
    monkeypatch,
):
    class Controller:
        def get_paramlist_names(self, name):
            assert name == "pscad"
            return ["PSCAD 4.6.2 (x64)"]

    sdk = SimpleNamespace()

    def controller():
        sdk.controller = SimpleNamespace(Controller=Controller)
        return Controller()

    sdk.controller = controller
    monkeypatch.setattr(
        connection_manager,
        "_optional_import",
        lambda name: sdk if name == "mhrc.automation" else None,
    )
    monkeypatch.setenv("PSCAD_MCP_BACKEND", "legacy")
    monkeypatch.setenv("PSCAD_MCP_VERSION", "4.6.2")
    monkeypatch.setenv("PSCAD_MCP_X64", "true")
    executor = ImmediateExecutor()
    first = await connection_manager._default_backend_factory(executor)
    second = await connection_manager._default_backend_factory(executor)
    assert first is not second
    assert first.version == second.version == "4.6.2"
    assert first.executor is second.executor is executor
