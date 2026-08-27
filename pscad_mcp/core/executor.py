import asyncio
import logging
import threading
import time
from typing import Any, Callable, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("pscad-mcp.executor")
_ERROR_TEXT_LIMIT = 512


class ExecutorTimeoutError(RuntimeError):
    """Raised when a PSCAD COM call exceeds its watchdog timeout."""


class ExecutorUnhealthyError(RuntimeError):
    """Raised when a timed-out executor must be reset before reuse."""


class PendingSettlementError(RuntimeError):
    """Raised when shutdown would abandon an unsettled PSCAD worker call."""


class ExecutorClosingError(PendingSettlementError):
    """Raised when a new call is submitted after shutdown begins."""


class ExecutorSettlementToken:
    """Loop-independent identity and completion signal for one worker call."""

    def __init__(self, operation_id: int, generation: int, operation: str):
        self.operation_id = operation_id
        self.generation = generation
        self.operation = operation
        self._settled = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[["ExecutorSettlementToken"], None]] = []

    @property
    def settled(self) -> bool:
        return self._settled.is_set()

    def add_done_callback(
        self,
        callback: Callable[["ExecutorSettlementToken"], None],
    ) -> None:
        call_now = False
        with self._lock:
            if self._settled.is_set():
                call_now = True
            else:
                self._callbacks.append(callback)
        if call_now:
            callback(self)

    def settle(self) -> None:
        callbacks: list[Callable[["ExecutorSettlementToken"], None]]
        with self._lock:
            if self._settled.is_set():
                return
            self._settled.set()
            callbacks = self._callbacks
            self._callbacks = []
        for callback in callbacks:
            callback(self)


def _initialize_windows_com() -> None:
    """Initialize COM when pywin32 is available on the worker platform."""
    try:
        import pythoncom
    except ImportError:
        return
    pythoncom.CoInitialize()


