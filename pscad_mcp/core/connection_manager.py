import logging
import importlib
import inspect
import os
from typing import Optional, Any
from .executor import PendingSettlementError, robust_executor
from .pscad_adapter import PscadAdapter
from .backend.legacy import LegacyBackend
from .backend.modern import ModernBackend
from .backend.base import BackendError
from .backend.selector import select_backend
from .pscad_config import PscadLaunchConfig
from .process_inventory import list_pscad_processes
from .service import PscadService

logger = logging.getLogger("pscad-mcp.connection")


def _optional_import(module_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


async def _default_backend_factory() -> Any:
    config = PscadLaunchConfig.from_environ(os.environ)
    legacy_module = _optional_import("mhrc.automation")
    modern_module = _optional_import("mhi.pscad")

    legacy_installations = []
    if legacy_module is not None:
        try:
            legacy_installations = await robust_executor.run_safe(
                lambda: legacy_module.controller().get_paramlist_names("pscad")
            )
        except Exception as exc:
            logger.warning("Legacy PSCAD discovery failed: %s", exc)

    modern_installations = []
    if modern_module is not None:
        try:
            modern_installations = await robust_executor.run_safe(
                modern_module.versions
            )
        except Exception as exc:
            logger.warning("Modern PSCAD discovery failed: %s", exc)

    choice = select_backend(
        os.environ,
        legacy_versions=lambda: legacy_installations,
        modern_versions=lambda: modern_installations,
    )
    if choice.backend == "legacy":
        return LegacyBackend(
            robust_executor,
            version=choice.version,
            x64=choice.x64,
            automation_module=legacy_module if legacy_module is not None else False,
            legacy_wheel=config.legacy_wheel,
            legacy_minimize=config.legacy_minimize,
            legacy_existing_policy=config.legacy_existing_policy,
            process_probe=list_pscad_processes,
        )
    return ModernBackend(
        robust_executor,
        version=choice.version,
        x64=choice.x64,
        pscad_module=modern_module,
        timeout=config.timeout,
    )

class PSCADConnectionManager:
    """
    Singleton Manager for PSCAD lifecycle and connection health.
    """
    _instance: Optional['PSCADConnectionManager'] = None
    _adapter: Optional[PscadAdapter] = None
    _service: Optional[PscadService] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PSCADConnectionManager, cls).__new__(cls)
            cls._instance._adapter = PscadAdapter(robust_executor)
            cls._instance._executor = robust_executor
            cls._instance._service = PscadService(
                _default_backend_factory,
                executor=robust_executor,
            )
        return cls._instance

    async def attach_local(self) -> str:
        """Robustly attach to any local PSCAD instance or launch a new one."""
        try:
            result = await self.service.attach_local()
            backend = self.service.backend
            backend_adapter = getattr(backend, "adapter", None)
            if backend_adapter is not None:
                self._adapter = backend_adapter
            return result
        except BackendError:
            raise
        except Exception as error:
            logger.exception("Attach failed.")
            raise RuntimeError(
                f"Failed to attach to PSCAD: {error}"
            ) from error

    def disconnect(self):
        """Clear temporary raw-proxy compatibility state."""
        self._adapter.disconnect()
        robust_executor.reset()

    @property
    def service(self) -> PscadService:
        if self._service is None:
            raise RuntimeError("PSCAD service is not initialized.")
        return self._service

    async def get_status(self) -> dict:
        return await self.service.status()

    def learning_snapshot(self) -> dict[str, str | None]:
        return self.service.learning_snapshot()

    async def repair_connection(self) -> str:
        result = await self.service.repair_connection()
        return result

    async def quit_pscad(self, *, confirm: bool = False) -> str:
        result = await self.service.quit_pscad(confirm=confirm)
        return result

    @staticmethod
    def error_payload(error: Exception, operation: str) -> dict:
        return PscadService.error_payload(error, operation)

    @property
    def adapter(self) -> PscadAdapter:
        if self._adapter is None:
            raise RuntimeError("PSCAD adapter is not initialized.")
        return self._adapter

    @property
    def connection_info(self) -> dict:
        selected = self.adapter.selected_installation
        return {
            "owns_process": self.adapter.owns_process,
            "selected_version": selected[0] if selected else None,
            "x64": selected[1] if selected else None,
        }

    async def heartbeat(self) -> dict:
        status = await self.get_status()
        return {"alive": status["alive"], "busy": status["busy"]}

    async def shutdown_connection(self) -> None:
        """Release PSCAD only after all worker calls have settled."""
        if self._executor.pending_settlements():
            raise PendingSettlementError(
                "PSCAD connection shutdown is blocked by pending settlements."
            )
        result = self.service.shutdown()
        if hasattr(result, "__await__"):
            await result

    async def shutdown_executor(self) -> None:
        """Close the shared worker without abandoning in-flight calls."""
        self._executor.shutdown_if_settled()

    async def shutdown(self, timeout_s: float = 5.0) -> None:
        """Direct shutdown entry point without invoking the server lifecycle."""
        self._executor.begin_shutdown()
        settled = self._executor.wait_for_settlements(timeout_s)
        if inspect.isawaitable(settled):
            settled = await settled
        if not settled:
            raise PendingSettlementError(
                "PSCAD shutdown is blocked by pending settlements."
            )
        await self.shutdown_connection()
        await self.shutdown_executor()

# Global singleton
pscad_manager = PSCADConnectionManager()
