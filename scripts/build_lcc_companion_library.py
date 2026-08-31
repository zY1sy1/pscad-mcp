"""Render the repository-authored PSCAD 4.6.2 fixed LCC companion."""

from __future__ import annotations

import argparse
import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "pscad_mcp" / "assets" / "templates" / "empty_library.pslx"
LIBRARY_NAME = "cigre_lcc_v1"

COMMON_G6P200 = {
    "FP": "0",
    "SNUB": "1",
    "View": "1",
    "FR": "50.0 [Hz]",
    "GP": "10.0",
    "GI": "50.0",
    "KP": "0",
    "RON": "0.01 [ohm]",
    "ROFF": "100000000.0 [ohm]",
    "EFVD": "0.0 [kV]",
    "EBO": "100000.0 [kV]",
    "TEXT": "0.0 [us]",
    "CD": "0.05 [uF]",
    "RD": "5000.0 [ohm]",
    "FPNM": "",
    "VVolt": "",
    "VCurr": "",
    "SCurr": "",
    "Tblock": "0.04",
    "RWSAFB": "0",
    "RWV": "1.0E5",
    "PFB": "0",
}

STYLE = {
    "g6p200": (115, 184, 113177439),
    "xnode": (18, 31, 114262475),
    "breakout": (40, 77, 6599472),
    "import": (83, 22, 35483323),
    "export": (74, 21, 39049670),
    "const": (69, 19, 8647988),
    "consti": (69, 19, 89924856),
    "sumjct": (76, 60, 6678153),
    "mult": (76, 53, 66270573),
    "pi_ctlr": (76, 61, 89208388),
    "hardlimit": (76, 58, 85352944),
    "maxmin": (76, 60, 79761838),
    "unity": (40, 19, 39250382),
    "pgb": (70, 30, 63669868),
}


@dataclass(frozen=True)
class Component:
    role: str
    definition: str
    x: int
    y: int
    parameters: dict[str, Any]


@dataclass(frozen=True)
class Wire:
    name: str
    points: tuple[tuple[int, int], ...]


def _stable_id(identity: str) -> int:
    digest = hashlib.sha256(identity.encode("ascii")).digest()
    return int.from_bytes(digest[:4], "big") % 2_000_000_000 + 1


def _settings_schematic(parent: ET.Element) -> ET.Element:
    schematic = ET.SubElement(parent, "schematic", {"classid": "UserCanvas"})
    parameters = ET.SubElement(schematic, "paramlist")
    for name, value in (
        ("show_grid", "0"),
        ("size", "0"),
        ("orient", "1"),
        ("show_border", "0"),
        ("monitor_bus_voltage", "0"),
        ("show_signal", "0"),
        ("show_virtual", "0"),
        ("show_sequence", "0"),
        ("auto_sequence", "1"),
    ):
        ET.SubElement(parameters, "param", {"name": name, "value": value})
    return schematic


def _form(definition: ET.Element, name: str) -> None:
    form = ET.SubElement(
        definition,
        "form",
        {"name": name, "w": "360", "h": "420", "splitter": "65"},
    )
    if name != "12 Pulse LCC Bridge":
        return
    category = ET.SubElement(form, "category", {"name": "Configuration"})
    parameter = ET.SubElement(
        category,
        "parameter",
        {
            "type": "Choice",
            "name": "UP",
            "desc": "Terminal direction",
        },
    )
    ET.SubElement(parameter, "value").text = "1"
    ET.SubElement(parameter, "choice").text = "1 = Rectifier"
    ET.SubElement(parameter, "choice").text = "0 = Inverter"


def _svg(
    definition: ET.Element,
    ports: tuple[tuple[str, str, str, str], ...],
) -> None:
    svg = ET.SubElement(definition, "svg", {"viewBox": "-200 -200 200 200"})
    ET.SubElement(
        svg,
        "rect",
        {
            "x": "-54",
            "y": "-72",
            "width": "108",
            "height": "144",
            "stroke": "Black",
            "stroke-width": "0.2",
            "fill-style": "Hollow",
        },
    )
    for index, (name, kind, direction, data_type) in enumerate(ports):
        is_electrical = kind == "electrical"
        x = 72 if direction == "output" or name.startswith("DC_") else -72
        y = -63 + index * 9
        attributes = {
            "model": "Natural" if is_electrical else "Transfer",
            "name": name,
            "x": str(x),
            "y": str(y),
            "dim": "1",
            "mode": "Electrical" if is_electrical else direction.title(),
            "type": "NonRemovable" if is_electrical else data_type,
        }
        ET.SubElement(svg, "port", attributes).text = "true"