class RobustExecutor:
    """
    Implements the Command/Proxy pattern to wrap PSCAD calls
    with timeouts and locks to prevent hangs and deadlocks.
    """
    def __init__(
        self,
        timeout: float = 30.0,
        com_initializer: Optional[Callable[[], None]] = None,
    ):
        self.timeout = timeout
        self.lock = threading.Lock()
        self._state_lock = threading.Lock()
        self.healthy = True
        self.last_operation: str | None = None
        self.last_error: str | None = None
        self.last_timeout_seconds: float | None = None
        self.reset_generation = 0
        self._active_generations: set[int] = set()
        self._next_operation_id = 0
        self._pending_tokens: set[ExecutorSettlementToken] = set()
        self._closing = False
        self._tokens_by_owner: dict[
            asyncio.Task[Any], set[ExecutorSettlementToken]
        ] = {}
        self.cancel_wait_timeout = min(1.0, max(0.01, timeout))
        self._com_initializer = com_initializer or _initialize_windows_com
        self.executor = self._new_executor()

    def _new_executor(self) -> ThreadPoolExecutor:
        """Create the single COM-initialized worker used for PSCAD calls."""
        return ThreadPoolExecutor(
            max_workers=1,
            initializer=self._com_initializer,
            thread_name_prefix="pscad-com",
        )

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        message = f"{type(error).__name__}: {error}"
        if len(message) <= _ERROR_TEXT_LIMIT:
            return message
        return message[: _ERROR_TEXT_LIMIT - 3] + "..."

    def snapshot(self) -> dict[str, Any]:
        """Return bounded executor state without exposing vendor objects."""
        with self._state_lock:
            return {
                "healthy": self.healthy,
                "last_operation": self.last_operation,
                "last_error": self.last_error,
                "last_timeout_seconds": self.last_timeout_seconds,
                "reset_generation": self.reset_generation,
                "previous_worker_retiring": any(
                    generation != self.reset_generation
                    for generation in self._active_generations
                ),
                "in_flight_calls": sum(
                    1 for token in self._pending_tokens if not token.settled
                ),
            }

    def pending_settlements(self) -> tuple[ExecutorSettlementToken, ...]:
        """Return loop-independent tokens for all unsettled worker calls."""
        with self._state_lock:
            return tuple(
                token for token in self._pending_tokens if not token.settled
            )

    def pending_settlements_for(
        self,
        owner: asyncio.Task[Any],
    ) -> tuple[ExecutorSettlementToken, ...]:
        """Return only unsettled calls issued by the supplied asyncio task."""
        with self._state_lock:
            return tuple(
                token
                for token in self._tokens_by_owner.get(owner, ())
                if not token.settled
            )

    def begin_shutdown(self) -> None:
        """Atomically close admission before inspecting settlements."""
        with self._state_lock:
            self._closing = True

    async def wait_for_settlements(self, timeout_s: float) -> bool:
        """Wait without blocking the event loop until current calls settle."""
        tokens = self.pending_settlements()
        if not tokens:
            return True
        loop = asyncio.get_running_loop()
        changed = asyncio.Event()

        def settled(_: ExecutorSettlementToken) -> None:
            try:
                loop.call_soon_threadsafe(changed.set)
            except RuntimeError:
                pass

        for token in tokens:
            token.add_done_callback(settled)

        async def wait_all() -> None:
            while any(not token.settled for token in tokens):
                changed.clear()
                if any(not token.settled for token in tokens):
                    await changed.wait()

        try:
            await asyncio.wait_for(wait_all(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return False
        return True

    def shutdown_if_settled(self) -> None:
        """Close the worker only when every submitted call has settled."""
        with self._state_lock:
            self._closing = True
            if any(not token.settled for token in self._pending_tokens):
                raise PendingSettlementError(
                    "PSCAD executor shutdown is blocked by pending settlements."
                )
            executor = self.executor
            executor.shutdown(wait=False, cancel_futures=True)

    async def run_safe(
        self,
        func: Callable,
        *args,
        timeout: float = None,
        **kwargs,
    ) -> Any:
        """Execute a PSCAD call in a separate thread with a watchdog timeout.

        Args:
            func: The callable to execute.
            *args: Positional arguments for func.
            timeout: Override the default timeout (seconds). Use for long operations like builds.
        **kwargs: Keyword arguments for func.
        """
        effective_timeout = timeout if timeout is not None else self.timeout
        loop = asyncio.get_running_loop()
        func_name = getattr(func, "__name__", str(func))
        started_at = time.perf_counter()
        owner = asyncio.current_task()
        with self._state_lock:
            if self._closing:
                raise ExecutorClosingError(
                    "PSCAD executor is closing and cannot accept new calls."
                )
            if not self.healthy:
                raise ExecutorUnhealthyError(
                    "PSCAD executor is unhealthy; reset it before retrying."
                )
            generation = self.reset_generation
            self._next_operation_id += 1
            token = ExecutorSettlementToken(
                self._next_operation_id,
                generation,
                func_name,
            )
            self._pending_tokens.add(token)
            if owner is not None:
                self._tokens_by_owner.setdefault(owner, set()).add(token)
            call_lock = self.lock
            self.last_operation = func_name
            self.last_error = None
            self.last_timeout_seconds = None
            worker_started = threading.Event()

            def settle_token() -> None:
                with self._state_lock:
                    self._active_generations.discard(generation)
                    self._pending_tokens.discard(token)
                    if owner is not None:
                        owned = self._tokens_by_owner.get(owner)
                        if owned is not None:
                            owned.discard(token)
                            if not owned:
                                self._tokens_by_owner.pop(owner, None)
                token.settle()

            def wrapped_call():
                worker_started.set()
                with self._state_lock:
                    self._active_generations.add(generation)
                try:
                    with call_lock:
                        return func(*args, **kwargs)
                finally:
                    settle_token()

            try:
                concurrent = self.executor.submit(wrapped_call)
            except BaseException:
                self._pending_tokens.discard(token)
                if owner is not None:
                    owned = self._tokens_by_owner.get(owner)
                    if owned is not None:
                        owned.discard(token)
                        if not owned:
                            self._tokens_by_owner.pop(owner, None)
                token.settle()
                raise

        def queued_submission_finished(completed: Any) -> None:
            if worker_started.is_set():
                return
            if not completed.cancelled():
                try:
                    submission_error = completed.exception()
                except BaseException as error:
                    submission_error = error
                if submission_error is not None:
                    with self._state_lock:
                        self.healthy = False
                        self.last_error = self._bounded_error(submission_error)
            # A completed Future whose wrapper never started cannot reach the
            # wrapper's finally block (for example, cancellation while queued
            # or ThreadPoolExecutor initializer failure). Settle it here.
            settle_token()

        concurrent.add_done_callback(queued_submission_finished)
        submitted = asyncio.wrap_future(concurrent, loop=loop)

        try:
            result = await asyncio.wait_for(
                asyncio.shield(submitted),
                timeout=effective_timeout,
            )
            logger.debug(
                "PSCAD command %s completed in %.3fs.",
                func_name,
                time.perf_counter() - started_at,
            )
            return result
        except asyncio.CancelledError:
            # Cancelling an asyncio wrapper cannot stop a COM call that is
            # already executing in its worker thread. Keep this coroutine
            # pending until the underlying call has truly settled so callers
            # do not release application-wide mutation ownership early.
            try:
                await asyncio.wait_for(
                    asyncio.shield(submitted),
                    timeout=self.cancel_wait_timeout,
                )
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass
            raise
        except asyncio.TimeoutError as error:
            failure = ExecutorTimeoutError(
                f"PSCAD timed out during {func_name}. It might be frozen or "
                "showing a dialog."
            )
            with self._state_lock:
                self.healthy = False
                self.last_error = self._bounded_error(failure)
                self.last_timeout_seconds = effective_timeout
            logger.error(
                "PSCAD command %s timed out after %.3fs (limit %.3fs).",
                func_name,
                time.perf_counter() - started_at,
                effective_timeout,
            )
            raise failure from error
        except Exception as error:
            with self._state_lock:
                self.last_error = self._bounded_error(error)
            logger.exception(
                "PSCAD command %s failed after %.3fs.",
                func_name,
                time.perf_counter() - started_at,
            )
            raise

    def reset(self) -> None:
        new_executor = self._new_executor()
        new_lock = threading.Lock()
        with self._state_lock:
            old_executor = self.executor
            self.executor = new_executor
            self.lock = new_lock
            self.reset_generation += 1
            self.healthy = True
            self.last_error = None
            self.last_timeout_seconds = None
        old_executor.shutdown(wait=False, cancel_futures=True)

    def shutdown(self) -> None:
        with self._state_lock:
            executor = self.executor
        executor.shutdown(wait=False, cancel_futures=True)


# Global shared executor instance
robust_executor = RobustExecutor()
