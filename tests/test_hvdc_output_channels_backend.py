import asyncio

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.service import PscadService
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.backend.modern import ModernBackend
from tests.backend_fakes import ImmediateExecutor


class OutputChannelBackend:
    async def get_output_channels(self, project_name):
        return [{"path": "Main/Vdc", "call_id": 7, "units": "kV", "description": "DC voltage"}]


def test_service_forwards_explicit_output_channel_metadata():
    service = PscadService(lambda: OutputChannelBackend())
    service._backend = OutputChannelBackend()
    result = asyncio.run(service.get_output_channels("derived"))
    assert result == [{"path": "Main/Vdc", "call_id": 7, "units": "kV", "description": "DC voltage"}]


@pytest.mark.parametrize("backend", [
    LegacyBackend(ImmediateExecutor(), version="4.6.2", x64=True, automation_module=False),
    ModernBackend(ImmediateExecutor(), version="5.0.2", x64=True, pscad_module=False, psout_module=False),
])
def test_backends_fail_closed_when_output_metadata_is_not_verified(backend):
    with pytest.raises(BackendError) as raised:
        asyncio.run(backend.get_output_channels("derived"))
    assert raised.value.code in {"CAPABILITY_UNAVAILABLE", "NOT_CONNECTED"}
