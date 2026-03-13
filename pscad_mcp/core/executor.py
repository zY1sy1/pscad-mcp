import asyncio
import threading
import logging
from typing import Any, Callable
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("pscad-mcp.executor")

class RobustExecutor:
    """
    Implements the Command/Proxy pattern to wrap PSCAD calls
    with timeouts and locks to prevent hangs and deadlocks.
    """
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.lock = threading.Lock()
        # PSCAD is single-threaded via COM; use a single worker executor
        self.executor = ThreadPoolExecutor(max_workers=1)

    async def run_safe(self, func: Callable, *args, **kwargs) -> Any:
        """Execute a PSCAD call in a separate thread with a watchdog timeout."""
        loop = asyncio.get_running_loop()
        func_name = getattr(func, "__name__", str(func))

        def wrapped_call():
            with self.lock:
                return func(*args, **kwargs)

        try:
            return await asyncio.wait_for(
                loop.run_in_executor(self.executor, wrapped_call), 
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"PSCAD Command {func_name} timed out after {self.timeout}s.")
            raise RuntimeError(f"PSCAD timed out during {func_name}. It might be frozen or showing a dialog.")
        except Exception as e:
            logger.error(f"Error in {func_name}: {str(e)}")
            raise


# Global shared executor instance
robust_executor = RobustExecutor()
