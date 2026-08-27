from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from pscad_mcp import tools
from pscad_mcp.core.connection_manager import PSCADConnectionManager
from pscad_mcp.core.executor import PendingSettlementError
from pscad_mcp.core.service import PscadService
from pscad_mcp.learning.service import LearningRuntime
from pscad_mcp.main import create_server
from pscad_mcp.runtime import RuntimeLifecycle, shutdown_domain_services


def test_runtime_shutdown_is_ordered_idempotent_and_fail_contained():
    calls: list[str] = []

    async def action(name: str, fail: bool = False) -> bool:
        calls.append(name)
        if fail:
            raise RuntimeError("SECRET-DETAIL")
        return True

    runtime = RuntimeLifecycle(
        domain_shutdown=lambda: action("domain"),
        settlement_wait=lambda: action("settlement"),
        learning_close=lambda: action("learning", fail=True),
        connection_shutdown=lambda: action("connection"),
        executor_shutdown=lambda: calls.append("executor"),
        timeout_s=0.2,
    )
    first = asyncio.run(runtime.shutdown())
    second = asyncio.run(runtime.shutdown())

    assert calls == ["domain", "settlement", "learning", "connection", "executor"]
    assert first["code"] == "SHUTDOWN_INCOMPLETE"
    assert first["failures"] == [
        {"operation": "learning", "exception": "RuntimeError"}
    ]
    assert second == first
    assert "SECRET-DETAIL" not in repr(first)


def test_false_settlement_is_bounded_and_later_guards_are_attempted(caplog):
    calls: list[str] = []

    async def settlement() -> bool:
        calls.append("settlement")
        return False

    async def guarded(name: str) -> None:
        calls.append(name)
        raise PendingSettlementError("TOP-SECRET")

    runtime = RuntimeLifecycle(
        domain_shutdown=lambda: calls.append("domain"),
        settlement_wait=settlement,
        learning_close=lambda: calls.append("learning"),
        connection_shutdown=lambda: guarded("connection"),
        executor_shutdown=lambda: guarded("executor"),
        timeout_s=0.2,
    )
    with caplog.at_level(logging.ERROR, logger="pscad-mcp.runtime"):
        result = asyncio.run(runtime.shutdown())

    assert calls == ["domain", "settlement", "learning", "connection", "executor"]
    assert result == {
        "code": "SHUTDOWN_INCOMPLETE",
        "failures": [
            {"operation": "settlement", "exception": "PendingSettlementError"},
            {"operation": "connection", "exception": "PendingSettlementError"},
            {"operation": "executor", "exception": "PendingSettlementError"},
        ],
    }
    assert "TOP-SECRET" not in caplog.text
    assert "TOP-SECRET" not in repr(result)


def test_domain_shutdown_attempts_all_services_in_fixed_order(monkeypatch):
    calls: list[str] = []

    async def first() -> None:
        calls.append("hvdc")
        raise RuntimeError("secret")

    async def second() -> None:
        calls.append("fixed")

    async def third() -> None:
        calls.append("parametric")

    monkeypatch.setattr("pscad_mcp.tools.hvdc_tools.shutdown_hvdc_service", first)
    monkeypatch.setattr("pscad_mcp.tools.lcc_tools.shutdown_lcc_builder_service", second)
    monkeypatch.setattr(
        "pscad_mcp.tools.lcc_parametric_tools.shutdown_parametric_lcc_builder_service",
        third,
    )

    with pytest.raises(Exception) as raised:
        asyncio.run(shutdown_domain_services())

    assert calls == ["hvdc", "fixed", "parametric"]
    assert "secret" not in str(raised.value)


def test_learning_runtime_close_does_not_initialize_and_closes_existing_service():
    loads: list[str] = []
    runtime = LearningRuntime(lambda: loads.append("loaded"))
    runtime.close()
    assert loads == []

    closed: list[str] = []
    runtime._service = SimpleNamespace(close=lambda: closed.append("closed"))
    runtime.close()
    runtime.close()
    assert closed == ["closed"]
    assert runtime._service is None


