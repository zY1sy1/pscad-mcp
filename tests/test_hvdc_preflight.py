import asyncio

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.preflight import ensure_output_ready


class OutputBackend:
    def __init__(self, plot_type):
        self.settings = {"PlotType": plot_type}
        self.calls = []

    async def get_project_settings(self, project_name):
        self.calls.append(("get", project_name))
        return dict(self.settings)

    async def set_project_settings(self, project_name, settings):
        self.calls.append(("set", project_name, dict(settings)))
        self.settings.update(settings)


def test_disabled_output_is_not_changed_on_source_project():
    backend = OutputBackend("NONE")
    with pytest.raises(BackendError) as raised:
        asyncio.run(ensure_output_ready(backend, "source", source_project="source", confirm=True))
    assert raised.value.code == "HVDC_CAPABILITY_UNAVAILABLE"
    assert backend.calls == [("get", "source")]


def test_confirmed_derived_project_enables_legacy_out_and_reads_back():
    backend = OutputBackend(0)
    result = asyncio.run(ensure_output_ready(backend, "derived", source_project="source", confirm=True))
    assert result == {"changed": True, "previous": 0, "current": "OUT"}
    assert backend.calls == [
        ("get", "derived"),
        ("set", "derived", {"PlotType": "OUT"}),
        ("get", "derived"),
    ]


@pytest.mark.parametrize("value", ["OUT", "LEGACY", "1", 1, True])
def test_enabled_output_aliases_are_left_unchanged(value):
    backend = OutputBackend(value)
    result = asyncio.run(ensure_output_ready(backend, "derived", source_project="source", confirm=True))
    assert result == {"changed": False, "previous": value, "current": value}
    assert backend.calls == [("get", "derived")]
