from __future__ import annotations

import asyncio
import logging
import threading
import time
from types import SimpleNamespace

import pytest

from pscad_mcp import tools
import pscad_mcp.main as main_module
import pscad_mcp.runtime as runtime_module
from pscad_mcp.core.connection_manager import PSCADConnectionManager
from pscad_mcp.core.executor import ExecutorClosingError, PendingSettlementError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import PscadService
from pscad_mcp.hvdc.builders.lcc.parametric_service import (
    ParametricLccBuilderService,
)
from pscad_mcp.hvdc.builders.lcc.service import LccBuilderService
from pscad_mcp.hvdc.service import HvdcDomainService
from pscad_mcp.learning.service import LearningRuntime
from pscad_mcp.main import create_server
from pscad_mcp.runtime import (
    PendingCleanupError,
    RuntimeLifecycle,
    SharedRuntimeLifespan,
    shutdown_domain_services,
)


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


def test_default_settlement_phase_closes_executor_admission_first(monkeypatch):
    calls: list[str] = []

    class Executor:
        def begin_shutdown(self):
            calls.append("gate")

        async def wait_for_settlements(self, timeout_s):
            calls.append("wait")
            return False

    monkeypatch.setattr(runtime_module, "robust_executor", Executor())
    runtime = RuntimeLifecycle(
        domain_shutdown=lambda: calls.append("domain"),
        learning_close=lambda: calls.append("learning"),
        connection_shutdown=lambda: calls.append("connection"),
        executor_shutdown=lambda: calls.append("executor"),
        timeout_s=0.2,
    )

    result = asyncio.run(runtime.shutdown())

    assert calls == ["domain", "gate", "wait", "learning", "connection", "executor"]
    assert result["failures"][0]["operation"] == "settlement"


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


def test_domain_shutdown_is_strictly_bounded_when_first_service_swallows_cancel(
    monkeypatch,
):
    calls: list[str] = []

    async def first(timeout_s=5.0):
        calls.append("hvdc")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.Event().wait()

    async def second(timeout_s=5.0):
        calls.append("fixed")

    async def third(timeout_s=5.0):
        calls.append("parametric")

    monkeypatch.setattr("pscad_mcp.tools.hvdc_tools.shutdown_hvdc_service", first)
    monkeypatch.setattr("pscad_mcp.tools.lcc_tools.shutdown_lcc_builder_service", second)
    monkeypatch.setattr(
        "pscad_mcp.tools.lcc_parametric_tools.shutdown_parametric_lcc_builder_service",
        third,
    )

    started = time.perf_counter()
    with pytest.raises(Exception):
        asyncio.run(shutdown_domain_services(timeout_s=0.09))

    assert time.perf_counter() - started < 0.3
    assert calls == ["hvdc", "fixed", "parametric"]


def test_custom_runtime_action_that_swallows_cancel_is_still_bounded():
    calls: list[str] = []

    async def stubborn():
        calls.append("domain")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return

    runtime = RuntimeLifecycle(
        domain_shutdown=stubborn,
        settlement_wait=lambda: calls.append("settlement") or True,
        learning_close=lambda: calls.append("learning"),
        connection_shutdown=lambda: calls.append("connection"),
        executor_shutdown=lambda: calls.append("executor"),
        timeout_s=0.03,
    )
    started = time.perf_counter()
    result = asyncio.run(runtime.shutdown())

    assert time.perf_counter() - started < 0.2
    assert calls == ["domain", "settlement", "learning", "connection", "executor"]
    assert result["failures"][0] == {
        "operation": "domain",
        "exception": "TimeoutError",
    }


