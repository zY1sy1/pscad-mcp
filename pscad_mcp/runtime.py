"""Deterministic, bounded shutdown for MCP-owned runtime resources."""

from __future__ import annotations

import asyncio
import concurrent.futures
from contextlib import asynccontextmanager
import inspect
import logging
import threading
from collections.abc import Callable
from typing import Any

from .core.connection_manager import pscad_manager
from .core.executor import PendingSettlementError, robust_executor
from .learning.service import learning_runtime


logger = logging.getLogger("pscad-mcp.runtime")
ShutdownAction = Callable[[], Any]


class DomainShutdownError(RuntimeError):
    """Report bounded domain-shutdown failures without exception messages."""

    def __init__(self, failures: list[dict[str, str]]) -> None:
        self.failures = tuple(dict(item) for item in failures)
        super().__init__("One or more domain services failed to shut down.")


def _consume_task_result(task: asyncio.Future[Any]) -> None:
    try:
        task.result()
    except BaseException:
        pass


def _cancel_and_consume(task: asyncio.Future[Any]) -> None:
    task.cancel()
    try:
        task.get_loop().call_soon(task.cancel)
    except RuntimeError:
        pass
    task.add_done_callback(_consume_task_result)


async def _run_bounded(action: ShutdownAction, timeout_s: float) -> Any:
    """Bound an async action without awaiting cancellation-resistant cleanup."""
    result = action()
    if not inspect.isawaitable(result):
        return result
    task = asyncio.ensure_future(result)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout_s)
    except asyncio.CancelledError:
        _cancel_and_consume(task)
        raise
    if task in done:
        return task.result()
    _cancel_and_consume(task)
    raise TimeoutError


async def shutdown_domain_services(timeout_s: float = 5.0) -> None:
    """Attempt every domain singleton in a stable dependency order."""
    from .tools.hvdc_tools import shutdown_hvdc_service
    from .tools.lcc_parametric_tools import (
        shutdown_parametric_lcc_builder_service,
    )
    from .tools.lcc_tools import shutdown_lcc_builder_service

    actions = (
        ("hvdc", shutdown_hvdc_service),
        ("fixed_lcc", shutdown_lcc_builder_service),
        ("parametric_lcc", shutdown_parametric_lcc_builder_service),
    )
    failures: list[dict[str, str]] = []
    action_timeout_s = timeout_s / (len(actions) + 1)
    for operation, action in actions:
        try:
            await _run_bounded(action, action_timeout_s)
        except Exception as error:
            failures.append(
                {"operation": operation, "exception": type(error).__name__}
            )
    if failures:
        raise DomainShutdownError(failures)


