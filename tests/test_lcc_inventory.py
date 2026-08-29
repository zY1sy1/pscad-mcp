from __future__ import annotations

import asyncio

from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.master_bindings import parse_master_binding_registry
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import PscadService

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


def _registry():
    return parse_master_binding_registry(
        {
            "schema_version": 1,
            "name": "inventory_test_registry",
            "pscad_version": "4.6.2",
            "bindings": [
                {
                    "logical_name": "master:source3",
                    "physical_definition": "source3",
                    "shape": {"kind": "direct"},
                    "ports": [
                        {
                            "logical": "ac",
                            "physical": "ac",
                            "kind": "electrical",
                            "dimension": 3,
                            "occurrence": 0,
                        }
                    ],
                    "parameters": [],
                    "fixed_parameters": [],
                    "evidence_parameters": [],
                }
            ],
        }
    )


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


def test_legacy_inventory_uses_registry_audit_and_reports_hashes(tmp_path):
    master = tmp_path / "master.pslx"
    master.write_text(
        """<?xml version='1.0'?>
<pslx><Definition name='source3'><svg><port model='Natural' name='ac' x='1' y='2' dim='3' type='NonRemovable'/></svg></Definition></pslx>
""",
        encoding="utf-8",
    )
    registry = _registry()
    backend = LegacyBackend(
        robust_executor,
        version="4.6.2",
        x64=True,
        automation_module=False,
        definition_paths={"master": master},
    )

    inventory = asyncio.run(
        backend.lcc_definition_inventory(CATALOG, registry.to_dict())
    )

    assert inventory["master_binding_registry_sha256"] == registry.sha256
    assert len(inventory["master_sha256"]) == 64
    evidence = inventory["definitions"]["master:source3"]
    assert evidence["physical_definition"] == "source3"
    assert evidence["verification_state"] == "verified"
    assert evidence["selected_ports"]["ac"]["physical"] == "ac"
    assert evidence["ports"] == [
        {
            "name": "ac",
            "physical": "ac",
            "occurrence": 0,
            "dimension": 3,
            "kind": "electrical",
        }
    ]


def test_service_preserves_master_audit_evidence(tmp_path):
    registry = _registry()

    class RegistryInventoryBackend(_InventoryBackend):
        async def lcc_definition_inventory(
            self, catalog, master_binding_registry=None
        ):
            assert master_binding_registry == registry.to_dict()
            return {
                "pscad_version": "4.6.2",
                "definitions": {
                    "master:source3": {
                        "ports": [{"name": "ac"}],
                        "verification_state": "verified",
                    }
                },
                "master_sha256": "a" * 64,
                "master_binding_registry_sha256": registry.sha256,
            }

    service = PscadService(
        lambda: RegistryInventoryBackend(),
        path_policy=PathPolicy(str(tmp_path)),
    )
    service._backend = RegistryInventoryBackend()

    inventory = asyncio.run(
        service.get_lcc_inventory(CATALOG, registry.to_dict())
    )

    assert inventory["master_sha256"] == "a" * 64
    assert inventory["master_binding_registry_sha256"] == registry.sha256
    assert (
        inventory["definitions"]["master:source3"]["verification_state"]
        == "verified"
    )
