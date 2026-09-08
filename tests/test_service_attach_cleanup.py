import asyncio
from types import SimpleNamespace

import pytest

from pscad_mcp.core.backend.base import BackendError, BackendInfo
from pscad_mcp.core.service import PscadService


class AttachBackend:
    name = "legacy"
    version = "4.6.2"

    def __init__(self, failure=None):
        self.failure = failure
        self.owns_process = False
        self.calls = []
        self.quit_fails = failure == "owned"

    @property
    def session_details(self):
        return {
            "mode": "managed-launch",
            "managed_pid": 4242 if self.owns_process else None,
        }

    async def attach(self):
        self.calls.append("attach")
        if self.failure == "ordinary":
            raise BackendError(
                "CONNECTION_FAILED", "No process was acquired.", self.name, "attach"
            )
        self.owns_process = True
        if self.failure == "owned":
            try:
                await self.quit()
            except RuntimeError as error:
                raise BackendError(
                    "ATTACH_CLEANUP_FAILED",
                    "The launched process could not be closed.",
                    self.name,
                    "attach",
                ) from error
        return BackendInfo(self.name, self.version, True, True, False, True, True)

    async def quit(self):
        self.calls.append("quit")
        if self.quit_fails:
            self.quit_fails = False
            raise RuntimeError("First owned quit failed")
        self.owns_process = False

    async def list_projects(self):
        self.calls.append("business")
        return []

    async def heartbeat(self):
        raise AssertionError("Pending cleanup must not probe a failed connection")


def test_owned_attach_failure_keeps_cleanup_handle_but_denies_business_and_reattach():
    failed = AttachBackend("owned")
    healthy = AttachBackend()
    created = []

    def factory():
        backend = failed if not created else healthy
        created.append(backend)
        return backend

    service = PscadService(factory, executor=SimpleNamespace(snapshot=dict))

    async def exercise():
        with pytest.raises(BackendError, match="could not be closed"):
            await service.attach_local()
        assert service._backend is None
        assert getattr(service, "_pending_cleanup_backend", None) is failed
        state = await service.status()
        assert state["connected"] is False
        assert state["pending_cleanup"] is True
        assert state["session"]["managed_pid"] == 4242
        with pytest.raises(RuntimeError, match="not connected"):
            await service.list_projects()
        with pytest.raises(BackendError, match="cleanup"):
            await service.attach_local()
        assert created == [failed]
        assert failed.calls == ["attach", "quit"]
        with pytest.raises(BackendError, match="cleanup"):
            await service.disconnect()
        failed.quit_fails = True
        with pytest.raises(RuntimeError):
            await service.quit_pscad(confirm=True)
        assert service._pending_cleanup_backend is failed
        await service.quit_pscad(confirm=True)
        assert service._pending_cleanup_backend is None
        await service.attach_local()
        assert created == [failed, healthy]
        assert service._backend is healthy
        await service.quit_pscad(confirm=True)

    asyncio.run(exercise())


def test_attach_failure_without_owned_resource_still_clears_backend():
    backend = AttachBackend("ordinary")
    service = PscadService(lambda: backend)

    async def exercise():
        with pytest.raises(BackendError):
            await service.attach_local()
        assert service._backend is None
        assert getattr(service, "_pending_cleanup_backend", None) is None
        assert backend.calls == ["attach"]

    asyncio.run(exercise())


def test_service_shutdown_closes_pending_owned_launch():
    backend = AttachBackend("owned")
    service = PscadService(lambda: backend)

    async def exercise():
        with pytest.raises(BackendError):
            await service.attach_local()
        await service.shutdown()
        assert service._pending_cleanup_backend is None
        assert service._backend is None

    asyncio.run(exercise())


def test_repair_cleans_pending_backend_before_selecting_replacement():
    failed = AttachBackend("owned")
    healthy = AttachBackend()
    choices = iter([failed, healthy])
    resets = []
    service = PscadService(
        lambda: next(choices),
        executor=SimpleNamespace(
            snapshot=dict, healthy=True, reset=lambda: resets.append(True)
        ),
    )

    async def exercise():
        with pytest.raises(BackendError):
            await service.attach_local()
        await service.repair_connection()
        assert failed.calls == ["attach", "quit", "quit"]
        assert healthy.calls == ["attach"]
        assert service._pending_cleanup_backend is None
        assert service._backend is healthy
        assert resets == [True]
        await service.quit_pscad(confirm=True)

    asyncio.run(exercise())
