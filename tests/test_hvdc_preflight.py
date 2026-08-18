import asyncio

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.preflight import ensure_output_ready, verify_required_result_selectors


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


def test_required_result_selectors_require_explicit_output_inspection():
    profile = {
        "profile_version": 2,
        "result_channels": [{"canonical": "dc_voltage", "path": "Main/Vdc", "units": "kV"}],
        "metric_roles": {"dc_voltage": "dc_voltage"},
    }

    class Backend:
        pass

    with pytest.raises(BackendError) as raised:
        asyncio.run(verify_required_result_selectors(Backend(), "derived", profile, ["dc_voltage"]))
    assert raised.value.code == "HVDC_CAPABILITY_UNAVAILABLE"


def test_required_result_selectors_reject_missing_or_mismatched_channel():
    profile = {
        "profile_version": 2,
        "result_channels": [{"canonical": "dc_voltage", "path": "Main/Vdc", "call_id": 1, "units": "kV"}],
        "metric_roles": {"dc_voltage": "dc_voltage"},
    }

    class Backend:
        async def get_output_channels(self, project_name):
            return [{"path": "Main/Vdc", "call_id": 1, "units": "pu"}]

    with pytest.raises(BackendError) as raised:
        asyncio.run(verify_required_result_selectors(Backend(), "derived", profile, ["dc_voltage"]))
    assert raised.value.code == "HVDC_MAPPING_MISSING"


def test_required_result_selectors_return_verified_channel_evidence():
    profile = {
        "profile_version": 2,
        "result_channels": [{"canonical": "dc_voltage", "path": "Main/Vdc", "call_id": 1, "units": "kV"}],
        "metric_roles": {"dc_voltage": "dc_voltage"},
    }

    class Backend:
        async def get_output_channels(self, project_name):
            return [{"path": "Main/Vdc", "call_id": 1, "units": "kV", "description": "Vdc"}]

    result = asyncio.run(verify_required_result_selectors(Backend(), "derived", profile, ["dc_voltage"]))
    assert result["verified"] is True
    assert result["required"][0]["observed"]["description"] == "Vdc"
