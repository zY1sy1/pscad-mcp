import json
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.build_lcc_companion_library import render_library


ASSETS = Path(__file__).parents[1] / "pscad_mcp/assets/lcc/cigre_lcc_monopole_v1"


def test_bridge_references_are_independent_of_valve_terminals():
    bridge = ET.fromstring(render_library()).find("./definitions/Definition[@name='LCC12PulseBridge']")
    ports = {port.get("name"): port for port in bridge.findall("./svg/port")}
    for phase in "ABC":
        assert f"REF_{phase}" in ports
        assert ports[f"REF_{phase}"].get("model") == "Natural"
    schematic = bridge.find("schematic")
    references = schematic.findall("User[@defn='master:nodeloop']")
    assert len(references) == 1
    reference = references[0]
    location = (int(reference.get("x")), int(reference.get("y")))
    for wire in schematic.findall("Wire"):
        origin = (int(wire.get("x")), int(wire.get("y")))
        points = [(origin[0] + int(v.get("x")), origin[1] + int(v.get("y"))) for v in wire.findall("vertex")]
        if wire.get("lcc_role") in {"ACY_TO_METER", "ACD_TO_METER", "METER_TO_Y", "METER_TO_D"}:
            assert location not in points
        elif wire.get("lcc_role") == "REFERENCE_BUS":
            assert location in points
    assert [node.find("paramlist/param[@name='KV']").get("value") for node in schematic.findall("User[@defn='master:g6p200']")] == ["-1", "-2"]


def test_primary_reference_connections_share_the_filtered_phase_bus():
    blueprint = json.loads((ASSETS / "blueprint.json").read_text(encoding="utf-8"))
    for station in ("rectifier", "inverter"):
        for phase in "ABC":
            endpoint = {"component": f"{station}_bridge", "port": f"REF_{phase}"}
            nets = [net for net in blueprint["nets"] if endpoint in net["endpoints"]]
            assert len(nets) == 1
            assert nets[0]["kind"] == "electrical"
            assert {"component": f"{station}_transformer_y", "port": f"HV_{phase}"} in nets[0]["endpoints"]