def _component(
    schematic: ET.Element,
    definition_name: str,
    sequence: int,
    component: Component,
) -> None:
    physical = component.definition.split(":", 1)[1]
    width, height, crc = STYLE[physical]
    element = ET.SubElement(
        schematic,
        "User",
        {
            "classid": "UserCmp",
            "name": "",
            "defn": component.definition,
            "id": str(_stable_id(f"{definition_name}:{component.role}")),
            "x": str(component.x),
            "y": str(component.y),
            "w": str(width),
            "h": str(height),
            "z": str(sequence * 10),
            "orient": "0",
            "link": "-1",
            "q": "4",
        },
    )
    paramlist = ET.SubElement(
        element,
        "paramlist",
        {"link": "-1", "name": "", "crc": str(crc)},
    )
    for name, value in component.parameters.items():
        ET.SubElement(
            paramlist,
            "param",
            {"name": name, "value": str(value)},
        )


def _wire(
    schematic: ET.Element,
    definition_name: str,
    sequence: int,
    wire: Wire,
) -> None:
    first_x, first_y = wire.points[0]
    xs = [point[0] for point in wire.points]
    ys = [point[1] for point in wire.points]
    element = ET.SubElement(
        schematic,
        "Wire",
        {
            "classid": "WireOrthogonal",
            "name": wire.name,
            "x": str(first_x),
            "y": str(first_y),
            "w": str(max(xs) - min(xs) + 10),
            "h": str(max(ys) - min(ys) + 10),
            "orient": "0",
            "id": str(_stable_id(f"{definition_name}:wire:{sequence}:{wire.name}")),
        },
    )
    for x, y in wire.points:
        ET.SubElement(
            element,
            "vertex",
            {"x": str(x - first_x), "y": str(y - first_y)},
        )


def _definition(
    definitions: ET.Element,
    name: str,
    form_name: str,
    ports: tuple[tuple[str, str, str, str], ...],
    components: tuple[Component, ...],
    wires: tuple[Wire, ...],
) -> None:
    definition = ET.SubElement(
        definitions,
        "Definition",
        {
            "classid": "UserCmpDefn",
            "name": name,
            "url": "",
            "view": "false",
            "instances": "0",
            "date": "0",
            "crc": str(_stable_id(f"{name}:crc")),
            "id": str(_stable_id(f"{name}:definition")),
            "group": "HVDC FACTS PE",
        },
    )
    description = ET.SubElement(definition, "paramlist")
    ET.SubElement(
        description,
        "param",
        {"name": "Description", "value": form_name},
    )
    _form(definition, form_name)
    _svg(definition, ports)
    schematic = _settings_schematic(definition)
    for sequence, component in enumerate(components, start=1):
        _component(schematic, name, sequence, component)
    for sequence, wire in enumerate(wires, start=1):
        _wire(schematic, name, sequence, wire)


def _pin(role: str, name: str, x: int, y: int) -> Component:
    return Component(role, "master:xnode", x, y, {"Name": name})


def _import(role: str, name: str, x: int, y: int) -> Component:
    return Component(role, "master:import", x, y, {"Name": name})


def _export(role: str, name: str, x: int, y: int) -> Component:
    return Component(role, "master:export", x, y, {"Name": name})


def _output_channel(
    role: str,
    name: str,
    units: str,
    x: int,
    y: int,
) -> Component:
    return Component(
        role,
        "master:pgb",
        x,
        y,
        {
            "Name": name,
            "Group": "",
            "UseSignalName": "0",
            "enab": "1",
            "Display": "1",
            "Scale": "1.0",
            "Units": units,
            "mrun": "0",
            "Pol": "0",
            "Max": "2.0",
            "Min": "-2.0",
        },
    )