def test_live_timed_out_domain_cleanup_blocks_connection_and_executor(caplog):
    calls: list[str] = []
    release: asyncio.Event

    async def exercise():
        nonlocal release
        release = asyncio.Event()

        async def stubborn():
            calls.append("domain")
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue
            raise RuntimeError("SECRET-LATE-CLEANUP")

        runtime = RuntimeLifecycle(
            domain_shutdown=stubborn,
            settlement_wait=lambda: calls.append("settlement") or True,
            learning_close=lambda: calls.append("learning"),
            connection_shutdown=lambda: calls.append("connection"),
            executor_shutdown=lambda: calls.append("executor"),
            timeout_s=0.03,
        )
        result = await runtime.shutdown()
        assert runtime.pending_cleanup_count == 1
        assert calls == ["domain", "settlement", "learning"]
        assert result == {
            "code": "SHUTDOWN_INCOMPLETE",
            "failures": [
                {"operation": "domain", "exception": "PendingCleanupError"},
                {"operation": "connection", "exception": "PendingCleanupError"},
                {"operation": "executor", "exception": "PendingCleanupError"},
            ],
        }
        release.set()
        final_result = await asyncio.wait_for(
            asyncio.wrap_future(runtime.finalization_future),
            timeout=1,
        )
        assert runtime.pending_cleanup_count == 0
        assert final_result == {
            "code": "SHUTDOWN_INCOMPLETE",
            "failures": [
                {"operation": "domain", "exception": "RuntimeError"},
            ],
        }
        assert await runtime.shutdown() == final_result

    with caplog.at_level(logging.ERROR, logger="pscad-mcp.runtime"):
        asyncio.run(exercise())
    assert "SECRET" not in caplog.text


def test_deferred_finalizer_retries_serially_when_cleanup_is_pending_again():
    releases = [asyncio.Event(), asyncio.Event()]
    attempts = 0
    active = 0
    max_active = 0
    calls: list[str] = []

    async def domain():
        nonlocal attempts, active, max_active
        index = attempts
        attempts += 1
        active += 1
        max_active = max(max_active, active)
        try:
            if index < len(releases):
                while not releases[index].is_set():
                    try:
                        await releases[index].wait()
                    except asyncio.CancelledError:
                        continue
        finally:
            active -= 1

    runtime = RuntimeLifecycle(
        domain_shutdown=domain,
        settlement_wait=lambda: calls.append("settlement") or True,
        learning_close=lambda: calls.append("learning"),
        connection_shutdown=lambda: calls.append("connection"),
        executor_shutdown=lambda: calls.append("executor"),
        timeout_s=0.02,
    )

    async def exercise():
        try:
            first = await runtime.shutdown()
            assert first["failures"][0] == {
                "operation": "domain",
                "exception": "PendingCleanupError",
            }
            releases[0].set()
            for _ in range(100):
                if attempts == 2 and runtime.pending_cleanup_count == 1:
                    break
                await asyncio.sleep(0.005)
            assert attempts == 2
            assert runtime.pending_cleanup_count == 1
            assert not runtime.finalization_future.done()
            releases[1].set()
            final = await asyncio.wait_for(
                asyncio.wrap_future(runtime.finalization_future),
                timeout=1,
            )
            assert final == {"code": "SHUTDOWN_COMPLETE", "failures": []}
        finally:
            for release in releases:
                release.set()
            if not runtime.finalization_future.done():
                await asyncio.wait_for(
                    asyncio.wrap_future(runtime.finalization_future),
                    timeout=1,
                )

    asyncio.run(exercise())
    assert attempts == 3
    assert max_active == 1
    assert calls.count("connection") == 1
    assert calls.count("executor") == 1


def test_domain_aggregate_propagates_live_cleanup_after_attempting_all(monkeypatch):
    calls: list[str] = []

    async def exercise():
        release = asyncio.Event()

        async def first(timeout_s=5.0):
            calls.append("hvdc")
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue

        async def second(timeout_s=5.0):
            calls.append("fixed")

        async def third(timeout_s=5.0):
            calls.append("parametric")

        monkeypatch.setattr(
            "pscad_mcp.tools.hvdc_tools.shutdown_hvdc_service", first
        )
        monkeypatch.setattr(
            "pscad_mcp.tools.lcc_tools.shutdown_lcc_builder_service", second
        )
        monkeypatch.setattr(
            "pscad_mcp.tools.lcc_parametric_tools.shutdown_parametric_lcc_builder_service",
            third,
        )
        with pytest.raises(PendingCleanupError) as raised:
            await shutdown_domain_services(timeout_s=0.09)
        assert calls == ["hvdc", "fixed", "parametric"]
        assert any(not task.done() for task in raised.value.pending_tasks)
        release.set()
        await asyncio.gather(*raised.value.pending_tasks, return_exceptions=True)

    asyncio.run(exercise())


