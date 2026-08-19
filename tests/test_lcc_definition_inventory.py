import asyncio

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.backend.modern import ModernBackend
from pscad_mcp.core.service import PscadService
from tests.backend_fakes import ImmediateExecutor


DEFINITIONS = [
    {
        "scoped_name": "master:source3",
        "ports": [
            {"name": "B", "x": 12, "y": 6, "kind": "electrical", "dimension": 1},
            {"name": "A", "x": -12, "y": 6, "kind": "electrical", "dimension": 1},
        ],
        "parameters": {
            "frequency": {"range": [45.0, 65.0], "units": "Hz"},
            "mode": {"enum": ["ideal", "impedance"]},
        },
        "bounding_box": {"left": -12, "top": -8, "right": 12, "bottom": 8},
    }
]


def test_live_definition_inventory_hash_is_deterministic_across_collection_order():
    from pscad_mcp.hvdc.builders.lcc.inventory import canonicalize_inventory

    first = canonicalize_inventory({"source": "live", "definitions": DEFINITIONS})
    reversed_ports = [
        {
            **DEFINITIONS[0],
            "ports": list(reversed(DEFINITIONS[0]["ports"])),
            "parameters": dict(reversed(list(DEFINITIONS[0]["parameters"].items()))),
        }
    ]
    second = canonicalize_inventory(
        {"source": "live", "definitions": reversed_ports}
    )

    assert first == second
    assert len(first["sha256"]) == 64
    assert first["definitions"][0]["ports"][0]["name"] == "A"


def test_packaged_catalog_cannot_satisfy_live_inventory_requirement():
    from pscad_mcp.hvdc.builders.lcc.inventory import require_live_inventory

    with pytest.raises(BackendError) as raised:
        require_live_inventory(
            {"source": "packaged_catalog", "definitions": DEFINITIONS}
        )

    assert raised.value.code == "DEFINITION_INVENTORY_REQUIRED"


class InventoryBackend:
    async def get_definition_inventory(self, project_name):
        assert project_name == "master"
        return {"source": "live", "definitions": DEFINITIONS}


def test_service_forwards_live_definition_inventory_without_catalog_fallback():
    backend = InventoryBackend()
    service = PscadService(lambda: backend)
    service._backend = backend

    result = asyncio.run(service.get_definition_inventory("master"))

    assert result == {"source": "live", "definitions": DEFINITIONS}


class VendorProject:
    def get_definition_inventory(self):
        return {"definitions": DEFINITIONS}


class VendorApp:
    def __init__(self, project):
        self._project = project

    def project(self, name):
        assert name == "master"
        return self._project


def _backend(backend_type, project):
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
    return backend


@pytest.mark.parametrize("backend_type", [LegacyBackend, ModernBackend])
def test_backends_return_only_provider_backed_live_definition_inventory(backend_type):
    result = asyncio.run(
        _backend(backend_type, VendorProject()).get_definition_inventory("master")
    )

    assert result == {"source": "live", "definitions": DEFINITIONS}


@pytest.mark.parametrize("backend_type", [LegacyBackend, ModernBackend])
def test_backends_fail_closed_without_live_definition_metadata_provider(backend_type):
    with pytest.raises(BackendError) as raised:
        asyncio.run(_backend(backend_type, object()).get_definition_inventory("master"))

    assert raised.value.code == "CAPABILITY_UNAVAILABLE"