@pytest.mark.parametrize(("owns_process", "expected"), [(True, "quit"), (False, "disconnect")])
def test_pscad_service_shutdown_preserves_backend_ownership_policy(owns_process, expected):
    calls: list[str] = []

    class Backend:
        async def quit(self):
            calls.append("quit")

        async def disconnect(self):
            calls.append("disconnect")

    backend = Backend()
    backend.owns_process = owns_process
    service = PscadService(lambda: backend, executor=SimpleNamespace())
    service._backend = backend

    asyncio.run(service.shutdown())

    assert calls == [expected]
    assert service._backend is None


def test_pscad_service_shutdown_failure_keeps_backend_reference():
    class Backend:
        owns_process = True

        async def quit(self):
            raise RuntimeError("cannot quit")

    backend = Backend()
    service = PscadService(lambda: backend, executor=SimpleNamespace())
    service._backend = backend

    with pytest.raises(RuntimeError):
        asyncio.run(service.shutdown())

    assert service._backend is backend


@pytest.mark.parametrize(
    ("module_name", "service_name", "backend_name", "shutdown_name"),
    [
        ("hvdc_tools", "_domain_service", "_domain_backend", "shutdown_hvdc_service"),
        ("lcc_tools", "_builder_service", "_builder_backend", "shutdown_lcc_builder_service"),
        (
            "lcc_parametric_tools",
            "_service_instance",
            "_service_backend",
            "shutdown_parametric_lcc_builder_service",
        ),
    ],
)
def test_tool_shutdown_helpers_do_not_initialize_and_clear_only_after_success(
    monkeypatch, module_name, service_name, backend_name, shutdown_name
):
    module = getattr(tools, module_name)
    monkeypatch.setattr(module, service_name, None)
    monkeypatch.setattr(module, backend_name, None)
    asyncio.run(getattr(module, shutdown_name)())
    assert getattr(module, service_name) is None

    class Service:
        def __init__(self):
            self.fail = True

        async def shutdown(self, timeout_s=5.0):
            if self.fail:
                raise RuntimeError("failed")

    service = Service()
    backend = object()
    monkeypatch.setattr(module, service_name, service)
    monkeypatch.setattr(module, backend_name, backend)
    with pytest.raises(RuntimeError):
        asyncio.run(getattr(module, shutdown_name)())
    assert getattr(module, service_name) is service
    assert getattr(module, backend_name) is backend

    service.fail = False
    asyncio.run(getattr(module, shutdown_name)())
    assert getattr(module, service_name) is None
    assert getattr(module, backend_name) is None


def test_connection_manager_direct_shutdown_composes_guards_once():
    calls: list[str] = []
    manager = object.__new__(PSCADConnectionManager)
    manager._service = SimpleNamespace(shutdown=lambda: calls.append("connection"))
    manager._executor = SimpleNamespace(
        wait_for_settlements=lambda timeout_s: calls.append("settlement") or True,
        pending_settlements=lambda: (),
        shutdown_if_settled=lambda: calls.append("executor"),
    )

    asyncio.run(manager.shutdown(timeout_s=0.2))

    assert calls == ["settlement", "connection", "executor"]


def test_connection_and_executor_guards_do_not_touch_resources_while_pending():
    calls: list[str] = []
    manager = object.__new__(PSCADConnectionManager)
    manager._service = SimpleNamespace(shutdown=lambda: calls.append("connection"))
    manager._executor = SimpleNamespace(
        pending_settlements=lambda: (object(),),
        shutdown_if_settled=lambda: calls.append("executor"),
    )

    with pytest.raises(PendingSettlementError):
        asyncio.run(manager.shutdown_connection())

    assert calls == []


def test_server_factory_installs_runtime_lifespan():
    server = create_server(environ={})

    assert isinstance(server._pscad_runtime, RuntimeLifecycle)
    assert server.settings.lifespan is not None