def test_shutdown_action_timeout_keyword_respects_parameter_kind():
    def positional_only(timeout_s="positional-default", /):
        return timeout_s

    def var_positional(*timeout_s):
        return timeout_s

    def keyword_capable(timeout_s="keyword-default"):
        return timeout_s

    def arbitrary_keywords(**values):
        return values

    assert runtime_module._invoke_shutdown_action(positional_only, 0.25) == (
        "positional-default"
    )
    assert runtime_module._invoke_shutdown_action(var_positional, 0.25) == ()
    assert runtime_module._invoke_shutdown_action(keyword_capable, 0.25) == 0.25
    assert runtime_module._invoke_shutdown_action(arbitrary_keywords, 0.25) == {
        "timeout_s": 0.25
    }


@pytest.mark.parametrize("service_kind", ["hvdc", "fixed_lcc", "parametric_lcc"])
def test_real_tool_shutdown_helper_propagates_pending_cleanup_to_runtime(
    monkeypatch, tmp_path, service_kind
):
    modules = {
        "hvdc": (tools.hvdc_tools, "_domain_service", "_domain_backend"),
        "fixed_lcc": (tools.lcc_tools, "_builder_service", "_builder_backend"),
        "parametric_lcc": (
            tools.lcc_parametric_tools,
            "_service_instance",
            "_service_backend",
        ),
    }

    async def exercise():
        release = asyncio.Event()
        released_leases: list[str] = []

        class Lease:
            token = "lease-token"

            def release(self, token):
                released_leases.append(token)

        async def stubborn_child():
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue

        child = asyncio.create_task(stubborn_child())
        if service_kind == "hvdc":
            service = HvdcDomainService(
                path_policy=PathPolicy(workspace_root=str(tmp_path))
            )
            service._scenario_cleanup_tasks["pending"] = child
        elif service_kind == "fixed_lcc":
            service = LccBuilderService(object(), workspace_root=tmp_path)
            service._tasks["pending"] = child
            service._leases["pending"] = Lease()
        else:
            service = ParametricLccBuilderService(workspace_root=tmp_path)
            service._tasks["pending"] = child
            service._leases["pending"] = Lease()

        for module, service_name, backend_name in modules.values():
            monkeypatch.setattr(module, service_name, None)
            monkeypatch.setattr(module, backend_name, None)
        module, service_name, backend_name = modules[service_kind]
        monkeypatch.setattr(module, service_name, service)
        monkeypatch.setattr(module, backend_name, object())

        calls: list[str] = []
        runtime = RuntimeLifecycle(
            domain_shutdown=lambda: shutdown_domain_services(timeout_s=0.12),
            settlement_wait=lambda: calls.append("settlement") or True,
            learning_close=lambda: calls.append("learning"),
            connection_shutdown=lambda: calls.append("connection"),
            executor_shutdown=lambda: calls.append("executor"),
            timeout_s=0.2,
        )
        try:
            result = await runtime.shutdown()
            assert calls == ["settlement", "learning"]
            assert result == {
                "code": "SHUTDOWN_INCOMPLETE",
                "failures": [
                    {"operation": "domain", "exception": "PendingCleanupError"},
                    {
                        "operation": "connection",
                        "exception": "PendingCleanupError",
                    },
                    {"operation": "executor", "exception": "PendingCleanupError"},
                ],
            }
            assert runtime.pending_cleanup_count == 1
            assert runtime.state == "closing"
            assert runtime._finalizer_task is not None
            assert runtime._finalizer_started.is_set()
            assert getattr(module, service_name) is service
            assert released_leases == []
        finally:
            release.set()
            await child
        final_result = await asyncio.wait_for(
            asyncio.wrap_future(runtime.finalization_future),
            timeout=1,
        )
        assert runtime.pending_cleanup_count == 0
        assert getattr(module, service_name) is None
        assert getattr(module, backend_name) is None
        expected_leases = [] if service_kind == "hvdc" else ["lease-token"]
        assert released_leases == expected_leases
        assert calls == [
            "settlement",
            "learning",
            "settlement",
            "learning",
            "connection",
            "executor",
        ]
        expected_final = {"code": "SHUTDOWN_COMPLETE", "failures": []}
        assert final_result == expected_final
        assert runtime.state == "closed"
        final_result["failures"].append(
            {"operation": "mutated", "exception": "MutatedError"}
        )
        assert await runtime.shutdown() == expected_final

    asyncio.run(exercise())