def _bridge_definition(definitions: ET.Element) -> None:
    ports = (
        tuple(
            (name, "electrical", "bidirectional", "Real")
            for name in (
                "ACY_A",
                "ACY_B",
                "ACY_C",
                "ACD_A",
                "ACD_B",
                "ACD_C",
                "DC_POS",
                "DC_NEG",
            )
        )
        + tuple(
            (name, "data", "input", "Real")
            for name in ("AO_Y", "AO_D", "ENABLE")
        )
        + tuple(
            (name, "data", "output", "Real")
            for name in ("AM_Y", "AM_D", "GM_Y", "GM_D")
        )
    )
    g6_y = {**COMMON_G6P200, "UP": "$(UP)", "KV": "-2"}
    g6_d = {**COMMON_G6P200, "UP": "$(UP)", "KV": "-1"}
    components = (
        _pin("pin_acy_a", "ACY_A", 90, 144),
        _pin("pin_acy_b", "ACY_B", 90, 180),
        _pin("pin_acy_c", "ACY_C", 90, 216),
        _pin("pin_acd_a", "ACD_A", 90, 414),
        _pin("pin_acd_b", "ACD_B", 90, 450),
        _pin("pin_acd_c", "ACD_C", 90, 486),
        _pin("pin_dc_pos", "DC_POS", 360, 54),
        _pin("pin_dc_neg", "DC_NEG", 360, 576),
        Component("breakout_y", "master:breakout", 180, 180, {"Dis": "0", "Com": "0"}),
        Component("breakout_d", "master:breakout", 180, 450, {"Dis": "0", "Com": "0"}),
        Component("bridge_y", "master:g6p200", 360, 180, g6_y),
        Component("bridge_d", "master:g6p200", 360, 450, g6_d),
        _import("import_ao_y", "AO_Y", 504, 216),
        _import("import_ao_d", "AO_D", 504, 486),
        _import("import_enable", "ENABLE", 504, 315),
        Component(
            "enable_to_integer",
            "master:unity",
            600,
            315,
            {"IType": "2", "OType": "1", "Dim": "1"},
        ),
        _export("export_am_y", "AM_Y", 504, 126),
        _export("export_gm_y", "GM_Y", 504, 144),
        _export("export_am_d", "AM_D", 504, 396),
        _export("export_gm_d", "GM_D", 504, 414),
        Component(
            "const_enable_one", "master:consti", 600, 270, {"Name": "LCC_ENABLE_ONE", "Value": "1"}
        ),
        Component(
            "const_cb_zero", "master:consti", 600, 414, {"Name": "LCC_CB_ZERO", "Value": "0"}
        ),
        Component(
            "enable_inverter",
            "master:sumjct",
            720,
            315,
            {
                "DPath": "0",
                "A": "0",
                "B": "0",
                "C": "0",
                "D": "1",
                "E": "0",
                "F": "-1",
                "G": "0",
            },
        ),
    )
    wires = (
        Wire("ACY_TO_Y", ((90, 144), (216, 144))),
        Wire("ACY_TO_Y_B", ((90, 180), (90, 171), (216, 171), (216, 180))),
        Wire("ACY_TO_Y_C", ((90, 216), (216, 216))),
        Wire("ACY_TO_Y_BUS", ((180, 180), (180, 162), (324, 162), (324, 180))),
        Wire("ACD_TO_D", ((90, 414), (216, 414))),
        Wire("ACD_TO_D_B", ((90, 450), (90, 441), (216, 441), (216, 450))),
        Wire("ACD_TO_D_C", ((90, 486), (216, 486))),
        Wire("ACD_TO_D_BUS", ((180, 450), (180, 432), (324, 432), (324, 450))),
        Wire("DC_POS_PATH", ((360, 54), (360, 90))),
        Wire("DC_SERIES", ((360, 270), (360, 360))),
        Wire("DC_NEG_PATH", ((360, 540), (360, 576))),
        Wire("AO_Y_TO_BRIDGE_Y", ((540, 216), (414, 216))),
        Wire("AO_D_TO_BRIDGE_D", ((540, 486), (414, 486))),
        Wire("ENABLE_CONVERSION", ((540, 315), (564, 315))),
        Wire("ENABLE_ONE", ((636, 270), (684, 270), (684, 315))),
        Wire("ENABLE_ORDER", ((600, 315), (720, 315), (720, 351))),
        Wire("ENABLE_TO_KB_Y", ((756, 315), (780, 315), (780, 234), (414, 234))),
        Wire("ENABLE_TO_KB_D", ((756, 315), (792, 315), (792, 504), (414, 504))),
        Wire("CB_ZERO_Y", ((636, 414), (648, 414), (648, 90), (342, 90))),
        Wire("CB_ZERO_D", ((636, 414), (660, 414), (660, 360), (342, 360))),
        Wire("AM_Y_OUTPUT", ((414, 126), (540, 126))),
        Wire("GM_Y_OUTPUT", ((414, 144), (540, 144))),
        Wire("AM_D_OUTPUT", ((414, 396), (540, 396))),
        Wire("GM_D_OUTPUT", ((414, 414), (540, 414))),
    )
    _definition(
        definitions,
        "LCC12PulseBridge",
        "12 Pulse LCC Bridge",
        ports,
        components,
        wires,
    )


