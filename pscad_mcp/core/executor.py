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
            }

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
        if not self.healthy:
            raise ExecutorUnhealthyError(
                "PSCAD executor is unhealthy; reset it before retrying."
            )
        effective_timeout = timeout if timeout is not None else self.timeout
        loop = asyncio.get_running_loop()
        func_name = getattr(func, "__name__", str(func))
        started_at = time.perf_counter()
        with self._state_lock:
            self.last_operation = func_name
            self.last_error = None
            self.last_timeout_seconds = None

        def wrapped_call():
            with self.lock:
                return func(*args, **kwargs)

        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(self.executor, wrapped_call),
                timeout=effective_timeout,
            )
            logger.debug(
                "PSCAD command %s completed in %.3fs.",
                func_name,
                time.perf_counter() - started_at,
            )
            return result
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
        old_executor = self.executor
        self.executor = self._new_executor()
        self.lock = threading.Lock()
        with self._state_lock:
            self.healthy = True
            self.last_error = None
            self.last_timeout_seconds = None
        old_executor.shutdown(wait=False, cancel_futures=True)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


# Global shared executor instance
robust_executor = RobustExecutor()