def test_runtime_shutdown_is_once_across_two_threads_and_event_loops():
    calls: list[str] = []
    calls_lock = threading.Lock()
    entered = threading.Event()
    release = threading.Event()

    async def domain():
        with calls_lock:
            calls.append("domain")
        entered.set()
        await asyncio.to_thread(release.wait, 1)

    runtime = RuntimeLifecycle(
        domain_shutdown=domain,
        settlement_wait=lambda: True,
        learning_close=lambda: None,
        connection_shutdown=lambda: None,
        executor_shutdown=lambda: None,
        timeout_s=0.5,
    )
    results: list[dict] = []
    errors: list[BaseException] = []

    def run():
        try:
            results.append(asyncio.run(asyncio.wait_for(runtime.shutdown(), 1)))
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=run, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    assert entered.wait(0.2)
    release.set()
    for thread in threads:
        thread.join(1)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert calls == ["domain"]
    assert results == [
        {"code": "SHUTDOWN_COMPLETE", "failures": []},
        {"code": "SHUTDOWN_COMPLETE", "failures": []},
    ]
    results[0]["failures"].append({"operation": "x", "exception": "Y"})
    assert results[1]["failures"] == []


def test_cancelled_shutdown_owner_wakes_waiter_without_repeating_actions():
    calls: list[str] = []
    entered = asyncio.Event()

    async def domain():
        calls.append("domain")
        entered.set()
        await asyncio.Event().wait()

    runtime = RuntimeLifecycle(
        domain_shutdown=domain,
        settlement_wait=lambda: True,
        learning_close=lambda: None,
        connection_shutdown=lambda: None,
        executor_shutdown=lambda: None,
        timeout_s=1,
    )

    async def exercise():
        owner = asyncio.create_task(runtime.shutdown())
        await entered.wait()
        waiter = asyncio.create_task(runtime.shutdown())
        await asyncio.sleep(0)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        return await asyncio.wait_for(waiter, 0.2)

    result = asyncio.run(exercise())
    assert calls == ["domain"]
    assert result == {
        "code": "SHUTDOWN_INCOMPLETE",
        "failures": [{"operation": "lifecycle", "exception": "CancelledError"}],
    }


def test_fatal_shutdown_owner_wakes_waiter_and_preserves_owner_exception():
    class FatalShutdown(BaseException):
        pass

    entered = asyncio.Event()
    release = asyncio.Event()

    async def domain():
        entered.set()
        await release.wait()
        raise FatalShutdown

    runtime = RuntimeLifecycle(
        domain_shutdown=domain,
        settlement_wait=lambda: True,
        learning_close=lambda: None,
        connection_shutdown=lambda: None,
        executor_shutdown=lambda: None,
        timeout_s=1,
    )

    async def exercise():
        owner = asyncio.create_task(runtime.shutdown())
        await entered.wait()
        waiter = asyncio.create_task(runtime.shutdown())
        release.set()
        with pytest.raises(FatalShutdown):
            await owner
        return await asyncio.wait_for(waiter, 0.2)

    result = asyncio.run(exercise())
    assert result == {
        "code": "SHUTDOWN_INCOMPLETE",
        "failures": [{"operation": "lifecycle", "exception": "FatalShutdown"}],
    }


def test_shared_lifespan_closes_only_after_last_peer_and_rejects_new_leases():
    calls: list[str] = []
    lifecycle = SimpleNamespace(
        shutdown=lambda: calls.append("shutdown")
        or {"code": "SHUTDOWN_COMPLETE", "failures": []}
    )
    owner = SharedRuntimeLifespan(lifecycle)

    async def exercise():
        first = owner.lifespan(None)
        second = owner.lifespan(None)
        assert await first.__aenter__() == {}
        assert await second.__aenter__() == {}
        await first.__aexit__(None, None, None)
        assert calls == []
        await second.__aexit__(None, None, None)
        assert calls == ["shutdown"]
        third = owner.lifespan(None)
        with pytest.raises(RuntimeError, match="RUNTIME_CLOSING"):
            await third.__aenter__()

    asyncio.run(exercise())