class RuntimeLifecycle:
    """Coordinate one idempotent, ordered shutdown of process resources."""

    def __init__(
        self,
        *,
        domain_shutdown: ShutdownAction | None = None,
        settlement_wait: ShutdownAction | None = None,
        learning_close: ShutdownAction | None = None,
        connection_shutdown: ShutdownAction | None = None,
        executor_shutdown: ShutdownAction | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        self.timeout_s = timeout_s
        self._domain_shutdown = domain_shutdown or (
            lambda: shutdown_domain_services(timeout_s=self.timeout_s)
        )
        self._learning_close = learning_close or learning_runtime.close
        self._connection_shutdown = (
            connection_shutdown or pscad_manager.shutdown_connection
        )
        self._executor_shutdown = executor_shutdown or pscad_manager.shutdown_executor
        if settlement_wait is None:
            async def guarded_settlement_wait() -> bool:
                robust_executor.begin_shutdown()
                return await robust_executor.wait_for_settlements(self.timeout_s)

            self._settlement_wait = guarded_settlement_wait
        else:
            self._settlement_wait = settlement_wait
        self._state_lock = threading.Lock()
        self._completion: concurrent.futures.Future[dict[str, Any]] | None = None
        self._result: dict[str, Any] | None = None

    @staticmethod
    def _copy_result(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "code": result["code"],
            "failures": [dict(item) for item in result["failures"]],
        }

    def _publish(
        self,
        completion: concurrent.futures.Future[dict[str, Any]],
        result: dict[str, Any],
    ) -> None:
        stored = self._copy_result(result)
        with self._state_lock:
            self._result = stored
        completion.set_result(self._copy_result(stored))

    async def _shutdown_once(self) -> dict[str, Any]:
        failures: list[dict[str, str]] = []
        actions = (
            ("domain", self._domain_shutdown),
            ("settlement", self._settlement_wait),
            ("learning", self._learning_close),
            ("connection", self._connection_shutdown),
            ("executor", self._executor_shutdown),
        )
        for operation, action in actions:
            try:
                result = await _run_bounded(action, self.timeout_s)
                if operation == "settlement" and result is False:
                    raise PendingSettlementError(
                        "PSCAD executor settlements did not complete in time."
                    )
            except Exception as error:
                failure = {
                    "operation": operation,
                    "exception": type(error).__name__,
                }
                failures.append(failure)
                logger.error(
                    "Runtime shutdown failed for operation=%s exception=%s.",
                    operation,
                    type(error).__name__,
                )
        return {
            "code": "SHUTDOWN_INCOMPLETE" if failures else "SHUTDOWN_COMPLETE",
            "failures": failures,
        }

    async def shutdown(self) -> dict[str, Any]:
        """Run cleanup once across threads and event loops."""
        with self._state_lock:
            if self._result is not None:
                return self._copy_result(self._result)
            completion = self._completion
            owner = completion is None
            if owner:
                completion = concurrent.futures.Future()
                self._completion = completion
        assert completion is not None
        if not owner:
            result = await asyncio.shield(asyncio.wrap_future(completion))
            return self._copy_result(result)
        try:
            result = await self._shutdown_once()
        except asyncio.CancelledError:
            result = {
                "code": "SHUTDOWN_INCOMPLETE",
                "failures": [
                    {"operation": "lifecycle", "exception": "CancelledError"}
                ],
            }
            self._publish(completion, result)
            raise
        except BaseException as error:
            result = {
                "code": "SHUTDOWN_INCOMPLETE",
                "failures": [
                    {"operation": "lifecycle", "exception": type(error).__name__}
                ],
            }
            logger.error(
                "Runtime shutdown failed for operation=lifecycle exception=%s.",
                type(error).__name__,
            )
            self._publish(completion, result)
            raise
        self._publish(completion, result)
        return self._copy_result(result)

    @asynccontextmanager
    async def lifespan(self, _server: Any):
        """FastMCP lifespan adapter."""
        try:
            yield {}
        finally:
            await self.shutdown()


class SharedRuntimeLifespan:
    """Process-wide lease owner for globally shared runtime resources."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self._lock = threading.Lock()
        self._active_count = 0
        self._state = "open"

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active_count

    def _acquire(self) -> None:
        with self._lock:
            if self._state != "open":
                raise RuntimeError("RUNTIME_CLOSING: runtime lifespan is closing.")
            self._active_count += 1

    def _release(self) -> bool:
        with self._lock:
            self._active_count -= 1
            if self._active_count == 0:
                self._state = "closing"
                return True
            return False

    @asynccontextmanager
    async def lifespan(self, _server: Any):
        self._acquire()
        try:
            yield {}
        finally:
            if self._release():
                try:
                    result = self.runtime.shutdown()
                    if inspect.isawaitable(result):
                        await result
                finally:
                    with self._lock:
                        self._state = "closed"


PROCESS_RUNTIME_LIFESPAN = SharedRuntimeLifespan(RuntimeLifecycle())


__all__ = [
    "DomainShutdownError",
    "RuntimeLifecycle",
    "SharedRuntimeLifespan",
    "PROCESS_RUNTIME_LIFESPAN",
    "shutdown_domain_services",
]
