"""Deterministic, bounded shutdown for MCP-owned runtime resources."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import inspect
import logging
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
    for operation, action in actions:
        try:
            await asyncio.wait_for(action(), timeout=timeout_s)
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
        self._settlement_wait = settlement_wait or (
            lambda: robust_executor.wait_for_settlements(self.timeout_s)
        )
        self._learning_close = learning_close or learning_runtime.close
        self._connection_shutdown = (
            connection_shutdown or pscad_manager.shutdown_connection
        )
        self._executor_shutdown = executor_shutdown or pscad_manager.shutdown_executor
        self._lock = asyncio.Lock()
        self._result: dict[str, Any] | None = None

    @staticmethod
    async def _invoke(action: ShutdownAction) -> Any:
        result = action()
        if inspect.isawaitable(result):
            return await result
        return result

    async def shutdown(self) -> dict[str, Any]:
        """Run every cleanup phase once and cache its bounded summary."""
        async with self._lock:
            if self._result is not None:
                return {
                    "code": self._result["code"],
                    "failures": [dict(item) for item in self._result["failures"]],
                }
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
                    result = await asyncio.wait_for(
                        self._invoke(action), timeout=self.timeout_s
                    )
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
            self._result = {
                "code": "SHUTDOWN_INCOMPLETE" if failures else "SHUTDOWN_COMPLETE",
                "failures": failures,
            }
            return {
                "code": self._result["code"],
                "failures": [dict(item) for item in failures],
            }

    @asynccontextmanager
    async def lifespan(self, _server: Any):
        """FastMCP lifespan adapter."""
        try:
            yield {}
        finally:
            await self.shutdown()


__all__ = [
    "DomainShutdownError",
    "RuntimeLifecycle",
    "shutdown_domain_services",
]
