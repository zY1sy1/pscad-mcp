import asyncio

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.backend.modern import ModernBackend
from pscad_mcp.core.service import PscadService
from tests.backend_fakes import ImmediateExecutor


CHANNEL = {
    "canonical": "dc_voltage",
    "path": "Main/Vdc",
    "call_id": 7,
    "units": "kV",
    "description": "DC voltage",
}


class CreatingBackend:
    def __init__(self):
        self.calls = []

    async def create_output_channel(self, project_name, channel):
        self.calls.append((project_name, dict(channel)))
        return dict(channel)


def test_service_validates_and_forwards_output_channel_creation():
    backend = CreatingBackend()
    service = PscadService(lambda: backend)
    service._backend = backend

    result = asyncio.run(service.create_output_channel("derived", CHANNEL))

    assert result == CHANNEL
    assert backend.calls == [("derived", CHANNEL)]


@pytest.mark.parametrize(
    "channel",
    [
        {},
        {"path": "Main/Vdc", "call_id": True},
        {"path": "Main/Vdc", "call_id": 0},
        {"path": "", "call_id": 1},
        {"path": "Main/Vdc", "unexpected": "value"},
    ],
)
def test_service_rejects_invalid_output_channel_contract(channel):
    backend = CreatingBackend()
    service = PscadService(lambda: backend)
    service._backend = backend

    with pytest.raises(BackendError) as raised:
        asyncio.run(service.create_output_channel("derived", channel))

    assert raised.value.code == "INVALID_ARGUMENT"
    assert backend.calls == []


class VendorProject:
    def __init__(self, *, provider="add_output_channel", existing=()):
        self.channels = [dict(item) for item in existing]
        self.created = []
        if provider == "create_output_channel":
            self.create_output_channel = self._create
        elif provider == "add_output_channel":
            self.add_output_channel = self._create

    def _create(self, channel):
        value = dict(channel)
        self.created.append(value)
        self.channels.append(value)
        return object()

    def output_channels(self):
        return [dict(item) for item in self.channels]


class VendorApp:
    def __init__(self, project):
        self._project = project

    def project(self, name):
        assert name == "derived"
        return self._project


@pytest.mark.parametrize(
    ("backend_type", "provider"),
    [
        (LegacyBackend, "add_output_channel"),
        (ModernBackend, "create_output_channel"),
    ],
)
def test_backends_create_and_read_back_exact_output_channel(backend_type, provider):
    project = VendorProject(provider=provider)
    if backend_type is LegacyBackend:
        backend = backend_type(
            ImmediateExecutor(), version="4.6.2", x64=True, automation_module=False
        )
    else:
        backend = backend_type(
            ImmediateExecutor(),
            version="5.0.2",
            x64=True,
            pscad_module=False,
            psout_module=False,
        )
    backend._app = VendorApp(project)

    result = asyncio.run(backend.create_output_channel("derived", CHANNEL))

    assert result == CHANNEL
    assert project.created == [
        {
            "path": "Main/Vdc",
            "call_id": 7,
            "units": "kV",
            "description": "DC voltage",
        }
    ]


@pytest.mark.parametrize("backend_type", [LegacyBackend, ModernBackend])
def test_backends_reject_duplicate_output_endpoint_before_vendor_write(backend_type):
    project = VendorProject(existing=[CHANNEL])
    if backend_type is LegacyBackend:
        backend = backend_type(
            ImmediateExecutor(), version="4.6.2", x64=True, automation_module=False
        )
    else:
        backend = backend_type(
            ImmediateExecutor(),
            version="5.0.2",
            x64=True,
            pscad_module=False,
            psout_module=False,
        )
    backend._app = VendorApp(project)

    with pytest.raises(BackendError) as raised:
        asyncio.run(backend.create_output_channel("derived", CHANNEL))

    assert raised.value.code == "ALREADY_EXISTS"
    assert project.created == []


@pytest.mark.parametrize("backend_type", [LegacyBackend, ModernBackend])
def test_backends_fail_closed_without_output_creation_provider(backend_type):
    project = VendorProject(provider=None)
    if backend_type is LegacyBackend:
        backend = backend_type(
            ImmediateExecutor(), version="4.6.2", x64=True, automation_module=False
        )
    else:
        backend = backend_type(
            ImmediateExecutor(),
            version="5.0.2",
            x64=True,
            pscad_module=False,
            psout_module=False,
        )
    backend._app = VendorApp(project)

    with pytest.raises(BackendError) as raised:
        asyncio.run(backend.create_output_channel("derived", CHANNEL))

    assert raised.value.code == "CAPABILITY_UNAVAILABLE"