def _rectifier_control(definitions: ET.Element) -> None:
    ports = tuple(
        (name, "data", "input", "Real")
        for name in ("VDC", "IDC", "IORDER", "ENABLE")
    ) + tuple((name, "data", "output", "Real") for name in ("AO_Y", "AO_D", "ALPHA"))
    components = (
        _import("import_vdc", "VDC", 90, 90),
        _import("import_idc", "IDC", 90, 180),
        _import("import_iorder", "IORDER", 90, 270),
        _import("import_enable", "ENABLE", 90, 360),
        Component(
            "current_error",
            "master:sumjct",
            324,
            225,
            {
                "DPath": "1",
                "A": "0",
                "B": "0",
                "C": "0",
                "D": "1",
                "E": "0",
                "F": "-1",
                "G": "0",
            },
        ),
        Component("enable_product", "master:mult", 450, 225, {"DPath": "1"}),
        Component(
            "current_pi",
            "master:pi_ctlr",
            540,
            225,
            {
                "GP": "1.0989",
                "TI": "0.01092 [s]",
                "YHI": "0.5235987755982988",
                "YLO": "0.08726646259971647",
                "YINIT": "0.2617993877991494",
                "Mthd": "0",
                "INTR": "0",
            },
        ),
        Component(
            "alpha_limit",
            "master:hardlimit",
            684,
            225,
            {
                "UL": "0.5235987755982988",
                "LL": "0.08726646259971647",
                "COM": "LCC_AO_Limit",
                "Dim": "1",
                "Limit": "0",
            },
        ),
        _export("export_ao_y", "AO_Y", 846, 180),
        _export("export_ao_d", "AO_D", 846, 225),
        _export("export_alpha", "ALPHA", 846, 270),
        _output_channel("monitor_ao_y", "AO_RECT_Y", "rad", 756, 126),
        _output_channel("monitor_ao_d", "AO_RECT_D", "rad", 756, 324),
    )
    wires = (
        Wire("CURRENT_ERROR", ((126, 180), (288, 225))),
        Wire("CURRENT_ORDER", ((126, 270), (324, 261))),
        Wire("ERROR_TO_PRODUCT", ((360, 225), (414, 225))),
        Wire("ENABLE_PRODUCT", ((126, 360), (450, 360), (450, 261))),
        Wire("PRODUCT_TO_PI", ((486, 225), (504, 225))),
        Wire("PI_TO_LIMIT", ((576, 225), (648, 225))),
        Wire("AO_Y_OUTPUT", ((720, 225), (882, 180))),
        Wire("AO_D_OUTPUT", ((720, 225), (882, 225))),
        Wire("ALPHA_OUTPUT", ((720, 225), (882, 270))),
        Wire("AO_Y_MONITOR", ((720, 225), (756, 126))),
        Wire("AO_D_MONITOR", ((720, 225), (756, 324))),
    )
    _definition(
        definitions,
        "RectifierControl",
        "Rectifier Current Control",
        ports,
        components,
        wires,
    )


