import asyncio
from pathlib import Path

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


def test_legacy_backend_reads_static_output_metadata_when_provider_is_absent(
    tmp_path: Path,
):
    project = tmp_path / "case.pscx"
    project.write_text(
        """<project name='case' version='4.6.2'>
        <output name='case'><domain name='Time' unit='s'/><analog>
          <channel index='0' id='123:0' name='Vdc' label='' dim='1' unit='kV' min='-2' max='2'/>
          <channel index='1' id='456:0' name='Idc' label='' dim='1' unit='kA' min='-2' max='2'/>
        </analog><digital /></output></project>""",
        encoding="ascii",
    )
    backend = LegacyBackend(
        ImmediateExecutor(),
        version="4.6.2",
        x64=True,
        automation_module=False,
        definition_paths={"case": project},
    )

    async def project_for(_name):
        return object()

    backend._project = project_for
    channels = asyncio.run(backend.get_output_channels("case"))

    assert channels == [
        {
            "path": "Main/Vdc",
            "call_id": 0,
            "units": "kV",
            "description": "Vdc",
        },
        {
            "path": "Main/Idc",
            "call_id": 1,
            "units": "kA",
            "description": "Idc",
        },
    ]


@pytest.mark.parametrize("backend", [
    LegacyBackend(ImmediateExecutor(), version="4.6.2", x64=True, automation_module=False),
    ModernBackend(ImmediateExecutor(), version="5.0.2", x64=True, pscad_module=False, psout_module=False),
])
def test_backends_fail_closed_when_output_metadata_is_not_verified(backend):
    with pytest.raises(BackendError) as raised:
        asyncio.run(backend.get_output_channels("derived"))
    assert raised.value.code in {"CAPABILITY_UNAVAILABLE", "NOT_CONNECTED"}
