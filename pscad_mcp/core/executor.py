import asyncio
import threading
import logging
from typing import Any, Callable, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("pscad-mcp.executor")


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
        self.healthy = True
        self._com_initializer = com_initializer or _initialize_windows_com
        self.executor = self._new_executor()

    def _new_executor(self) -> ThreadPoolExecutor:
        """Create the single COM-initialized worker used for PSCAD calls."""
        return ThreadPoolExecutor(
            max_workers=1,
            initializer=self._com_initializer,
            thread_name_prefix="pscad-com",
        )

    async def run_safe(self, func: Callable, *args, timeout: float = None, **kwargs) -> Any:
        """Execute a PSCAD call in a separate thread with a watchdog timeout.

        Args:
            func: The callable to execute.
            *args: Positional arguments for func.
            timeout: Override the default timeout (seconds). Use for long operations like builds.
        **kwargs: Keyword arguments for func.
        """
        if not self.healthy:
            raise RuntimeError("PSCAD executor is unhealthy; reset it before retrying.")
        effective_timeout = timeout if timeout is not None else self.timeout
        loop = asyncio.get_running_loop()
        func_name = getattr(func, "__name__", str(func))

        def wrapped_call():
            with self.lock:
                return func(*args, **kwargs)

        try:
            return await asyncio.wait_for(
                loop.run_in_executor(self.executor, wrapped_call),
                timeout=effective_timeout
            )
        except asyncio.TimeoutError:
            self.healthy = False
            logger.error(f"PSCAD Command {func_name} timed out after {effective_timeout}s.")
            raise RuntimeError(f"PSCAD timed out during {func_name}. It might be frozen or showing a dialog.")
        except Exception as e:
            logger.error(f"Error in {func_name}: {str(e)}")
            raise

    def reset(self) -> None:
        old_executor = self.executor
        self.executor = self._new_executor()
        self.lock = threading.Lock()
        self.healthy = True
        old_executor.shutdown(wait=False, cancel_futures=True)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


# Global shared executor instance
robust_executor = RobustExecutor()