def _inverter_control(definitions: ET.Element) -> None:
    ports = tuple(
        (name, "data", "input", "Real")
        for name in ("VDC", "IDC", "GM_Y", "GM_D", "GAMMA_ORDER", "ENABLE")
    ) + tuple((name, "data", "output", "Real") for name in ("AO_Y", "AO_D", "GAMMA"))
    components = (
        _import("import_vdc", "VDC", 90, 72),
        _import("import_idc", "IDC", 90, 126),
        _import("import_gm_y", "GM_Y", 90, 198),
        _import("import_gm_d", "GM_D", 90, 270),
        _import("import_gamma_order", "GAMMA_ORDER", 90, 342),
        _import("import_enable", "ENABLE", 90, 414),
        Component(
            "gamma_minimum",
            "master:maxmin",
            288,
            234,
            {
                "DPath": "1",
                "Type": "0",
                "A": "0",
                "B": "0",
                "C": "0",
                "D": "1",
                "E": "1",
                "F": "0",
                "G": "0",
            },
        ),
        Component(
            "gamma_error",
            "master:sumjct",
            414,
            306,
            {
                "DPath": "1",
                "A": "0",
                "B": "0",
                "C": "0",
                "D": "1",
                "E": "0",
                "F": "-1",
                "G": "0",
            },
        ),
        Component("enable_product", "master:mult", 540, 306, {"DPath": "1"}),
        Component(
            "gamma_pi",
            "master:pi_ctlr",
            630,
            306,
            {
                "GP": "0.7506",
                "TI": "0.0544 [s]",
                "YHI": "1.92",
                "YLO": "0.52",
                "YINIT": "1.57",
                "Mthd": "0",
                "INTR": "0",
            },
        ),
        Component(
            "beta_limit",
            "master:hardlimit",
            774,
            306,
            {
                "UL": "1.92",
                "LL": "0.52",
                "COM": "LCC_AO_Limit",
                "Dim": "1",
                "Limit": "0",
            },
        ),
        _export("export_ao_y", "AO_Y", 936, 252),
        _export("export_ao_d", "AO_D", 936, 306),
        _export("export_gamma", "GAMMA", 936, 360),
        _output_channel("monitor_ao_y", "AO_INV_Y", "rad", 864, 180),
        _output_channel("monitor_ao_d", "AO_INV_D", "rad", 864, 414),
        _output_channel("monitor_gamma", "GAMMA_INV", "rad", 396, 180),
    )
    wires = (
        Wire("GAMMA_MIN", ((126, 198), (252, 234))),
        Wire("GAMMA_MIN_D", ((126, 270), (252, 270))),
        Wire("GAMMA_ERROR", ((126, 342), (378, 306))),
        Wire("GAMMA_FEEDBACK", ((324, 234), (414, 342))),
        Wire("ERROR_TO_PRODUCT", ((450, 306), (504, 306))),
        Wire("ENABLE_PRODUCT", ((126, 414), (540, 414), (540, 342))),
        Wire("PRODUCT_TO_PI", ((576, 306), (594, 306))),
        Wire("PI_TO_LIMIT", ((666, 306), (738, 306))),
        Wire("AO_Y_OUTPUT", ((810, 306), (972, 252))),
        Wire("AO_D_OUTPUT", ((810, 306), (972, 306))),
        Wire("GAMMA_OUTPUT", ((324, 234), (972, 360))),
        Wire("AO_Y_MONITOR", ((810, 306), (864, 180))),
        Wire("AO_D_MONITOR", ((810, 306), (864, 414))),
        Wire("GAMMA_MONITOR", ((324, 234), (396, 180))),
    )
    _definition(
        definitions,
        "InverterControl",
        "Inverter Gamma Control",
        ports,
        components,
        wires,
    )


