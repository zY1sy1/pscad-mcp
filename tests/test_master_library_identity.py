import asyncio
import hashlib

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.service import PscadService
from tests.backend_fakes import ImmediateExecutor


def test_master_identity_uses_connected_installation_without_changing_registry(tmp_path):
    master = tmp_path / "master.pslx"
    master.write_text("<project name='master'/>")
    unrelated = tmp_path / "not_installed.pslx"
    unrelated.write_text("<project name='other'/>")
    backend = LegacyBackend(ImmediateExecutor(), version="4.6.2", x64=True, automation_module=False,
                            definition_paths={"master": unrelated})
    backend._app = object()
    registry = object()
    backend._audited_master_registry = registry

    async def discover():
        return master

    backend._discover_master_library = discover
    assert callable(getattr(backend, "get_master_library_identity", None)), "Read-only Master identity is missing"
    identity = asyncio.run(backend.get_master_library_identity())
    assert identity["master_path"] == str(master.resolve())
    assert identity["master_sha256"] == hashlib.sha256(master.read_bytes()).hexdigest()
    assert backend._audited_master_registry is registry
    assert backend.definition_paths == {"master": unrelated}


def test_master_identity_requires_a_connected_backend():
    backend = LegacyBackend(ImmediateExecutor(), version="4.6.2", x64=True, automation_module=False)
    assert callable(getattr(backend, "get_master_library_identity", None))
    with pytest.raises(BackendError):
        asyncio.run(backend.get_master_library_identity())


def test_master_identity_rejects_a_different_managed_installation(tmp_path):
    configured = tmp_path / "configured" / "master.pslx"
    configured.parent.mkdir()
    configured.write_text("configured")
    installed = tmp_path / "connected" / "master.pslx"
    installed.parent.mkdir()
    installed.write_text("connected")
    backend = LegacyBackend(ImmediateExecutor(), version="4.6.2", x64=True, automation_module=False)
    backend._app = object()
    backend._managed_executable = str(installed.parent / "bin" / "Pscad.exe")

    async def discover():
        return configured

    backend._discover_master_library = discover
    with pytest.raises(BackendError, match="connected"):
        asyncio.run(backend.get_master_library_identity())


def test_service_forwards_master_identity_without_reselecting_backend():
    class Backend:
        async def get_master_library_identity(self):
            return {"master_path": "installed", "master_sha256": "a" * 64}

    def forbidden_factory():
        raise AssertionError("The read-only call must not select a backend")

    service = PscadService(forbidden_factory)
    service._backend = Backend()
    assert callable(getattr(service, "get_master_library_identity", None))
    assert asyncio.run(service.get_master_library_identity())["master_path"] == "installed"
