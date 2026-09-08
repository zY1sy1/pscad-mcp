import json
import xml.etree.ElementTree as ET
from pathlib import Path

from pscad_mcp.hvdc.builders.lcc.schema import parse_blueprint
from scripts.build_lcc_companion_library import render_library


def test_duplicate_measurements_require_explicit_derived_signal_metadata():
    path = Path("pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/blueprint.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    measurements = {item["logical_id"]: item for item in value["measurements"]}
    assert measurements["mu_measurement"]["port"] != measurements["alpha_measurement"]["port"]
    assert measurements["vac_rect_measurement"]["derived_from"] == "p_rect_measurement"
    parsed = parse_blueprint(value)
    assert len(parsed.measurements) == len(value["measurements"])


def test_angle_measurements_receive_each_native_bridge_angle():
    value = json.loads(Path("pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/blueprint.json").read_text(encoding="utf-8"))
    measurements = {item["logical_id"]: item for item in value["measurements"]}
    assert measurements["alpha_measurement"]["component"] == "signal_interface"
    assert measurements["mu_measurement"]["component"] == "signal_interface"
    for name in ("AM_Y", "AM_D", "GM_Y", "GM_D"):
        assert any(
            {"component": "rectifier_bridge", "port": name} in net["endpoints"]
            and {"component": "signal_interface", "port": name} in net["endpoints"]
            for net in value["nets"]
        )


def test_inverter_voltage_uses_native_dp_minus_dn_polarity():
    interface = ET.fromstring(render_library()).find("./definitions/Definition[@name='SignalInterface']/schematic")
    inversion = interface.find("User[@defn='master:sumjct']/paramlist/param[@name='D'][@value='-1']")
    assert inversion is not None


def test_terminal_power_has_one_real_meter_per_phase():
    value = json.loads(Path("pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/blueprint.json").read_text(encoding="utf-8"))
    meters = [item for item in value["components"] if item["definition"] == "master:ac_meter"]
    for station in ("rectifier", "inverter"):
        station_meters = [item for item in meters if item["logical_id"].startswith(station)]
        assert len(station_meters) == 3
        assert len({item["parameters"]["ActivePowerSignal"] for item in station_meters}) == 3
        for phase, meter in zip("ABC", station_meters, strict=True):
            assert any(
                {"component": f"{station}_source", "port": phase} in net["endpoints"]
                and {"component": meter["logical_id"], "port": "A"} in net["endpoints"]
                for net in value["nets"]
            )


def test_measurement_summing_junctions_satisfy_native_input_minimum():
    root = ET.fromstring(render_library())
    for junction in root.findall("./definitions/Definition[@name='SignalInterface']/schematic/User[@defn='master:sumjct']"):
        parameters = {param.get("name"): param.get("value") for param in junction.findall("paramlist/param")}
        assert sum(int(parameters[name]) != 0 for name in "ABCDEFG") >= 2


def test_converter_power_uses_independent_ac_measurements_and_module_export():
    root = ET.fromstring(render_library())
    bridge = root.find("./definitions/Definition[@name='LCC12PulseBridge']")
    meters = bridge.findall("schematic/User[@defn='master:multimeter']")
    assert len(meters) == 2
    for meter in meters:
        parameters = {p.get("name"): p.get("value") for p in meter.findall("paramlist/param")}
        assert parameters["MeasP"] == "1"
        assert parameters["TS"] == "0.0 [s]"
        assert parameters["S"] == "1.0 [MVA]"
    assert bridge.find("svg/port[@name='P_AC'][@mode='Output']") is not None
    assert bridge.find("schematic/User[@defn='master:export']/paramlist/param[@name='Name'][@value='P_AC']") is not None


def test_power_product_and_grid_balance_keep_distinct_physical_boundaries():
    root = Path("pscad_mcp/assets/lcc/cigre_lcc_monopole_v1")
    checks = {item["name"]: item for item in json.loads((root / "acceptance.json").read_text())["physical_checks"]}
    assert checks["dc_power_product"]["power_channel"] == "Main/PCONV_RECT"
    assert checks["dc_power_product"]["max_percent"] == 5.0
    assert checks["terminal_power_balance"]["rectifier_power_channel"] == "Main/P_RECT"
    assert checks["terminal_power_balance"]["inverter_power_channel"] == "Main/P_INV"
    assert checks["terminal_power_balance"]["loss_allowance"] == 100.0


def test_angle_routes_and_current_power_routes_preserve_distinct_signals():
    from pscad_mcp.hvdc.builders.lcc.catalog import parse_catalog
    from pscad_mcp.hvdc.builders.lcc.executor import _route_for_backend
    from pscad_mcp.hvdc.builders.lcc.planner import _net_route
    from pscad_mcp.topology.connectivity import build_connectivity
    from pscad_mcp.topology.models import ProjectTopology, TopologyConductor

    root = Path("pscad_mcp/assets/lcc/cigre_lcc_monopole_v1")
    blueprint = parse_blueprint(json.loads((root / "blueprint.json").read_text()))
    catalog = parse_catalog(json.loads((root / "catalog-pscad-4.6.2.json").read_text()))
    components = {component.logical_id: component for component in blueprint.components}
    for names in ({"am_rect_y_measurement", "am_rect_d_measurement", "gm_rect_y_measurement", "gm_rect_d_measurement"}, {"idc_raw", "p_rect_a_measurement", "p_rect_b_measurement", "p_rect_c_measurement", "p_inv_a_measurement", "p_inv_b_measurement", "p_inv_c_measurement"}):
        for snapped in (False, True):
            conductors = []
            for net in blueprint.nets:
                if net.logical_id not in names:
                    continue
                route = _net_route(net, components, catalog)
                if snapped:
                    route = _route_for_backend(route, route[0], route[-1])
                conductors.append(TopologyConductor(key=net.logical_id, object_id=net.logical_id, canvas_key="Main", kind="wire", namespace="data", vertices=route))
            topology = build_connectivity(ProjectTopology("measurements", "4.6.2", conductors=tuple(conductors))).topology
            assert {frozenset(net.conductor_keys) for net in topology.nets} == {frozenset({name}) for name in names}