def test_shared_lifespan_rejects_new_lease_while_last_exit_is_closing():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def shutdown():
        entered.set()
        await release.wait()

    owner = SharedRuntimeLifespan(SimpleNamespace(shutdown=shutdown))

    async def exercise():
        first = owner.lifespan(None)
        await first.__aenter__()
        closing = asyncio.create_task(first.__aexit__(None, None, None))
        await entered.wait()
        rejected = owner.lifespan(None)
        with pytest.raises(RuntimeError, match="RUNTIME_CLOSING"):
            await rejected.__aenter__()
        release.set()
        await closing

    asyncio.run(exercise())


def test_shared_lifespan_stays_closing_until_deferred_runtime_finalization():
    calls: list[str] = []
    release = asyncio.Event()
    domain_attempts = 0

    async def domain():
        nonlocal domain_attempts
        domain_attempts += 1
        calls.append(f"domain-{domain_attempts}")
        if domain_attempts == 1:
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue

    runtime = RuntimeLifecycle(
        domain_shutdown=domain,
        settlement_wait=lambda: calls.append("settlement") or True,
        learning_close=lambda: calls.append("learning"),
        connection_shutdown=lambda: calls.append("connection"),
        executor_shutdown=lambda: calls.append("executor"),
        timeout_s=0.03,
    )
    owner = SharedRuntimeLifespan(runtime)

    async def exercise():
        context = owner.lifespan(None)
        await context.__aenter__()
        await context.__aexit__(None, None, None)
        assert owner.state == "closing"
        assert runtime.state == "closing"
        cancelled_waiter = runtime.finalization_future
        independent_waiter = runtime.finalization_future
        with pytest.raises(RuntimeError, match="FINALIZATION_FUTURE_READ_ONLY"):
            independent_waiter.set_result(
                {"code": "FORGED", "failures": []}
            )
        waiters_are_independent = cancelled_waiter is not independent_waiter
        waiter_cancelled = cancelled_waiter.cancel()
        peer_was_cancelled = independent_waiter.cancelled()
        peer_was_done = independent_waiter.done()
        state_after_waiter_cancel = owner.state
        rejected = owner.lifespan(None)
        with pytest.raises(RuntimeError, match="RUNTIME_CLOSING"):
            await rejected.__aenter__()
        release.set()
        await asyncio.sleep(0.1)
        assert waiters_are_independent
        assert waiter_cancelled
        assert not peer_was_cancelled
        assert not peer_was_done
        assert state_after_waiter_cancel == "closing"
        await asyncio.wait_for(
            asyncio.wrap_future(independent_waiter),
            timeout=1,
        )
        for _ in range(20):
            if owner.state == "closed":
                break
            await asyncio.sleep(0)
        assert owner.state == "closed"
        assert runtime.state == "closed"

    asyncio.run(exercise())
    assert calls == [
        "domain-1",
        "settlement",
        "learning",
        "domain-2",
        "settlement",
        "learning",
        "connection",
        "executor",
    ]


def test_cancelled_deferred_finalizer_publishes_failure_and_closes_owner():
    release = asyncio.Event()
    calls: list[str] = []

    async def domain():
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue

    runtime = RuntimeLifecycle(
        domain_shutdown=domain,
        settlement_wait=lambda: calls.append("settlement") or True,
        learning_close=lambda: calls.append("learning"),
        connection_shutdown=lambda: calls.append("connection"),
        executor_shutdown=lambda: calls.append("executor"),
        timeout_s=0.02,
    )
    owner = SharedRuntimeLifespan(runtime)

    async def exercise():
        context = owner.lifespan(None)
        await context.__aenter__()
        await context.__aexit__(None, None, None)
        assert owner.state == "closing"
        finalizer = runtime._finalizer_task
        assert finalizer is not None
        finalizer.cancel()
        await finalizer
        final = await asyncio.wrap_future(runtime.finalization_future)
        assert final == {
            "code": "SHUTDOWN_INCOMPLETE",
            "failures": [
                {"operation": "lifecycle", "exception": "CancelledError"},
            ],
        }
        assert owner.state == "closed"
        assert calls == ["settlement", "learning"]
        release.set()
        await asyncio.gather(
            *runtime._pending_cleanup_snapshot(),
            return_exceptions=True,
        )

    asyncio.run(exercise())


