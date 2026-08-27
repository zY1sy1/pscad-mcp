"""Deterministic, bounded shutdown for MCP-owned runtime resources."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
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
BoundedTaskTracker = Callable[[asyncio.Future[Any]], None]
_BOUNDED_TASK_TRACKER: contextvars.ContextVar[BoundedTaskTracker | None] = (
    contextvars.ContextVar("pscad_mcp_bounded_task_tracker", default=None)
)


class DomainShutdownError(RuntimeError):
    """Report bounded domain-shutdown failures without exception messages."""

    def __init__(self, failures: list[dict[str, str]]) -> None:
        self.failures = tuple(dict(item) for item in failures)
        super().__init__("One or more domain services failed to shut down.")


class PendingCleanupError(RuntimeError):
    """Signal that timed-out cleanup remains live and dependencies are unsafe."""

    def __init__(self, tasks: tuple[asyncio.Future[Any], ...]) -> None:
        self.pending_tasks = tuple(task for task in tasks if not task.done())
        for task in self.pending_tasks:
            task.add_done_callback(_consume_task_result)
        super().__init__("Runtime cleanup remains pending.")


class _FinalizationProxy(concurrent.futures.Future[dict[str, Any]]):
    """Cancelable observer that cannot mutate runtime-owned completion state."""

    def set_result(self, result: dict[str, Any]) -> None:
        raise RuntimeError("FINALIZATION_FUTURE_READ_ONLY")

    def set_exception(self, exception: BaseException) -> None:
        raise RuntimeError("FINALIZATION_FUTURE_READ_ONLY")

    def _publish_result(self, result: dict[str, Any]) -> None:
        super().set_result(result)

    def _publish_exception(self, exception: BaseException) -> None:
        super().set_exception(exception)


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


def _invoke_shutdown_action(action: ShutdownAction, timeout_s: float) -> Any:
    """Pass a service budget when supported while preserving test injections."""
    try:
        parameters = inspect.signature(action).parameters.values()
    except (TypeError, ValueError):
        parameters = ()
    supports_timeout = any(
        (
            parameter.name == "timeout_s"
            and parameter.kind
            in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        )
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    if supports_timeout:
        return action(timeout_s=timeout_s)
    return action()


async def _run_bounded(action: ShutdownAction, timeout_s: float) -> Any:
    """Bound an async action without awaiting cancellation-resistant cleanup."""
    result = action()
    if not inspect.isawaitable(result):
        return result
    task = asyncio.ensure_future(result)
    tracker = _BOUNDED_TASK_TRACKER.get()
    if tracker is not None:
        tracker(task)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout_s)
    except asyncio.CancelledError:
        _cancel_and_consume(task)
        raise
    if task in done:
        return task.result()
    _cancel_and_consume(task)
    await asyncio.sleep(0)
    if not task.done():
        raise PendingCleanupError((task,))
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
    pending_tasks: list[asyncio.Future[Any]] = []
    action_timeout_s = max(0.0, timeout_s) / (len(actions) + 1)
    service_timeout_s = action_timeout_s / 2
    for operation, action in actions:
        try:
            await _run_bounded(
                lambda action=action: _invoke_shutdown_action(
                    action,
                    service_timeout_s,
                ),
                action_timeout_s,
            )
        except PendingCleanupError as error:
            pending_tasks.extend(error.pending_tasks)
            failures.append(
                {"operation": operation, "exception": "PendingCleanupError"}
            )
        except Exception as error:
            failures.append(
                {"operation": operation, "exception": type(error).__name__}
            )
    live_tasks = tuple(task for task in pending_tasks if not task.done())
    if live_tasks:
        raise PendingCleanupError(live_tasks)
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
        self._latest_result: dict[str, Any] | None = None
        self._finalization: concurrent.futures.Future[dict[str, Any]] = (
            concurrent.futures.Future()
        )
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._state = "open"
        self._deferred = False
        self._finalizer_task: asyncio.Task[None] | None = None
        self._finalizer_wakeup: asyncio.Event | None = None
        self._finalizer_started_async: asyncio.Event | None = None
        self._finalizer_started = threading.Event()
        self._finalization_done = threading.Event()
        self._loop_watcher: threading.Thread | None = None
        self._pending_cleanup_tasks: set[asyncio.Future[Any]] = set()
        self._bounded_action_tasks: set[asyncio.Future[Any]] = set()

    @property
    def finalization_future(self) -> concurrent.futures.Future[dict[str, Any]]:
        proxy = _FinalizationProxy()

        def forward(
            source: concurrent.futures.Future[dict[str, Any]],
        ) -> None:
            if proxy.cancelled():
                return
            try:
                result = source.result()
                proxy._publish_result(self._copy_result(result))
            except concurrent.futures.InvalidStateError:
                pass
            except BaseException as error:
                try:
                    proxy._publish_exception(error)
                except concurrent.futures.InvalidStateError:
                    pass

        self._finalization.add_done_callback(forward)
        return proxy

    def _subscribe_finalization(
        self,
        callback: Callable[[concurrent.futures.Future[dict[str, Any]]], Any],
    ) -> None:
        self._finalization.add_done_callback(callback)

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    @property
    def pending_cleanup_count(self) -> int:
        with self._state_lock:
            return sum(not task.done() for task in self._pending_cleanup_tasks)

    @property
    def bounded_action_count(self) -> int:
        with self._state_lock:
            return sum(not task.done() for task in self._bounded_action_tasks)

    def _bounded_action_finished(self, task: asyncio.Future[Any]) -> None:
        _consume_task_result(task)
        with self._state_lock:
            self._bounded_action_tasks.discard(task)

    def _track_bounded_action(self, task: asyncio.Future[Any]) -> None:
        if task.done():
            _consume_task_result(task)
            return
        with self._state_lock:
            self._bounded_action_tasks.add(task)
        task.add_done_callback(self._bounded_action_finished)

    def _pending_cleanup_finished(self, task: asyncio.Future[Any]) -> None:
        _consume_task_result(task)
        with self._state_lock:
            self._pending_cleanup_tasks.discard(task)
            loop = self._owner_loop
            wakeup = self._finalizer_wakeup
        if loop is not None and wakeup is not None:
            try:
                loop.call_soon_threadsafe(wakeup.set)
            except RuntimeError:
                pass

    def _track_pending_cleanup(
        self,
        tasks: tuple[asyncio.Future[Any], ...],
    ) -> None:
        live = tuple(task for task in tasks if not task.done())
        with self._state_lock:
            self._pending_cleanup_tasks.update(live)
        for task in live:
            task.add_done_callback(self._pending_cleanup_finished)

    def _pending_cleanup_snapshot(self) -> tuple[asyncio.Future[Any], ...]:
        with self._state_lock:
            return tuple(
                task for task in self._pending_cleanup_tasks if not task.done()
            )

    @staticmethod
    def _requires_deferred_cleanup(result: dict[str, Any]) -> bool:
        return any(
            failure.get("exception") == "PendingCleanupError"
            for failure in result["failures"]
        )

    def _watch_owner_loop(self) -> None:
        while not self._finalization_done.wait(0.01):
            with self._state_lock:
                loop = self._owner_loop
            if loop is not None and loop.is_closed():
                self._publish_final(
                    {
                        "code": "SHUTDOWN_INCOMPLETE",
                        "failures": [
                            {
                                "operation": "lifecycle",
                                "exception": "EventLoopClosedError",
                            }
                        ],
                    }
                )
                self._detach_tasks_from_closed_loop()
                return

    @staticmethod
    def _suppress_reported_destroy_warning(task: asyncio.Future[Any]) -> None:
        # The owner loop is already closed, so these tasks cannot be resumed or
        # cancelled safely. Suppress only their already-reported pending-task
        # diagnostic; never close or drive a user coroutine from this thread.
        if not task.done() and hasattr(task, "_log_destroy_pending"):
            try:
                task._log_destroy_pending = False  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                pass

    def _detach_tasks_from_closed_loop(self) -> None:
        with self._state_lock:
            pending = tuple(self._pending_cleanup_tasks)
            bounded = tuple(self._bounded_action_tasks)
            finalizer = self._finalizer_task
            self._pending_cleanup_tasks.clear()
            self._bounded_action_tasks.clear()
            self._finalizer_task = None
            self._finalizer_wakeup = None
            self._finalizer_started_async = None
            self._owner_loop = None
            self._loop_watcher = None
        for task in dict.fromkeys((*pending, *bounded)):
            self._suppress_reported_destroy_warning(task)
            try:
                task.remove_done_callback(self._pending_cleanup_finished)
            except (AttributeError, RuntimeError):
                pass
            try:
                task.remove_done_callback(self._bounded_action_finished)
            except (AttributeError, RuntimeError):
                pass
        if finalizer is not None:
            self._suppress_reported_destroy_warning(finalizer)
            try:
                finalizer.remove_done_callback(self._finalizer_finished)
            except (AttributeError, RuntimeError):
                pass

    def _start_loop_watcher(self) -> None:
        with self._state_lock:
            current = self._loop_watcher
            if current is not None and current.is_alive():
                return
            watcher = threading.Thread(
                target=self._watch_owner_loop,
                name="pscad-runtime-loop-watcher",
                daemon=True,
            )
            self._loop_watcher = watcher
        watcher.start()

    async def _wait_for_pending_cleanup(self) -> None:
        wakeup = self._finalizer_wakeup
        assert wakeup is not None
        while self._pending_cleanup_snapshot():
            wakeup.clear()
            if not self._pending_cleanup_snapshot():
                return
            await wakeup.wait()

    async def _run_deferred_finalizer(self) -> None:
        self._finalizer_started.set()
        started_async = self._finalizer_started_async
        if started_async is not None:
            started_async.set()
        try:
            while True:
                await self._wait_for_pending_cleanup()
                result = await self._shutdown_once()
                if self._requires_deferred_cleanup(result):
                    with self._state_lock:
                        self._latest_result = self._copy_result(result)
                    continue
                self._publish_final(result)
                return
        except asyncio.CancelledError:
            self._publish_final(
                {
                    "code": "SHUTDOWN_INCOMPLETE",
                    "failures": [
                        {
                            "operation": "lifecycle",
                            "exception": "CancelledError",
                        }
                    ],
                }
            )
        except GeneratorExit:
            raise
        except BaseException as error:
            logger.error(
                "Runtime shutdown failed for operation=lifecycle exception=%s.",
                type(error).__name__,
            )
            self._publish_final(
                {
                    "code": "SHUTDOWN_INCOMPLETE",
                    "failures": [
                        {
                            "operation": "lifecycle",
                            "exception": type(error).__name__,
                        }
                    ],
                }
            )

    def _finalizer_finished(self, task: asyncio.Task[None]) -> None:
        failure_type: str | None = None
        if task.cancelled():
            failure_type = "CancelledError"
        else:
            try:
                task.result()
            except BaseException as error:
                if not self._finalizer_started.is_set():
                    failure_type = type(error).__name__
        started_async = self._finalizer_started_async
        if started_async is not None:
            started_async.set()
        if failure_type is not None:
            self._publish_final(
                {
                    "code": "SHUTDOWN_INCOMPLETE",
                    "failures": [
                        {
                            "operation": "lifecycle",
                            "exception": failure_type,
                        }
                    ],
                }
            )

    async def _start_deferred_finalizer(self) -> bool:
        with self._state_lock:
            current = self._finalizer_task
            if current is None:
                self._finalizer_wakeup = asyncio.Event()
                self._finalizer_started_async = asyncio.Event()
                current = asyncio.create_task(self._run_deferred_finalizer())
                self._finalizer_task = current
            started_async = self._finalizer_started_async
        assert started_async is not None
        current.add_done_callback(self._finalizer_finished)
        self._start_loop_watcher()
        cancelled = False
        while not started_async.is_set():
            try:
                await asyncio.shield(started_async.wait())
            except asyncio.CancelledError:
                cancelled = True
        return cancelled

    @staticmethod
    def _copy_result(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "code": result["code"],
            "failures": [dict(item) for item in result["failures"]],
        }

    def _publish_initial(
        self,
        completion: concurrent.futures.Future[dict[str, Any]],
        result: dict[str, Any],
    ) -> None:
        stored = self._copy_result(result)
        with self._state_lock:
            self._latest_result = stored
        if not completion.done():
            completion.set_result(self._copy_result(stored))

    def _publish_final(self, result: dict[str, Any]) -> None:
        stored = self._copy_result(result)
        completion: concurrent.futures.Future[dict[str, Any]] | None
        with self._state_lock:
            if self._result is not None:
                return
            self._result = stored
            self._latest_result = stored
            self._state = "closed"
            self._deferred = False
            completion = self._completion
        if completion is not None and not completion.done():
            completion.set_result(self._copy_result(stored))
        if not self._finalization.done():
            self._finalization.set_result(self._copy_result(stored))
        self._finalization_done.set()

    async def _publish_deferred(
        self,
        completion: concurrent.futures.Future[dict[str, Any]],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        with self._state_lock:
            self._deferred = True
            self._latest_result = self._copy_result(result)
        cancelled = await self._start_deferred_finalizer()
        with self._state_lock:
            finalized = self._result is not None
            final_result = (
                self._copy_result(self._result)
                if self._result is not None
                else None
            )
        if not finalized:
            self._publish_initial(completion, result)
        if cancelled:
            raise asyncio.CancelledError
        return final_result if final_result is not None else self._copy_result(result)

    async def _shutdown_once(self) -> dict[str, Any]:
        tracker_token = _BOUNDED_TASK_TRACKER.set(self._track_bounded_action)
        try:
            return await self._shutdown_actions()
        finally:
            try:
                _BOUNDED_TASK_TRACKER.reset(tracker_token)
            except ValueError:
                # A coroutine abandoned with an already-closed owner loop can
                # later receive GeneratorExit from a different GC context.
                # The loop cannot run more work, so no tracker can leak into it.
                pass

    async def _shutdown_actions(self) -> dict[str, Any]:
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
                pending = self._pending_cleanup_snapshot()
                if operation in {"connection", "executor"} and pending:
                    raise PendingCleanupError(pending)
                result = await _run_bounded(action, self.timeout_s)
                if operation == "settlement" and result is False:
                    raise PendingSettlementError(
                        "PSCAD executor settlements did not complete in time."
                    )
            except PendingCleanupError as error:
                self._track_pending_cleanup(error.pending_tasks)
                failure = {
                    "operation": operation,
                    "exception": "PendingCleanupError",
                }
                failures.append(failure)
                logger.error(
                    "Runtime shutdown failed for operation=%s exception=%s.",
                    operation,
                    "PendingCleanupError",
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
                self._owner_loop = asyncio.get_running_loop()
                self._state = "closing"
            elif completion.done() and self._latest_result is not None:
                return self._copy_result(self._latest_result)
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
            self._publish_final(result)
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
            self._publish_final(result)
            raise
        if self._requires_deferred_cleanup(result):
            result = await self._publish_deferred(completion, result)
        else:
            self._publish_final(result)
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

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

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

    async def _shutdown_runtime(self) -> Any:
        result = self.runtime.shutdown()
        if inspect.isawaitable(result):
            return await result
        return result

    def _mark_closed(self, _future: Any = None) -> None:
        with self._lock:
            self._state = "closed"

    def _close_or_follow_deferred_finalization(self) -> None:
        subscribe = getattr(self.runtime, "_subscribe_finalization", None)
        if callable(subscribe):
            subscribe(self._mark_closed)
            return
        finalization = getattr(self.runtime, "finalization_future", None)
        if isinstance(finalization, concurrent.futures.Future):
            if finalization.done() and not finalization.cancelled():
                self._mark_closed()
            else:
                def close_when_complete(future: Any) -> None:
                    if not future.cancelled():
                        self._mark_closed(future)

                finalization.add_done_callback(close_when_complete)
            return
        self._mark_closed()

    async def _finish_shutdown(self) -> None:
        shutdown_task = asyncio.create_task(self._shutdown_runtime())
        cancelled = False
        failure: BaseException | None = None
        try:
            while not shutdown_task.done():
                try:
                    await asyncio.shield(shutdown_task)
                except asyncio.CancelledError:
                    cancelled = True
                except BaseException as error:
                    failure = error
                    break
            if failure is None:
                try:
                    shutdown_task.result()
                except BaseException as error:
                    failure = error
        finally:
            self._close_or_follow_deferred_finalization()
        if failure is not None:
            raise failure
        if cancelled:
            raise asyncio.CancelledError

    @asynccontextmanager
    async def lifespan(self, _server: Any):
        self._acquire()
        try:
            yield {}
        finally:
            if self._release():
                await self._finish_shutdown()


PROCESS_RUNTIME_LIFESPAN = SharedRuntimeLifespan(RuntimeLifecycle())


__all__ = [
    "DomainShutdownError",
    "RuntimeLifecycle",
    "SharedRuntimeLifespan",
    "PROCESS_RUNTIME_LIFESPAN",
    "PendingCleanupError",
    "shutdown_domain_services",
]
