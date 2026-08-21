from __future__ import annotations

import asyncio

from pscad_mcp.core.backend.base import BackendInfo
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import PscadService
from pscad_mcp.core.backend.legacy import LegacyBackend


CATALOG = {
    "schema_version": 1,
    "name": "test",
    "pscad_version": "4.6.2",
    "identity": "test/catalog",
    "definitions": [
        {
            "scoped_name": "master:source3",
            "ports": [{"name": "ac", "kind": "electrical", "dimension": 3}],
        },
        {
            "scoped_name": "cigre_lcc_v1:Bridge",
            "ports": [{"name": "dc", "kind": "electrical", "dimension": 1}],
        },
    ],
}


class _InventoryBackend:
    name = "legacy"
    version = "4.6.2"
    x64 = True

    async def lcc_definition_inventory(self, catalog):
        return {
            "pscad_version": "4.6.2",
            "definitions": {
                "master:source3": {"ports": [{"name": "ac"}]},
            },
        }


def test_service_combines_live_inventory_with_packaged_companion_definitions(tmp_path):
    service = PscadService(
        lambda: _InventoryBackend(),
        path_policy=PathPolicy(str(tmp_path)),
    )
    service._backend = _InventoryBackend()

    inventory = asyncio.run(service.get_lcc_inventory(CATALOG))

    assert inventory["pscad_version"] == "4.6.2"
    assert set(inventory["definitions"]) == {
        "master:source3",
        "cigre_lcc_v1:Bridge",
    }
    assert inventory["definitions"]["cigre_lcc_v1:Bridge"]["source"] == "packaged_companion"


def test_legacy_inventory_reads_live_master_definition_metadata(tmp_path):
    master = tmp_path / "master.pslx"
    master.write_text(
        """<?xml version='1.0'?>
<pslx><Definition name='source3'><svg><port name='ac' x='1' y='2' dim='3' type='electrical'/></svg></Definition></pslx>
""",
        encoding="utf-8",
    )
    backend = LegacyBackend(
        robust_executor,
        version="4.6.2",
        x64=True,
        automation_module=False,
        definition_paths={"master": master},
    )

    inventory = asyncio.run(backend.lcc_definition_inventory(CATALOG))

    assert inventory["pscad_version"] == "4.6.2"
    assert inventory["definitions"]["master:source3"]["ports"] == [
        {"name": "ac", "dimension": 3, "kind": "electrical"}
    ]