def test_closed_owner_loop_watcher_publishes_fixed_failure_and_closes_owner():
    calls: list[str] = []
    runtime = RuntimeLifecycle(
        domain_shutdown=lambda: None,
        settlement_wait=lambda: True,
        learning_close=lambda: None,
        connection_shutdown=lambda: calls.append("connection"),
        executor_shutdown=lambda: calls.append("executor"),
    )
    owner = SharedRuntimeLifespan(runtime)

    class ClosedLoop:
        @staticmethod
        def is_closed():
            return True

    with runtime._state_lock:
        runtime._state = "closing"
        runtime._deferred = True
        runtime._owner_loop = ClosedLoop()
    with owner._lock:
        owner._state = "closing"
    owner._close_or_follow_deferred_finalization()
    runtime._start_loop_watcher()

    result = runtime.finalization_future.result(timeout=1)
    assert result == {
        "code": "SHUTDOWN_INCOMPLETE",
        "failures": [
            {"operation": "lifecycle", "exception": "EventLoopClosedError"},
        ],
    }
    assert runtime.state == "closed"
    assert owner.state == "closed"
    assert calls == []


def test_last_lifespan_exit_defers_repeated_cancellation_until_shutdown_finishes():
    calls: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def action(name):
        calls.append(name)
        if name == "domain":
            entered.set()
            await release.wait()
        return True

    runtime = RuntimeLifecycle(
        domain_shutdown=lambda: action("domain"),
        settlement_wait=lambda: action("settlement"),
        learning_close=lambda: action("learning"),
        connection_shutdown=lambda: action("connection"),
        executor_shutdown=lambda: action("executor"),
        timeout_s=0.5,
    )
    owner = SharedRuntimeLifespan(runtime)

    async def exercise():
        context = owner.lifespan(None)
        await context.__aenter__()
        exiting = asyncio.create_task(context.__aexit__(None, None, None))
        await entered.wait()
        exiting.cancel()
        await asyncio.sleep(0)
        exiting.cancel()
        assert owner.active_count == 0
        rejected = owner.lifespan(None)
        with pytest.raises(RuntimeError, match="RUNTIME_CLOSING"):
            await rejected.__aenter__()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await exiting

    asyncio.run(exercise())
    assert calls == ["domain", "settlement", "learning", "connection", "executor"]
    assert runtime._result == {"code": "SHUTDOWN_COMPLETE", "failures": []}
    assert owner.state == "closed"


def test_server_factories_share_process_lifespan_without_activating_it():
    first = create_server(environ={})
    second = create_server(environ={})

    assert first._pscad_runtime_owner is second._pscad_runtime_owner
    assert first._pscad_runtime_owner.active_count == 0


def test_two_factory_servers_hold_overlapping_shared_lifespan(monkeypatch):
    calls: list[str] = []
    lifecycle = SimpleNamespace(shutdown=lambda: calls.append("shutdown"))
    owner = SharedRuntimeLifespan(lifecycle)
    monkeypatch.setattr(main_module, "PROCESS_RUNTIME_LIFESPAN", owner)
    first = create_server(environ={})
    second = create_server(environ={})

    async def exercise():
        first_context = first.settings.lifespan(first)
        second_context = second.settings.lifespan(second)
        await first_context.__aenter__()
        await second_context.__aenter__()
        await first_context.__aexit__(None, None, None)
        assert calls == []
        await second_context.__aexit__(None, None, None)

    asyncio.run(exercise())
    assert calls == ["shutdown"]


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
        begin_shutdown=lambda: calls.append("gate"),
        wait_for_settlements=lambda timeout_s: calls.append("settlement") or True,
        pending_settlements=lambda: (),
        shutdown_if_settled=lambda: calls.append("executor"),
    )

    asyncio.run(manager.shutdown(timeout_s=0.2))

    assert calls == ["gate", "settlement", "connection", "executor"]


def test_connection_manager_pending_shutdown_keeps_connection_and_worker():
    calls: list[str] = []
    worker = object()
    manager = object.__new__(PSCADConnectionManager)
    manager._service = SimpleNamespace(shutdown=lambda: calls.append("connection"))
    manager._executor = SimpleNamespace(
        executor=worker,
        begin_shutdown=lambda: calls.append("gate"),
        wait_for_settlements=lambda timeout_s: calls.append("settlement") or False,
        pending_settlements=lambda: (object(),),
        shutdown_if_settled=lambda: calls.append("executor"),
    )

    with pytest.raises(PendingSettlementError):
        asyncio.run(manager.shutdown(timeout_s=0.01))

    assert calls == ["gate", "settlement"]
    assert manager._executor.executor is worker


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
