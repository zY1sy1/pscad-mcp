from __future__ import annotations

import pytest

from pscad_mcp.builders.blueprint.inventory import read_live_inventory


@pytest.mark.asyncio
async def test_live_inventory_fallback_uses_pscad_service_status_and_observed_definition_metadata():
    class GenericService:
        async def list_canvas_components(self, project_name, *, canvas_name):
            return [{"id": 7, "name": "BRK", "definition": "master:breaker", "orientation": 0}]

        async def get_project_definitions(self, project_name):
            return ["master:breaker"]

        async def status(self):
            return {"version": "4.6.2"}

        async def get_component_parameters(self, project_name, component_id):
            return {"Name": "BRK"}

        async def get_component_ports(self, project_name, component_id):
            return {"A": {"name": "A", "x": 9, "y": 10, "kind": "electrical", "dimension": 1}}

        async def get_component_location(self, project_name, component_id):
            return {"x": 10, "y": 10}

    inventory = await read_live_inventory(GenericService(), "Source", "breaker")

    assert inventory.pscad_version == "4.6.2"
    assert inventory.definitions["master:breaker"]["parameters"]["Name"] == {"resolved": True, "units": None}
    assert inventory.definitions["master:breaker"]["ports"]["A"]["dimension"] == 1
    assert inventory.components[0]["logical_id"] == "BRK"