def _initialization(definitions: ET.Element) -> None:
    ports = tuple(
        (name, "data", "output", "Real")
        for name in ("IORDER", "GAMMA_ORDER", "ENABLE_RECT", "ENABLE_INV")
    )
    components = (
        Component("iorder", "master:const", 180, 126, {"Name": "LCC_IORDER_VALUE", "Value": "1.0"}),
        Component(
            "gamma_order",
            "master:const",
            180,
            198,
            {"Name": "LCC_GAMMA_ORDER_VALUE", "Value": "0.3141592653589793"},
        ),
        Component("enable_rect", "master:consti", 180, 270, {"Name": "LCC_ENABLE_RECT_VALUE", "Value": "1"}),
        Component("enable_inv", "master:consti", 180, 342, {"Name": "LCC_ENABLE_INV_VALUE", "Value": "1"}),
        _export("export_iorder", "IORDER", 360, 126),
        _export("export_gamma", "GAMMA_ORDER", 360, 198),
        _export("export_enable_rect", "ENABLE_RECT", 360, 270),
        _export("export_enable_inv", "ENABLE_INV", 360, 342),
        Component(
            "enable_rect_to_real",
            "master:unity",
            270,
            270,
            {"IType": "1", "OType": "2", "Dim": "1"},
        ),
        Component(
            "enable_inv_to_real",
            "master:unity",
            270,
            342,
            {"IType": "1", "OType": "2", "Dim": "1"},
        ),
        _output_channel("monitor_enable_rect", "ENABLE_RECT", "state", 432, 270),
        _output_channel("monitor_enable_inv", "ENABLE_INV", "state", 432, 342),
    )
    wires = (
        Wire("IORDER_OUTPUT", ((216, 126), (396, 126))),
        Wire("GAMMA_ORDER_OUTPUT", ((216, 198), (396, 198))),
        Wire("ENABLE_RECT_OUTPUT", ((270, 270), (396, 270))),
        Wire("ENABLE_INV_OUTPUT", ((270, 342), (396, 342))),
        Wire("ENABLE_RECT_CONVERSION", ((216, 270), (234, 270))),
        Wire("ENABLE_INV_CONVERSION", ((216, 342), (234, 342))),
        Wire("ENABLE_RECT_MONITOR", ((270, 270), (432, 270))),
        Wire("ENABLE_INV_MONITOR", ((270, 342), (432, 342))),
    )
    _definition(
        definitions,
        "Initialization",
        "Fixed LCC Initialization",
        ports,
        components,
        wires,
    )


def _signal_interface(definitions: ET.Element) -> None:
    ports = tuple(
        (name, "data", "output", "Real") for name in ("VDC_RECT", "VDC_INV", "IDC")
    )
    components = (
        _import("import_vdc_rect", "LCC_VDC_RECT_RAW", 180, 126),
        _import("import_vdc_inv", "LCC_VDC_INV_RAW", 180, 198),
        _import("import_idc", "LCC_IDC_RAW", 180, 270),
        _export("export_vdc_rect", "VDC_RECT", 360, 126),
        _export("export_vdc_inv", "VDC_INV", 360, 198),
        _export("export_idc", "IDC", 360, 270),
        _output_channel("monitor_vdc_rect", "VDC_RECT", "kV", 288, 72),
        _output_channel("monitor_vdc_inv", "VDC_INV", "kV", 288, 342),
        _output_channel("monitor_idc", "IDC", "kA", 288, 414),
    )
    wires = (
        Wire("VDC_RECT_IMPORT", ((216, 126), (396, 126))),
        Wire("VDC_INV_IMPORT", ((216, 198), (396, 198))),
        Wire("IDC_IMPORT", ((216, 270), (396, 270))),
        Wire("VDC_RECT_MONITOR", ((216, 126), (288, 72))),
        Wire("VDC_INV_MONITOR", ((216, 198), (288, 342))),
        Wire("IDC_MONITOR", ((216, 270), (288, 414))),
    )
    _definition(
        definitions,
        "SignalInterface",
        "Fixed LCC Signal Interface",
        ports,
        components,
        wires,
    )


def render_library() -> bytes:
    root = ET.parse(TEMPLATE).getroot()
    root.set("name", LIBRARY_NAME)
    root.set("version", "4.6.2")
    root.set("Target", "Library")
    definitions = next(
        child for child in root if child.tag.rsplit("}", 1)[-1] == "definitions"
    )
    definitions.clear()
    for child in list(root):
        if child.tag.rsplit("}", 1)[-1] == "hierarchy":
            root.remove(child)
    _bridge_definition(definitions)
    _rectifier_control(definitions)
    _inverter_control(definitions)
    _initialization(definitions)
    _signal_interface(definitions)
    ET.indent(root, space="  ")
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return payload.replace(b"\r\n", b"\n") + (b"" if payload.endswith(b"\n") else b"\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    payload = render_library()
    if arguments.check:
        return 0 if arguments.output.read_bytes() == payload else 1
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
