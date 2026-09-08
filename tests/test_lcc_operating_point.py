import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.build_lcc_companion_library import render_library


ASSETS = Path(__file__).parents[1] / "pscad_mcp/assets/lcc/cigre_lcc_monopole_v1"


def test_transformer_mva_base_matches_fixed_dc_current_and_voltage_ratio(tmp_path):
    from pscad_mcp.core.master_bindings import audit_master_bindings, parse_master_binding_registry
    from tests.test_master_binding_registry import _write_master_fixture

    blueprint = json.loads((ASSETS / "blueprint.json").read_text())
    registry = parse_master_binding_registry(json.loads((ASSETS / "master-bindings-pscad-4.6.2.json").read_text()))
    audited = audit_master_bindings(_write_master_fixture(tmp_path), registry)
    transformers = [item for item in blueprint["components"] if item["definition"] == "master:converter_transformer"]
    for transformer in transformers:
        parameters = transformer["parameters"]
        ratio = 213.4557 / 209.2288 if transformer["logical_id"].startswith("rectifier") else 1.0
        physical = audited.resolve_component("master:converter_transformer", parameters).physical_parameters
        assert physical["V2"] == pytest.approx(230.0 * ratio)
        assert physical["Tmva"] == pytest.approx(math.sqrt(2) * physical["V2"])


def test_smoothing_reactors_use_verified_case_specific_sizing():
    blueprint = json.loads((ASSETS / "blueprint.json").read_text())
    components = {item["logical_id"]: item for item in blueprint["components"]}
    for name in ("dc_smoothing_reactor", "inverter_smoothing_reactor"):
        assert components[name]["parameters"]["Inductance_mH"] == 200.0
    assert components["dc_line"]["parameters"]["Resistance_ohm"] == 10.0


def test_native_control_limits_cover_current_limiting_and_gamma_control():
    root = ET.fromstring(render_library())
    for name, upper in (("RectifierControl", math.pi - 0.52), ("InverterControl", 1.57)):
        schematic = root.find(f"./definitions/Definition[@name='{name}']/schematic")
        for primitive, parameter in (("pi_ctlr", "YHI"), ("hardlimit", "UL")):
            limit = schematic.find(f"User[@defn='master:{primitive}']/paramlist/param[@name='{parameter}']")
            assert float(limit.get("value")) == pytest.approx(upper)


def test_gamma_cycle_minimum_is_in_the_control_feedback_path():
    root = ET.fromstring(render_library())
    schematic = root.find("./definitions/Definition[@name='InverterControl']/schematic")
    cycles = schematic.findall("User[@defn='master:mingam']")
    assert len(cycles) == 1
    assert cycles[0].find("paramlist/param[@name='FREQ']").get("value") == "50.0 [Hz]"
    assert schematic.find("Wire[@lcc_role='GAMMA_MIN_TO_CYCLE']") is not None
    fanout = schematic.find("Wire[@lcc_role='GAMMA_FANOUT']")
    assert (int(fanout.get("x")), int(fanout.get("y"))) == (int(cycles[0].get("x")) + 36, int(cycles[0].get("y")))


def test_startup_command_bounds_match_native_actuator_limits():
    contract = json.loads((ASSETS / "smoke.json").read_text())
    for group in ("Y", "D"):
        assert contract["ao_limits_rad"][f"Main/AO_RECT_{group}"] == pytest.approx([math.radians(5), math.pi - 0.52])
        assert contract["ao_limits_rad"][f"Main/AO_INV_{group}"] == pytest.approx([math.pi - 1.57, math.pi - 0.52])
