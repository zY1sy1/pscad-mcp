from __future__ import annotations

import xml.etree.ElementTree as ET
from itertools import pairwise
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.companion import audit_companion_library
from scripts.build_lcc_companion_library import render_library

PORTS = {
    "LCC12PulseBridge": (
        ("ACY_A", "Natural", "", "NonRemovable"),
        ("ACY_B", "Natural", "", "NonRemovable"),
        ("ACY_C", "Natural", "", "NonRemovable"),
        ("ACD_A", "Natural", "", "NonRemovable"),
        ("ACD_B", "Natural", "", "NonRemovable"),
        ("ACD_C", "Natural", "", "NonRemovable"),
        ("DC_POS", "Natural", "", "NonRemovable"),
        ("DC_NEG", "Natural", "", "NonRemovable"),
        ("AO_Y", "Transfer", "Input", "Real"),
        ("AO_D", "Transfer", "Input", "Real"),
        ("ENABLE", "Transfer", "Input", "Real"),
        ("AM_Y", "Transfer", "Output", "Real"),
        ("AM_D", "Transfer", "Output", "Real"),
        ("GM_Y", "Transfer", "Output", "Real"),
        ("GM_D", "Transfer", "Output", "Real"),
        ("REF_A", "Natural", "", "NonRemovable"),
        ("REF_B", "Natural", "", "NonRemovable"),
        ("REF_C", "Natural", "", "NonRemovable"),
    ),
    "RectifierControl": (
        ("VDC_MEAS", "Transfer", "Input", "Real"),
        ("IDC_MEAS", "Transfer", "Input", "Real"),
        ("IORDER", "Transfer", "Input", "Real"),
        ("ENABLE", "Transfer", "Input", "Real"),
        ("AO_Y", "Transfer", "Output", "Real"),
        ("AO_D", "Transfer", "Output", "Real"),
        ("ALPHA", "Transfer", "Output", "Real"),
    ),
    "InverterControl": (
        ("VDC_MEAS", "Transfer", "Input", "Real"),
        ("IDC_MEAS", "Transfer", "Input", "Real"),
        ("GM_Y", "Transfer", "Input", "Real"),
        ("GM_D", "Transfer", "Input", "Real"),
        ("GAMMA_ORDER", "Transfer", "Input", "Real"),
        ("ENABLE", "Transfer", "Input", "Real"),
        ("AO_Y", "Transfer", "Output", "Real"),
        ("AO_D", "Transfer", "Output", "Real"),
        ("GAMMA", "Transfer", "Output", "Real"),
    ),
    "Initialization": (
        ("IORDER", "Transfer", "Output", "Real"),
        ("GAMMA_ORDER", "Transfer", "Output", "Real"),
        ("ENABLE_RECT", "Transfer", "Output", "Real"),
        ("ENABLE_INV", "Transfer", "Output", "Real"),
    ),
    "SignalInterface": (
        ("VDC_RECT_RAW", "Transfer", "Input", "Real"),
        ("VDC_INV_RAW", "Transfer", "Input", "Real"),
        ("IDC_RAW", "Transfer", "Input", "Real"),
        ("VDC_RECT", "Transfer", "Output", "Real"),
        ("VDC_INV", "Transfer", "Output", "Real"),
        ("IDC", "Transfer", "Output", "Real"),
        *((name, "Transfer", "Input", "Real") for name in ("AM_Y", "AM_D", "GM_Y", "GM_D", "P_RECT_A", "P_RECT_B", "P_RECT_C", "P_INV_A", "P_INV_B", "P_INV_C")),
        *((name, "Transfer", "Output", "Real") for name in ("ALPHA_RECT", "MU_RECT", "P_RECT", "P_INV")),
    ),
}

USERS = {
    "LCC12PulseBridge": (
        "master:g6p200",
        "master:g6p200",
        *("master:xnode" for _ in range(11)),
        "master:breakout",
        "master:breakout",
        "master:breakout",
        "master:nodeloop",
        *("master:resistor" for _ in range(9)),
        *("master:import" for _ in range(3)),
        *("master:export" for _ in range(4)),
        "master:unity",
    ),
    "RectifierControl": (
        *("master:import" for _ in range(4)),
        *("master:export" for _ in range(3)),
        "master:sumjct",
        "master:mult",
        "master:pi_ctlr",
        "master:hardlimit",
        "master:pgb",
        "master:pgb",
    ),
    "InverterControl": (
        *("master:import" for _ in range(6)),
        *("master:export" for _ in range(3)),
        "master:maxmin",
        "master:sumjct",
        "master:sumjct",
        "master:const",
        "master:mult",
        "master:pi_ctlr",
        "master:hardlimit",
        "master:pgb",
        "master:pgb",
        "master:pgb",
    ),
    "Initialization": (
        "master:const",
        "master:const",
        "master:consti",
        "master:consti",
        *("master:export" for _ in range(4)),
        "master:unity",
        "master:unity",
        "master:pgb",
        "master:pgb",
    ),
    "SignalInterface": (
        *("master:import" for _ in range(13)),
        *("master:export" for _ in range(7)),
        "master:unity",
        "master:unity",
        *("master:sumjct" for _ in range(5)),
        "master:maxmin",
        "master:maxmin",
        "master:const",
        "master:const",
        "master:pgb",
        "master:pgb",
        "master:pgb",
    ),
}

WIRES = {
    "LCC12PulseBridge": (
        "ACY_TO_Y",
        "ACD_TO_D",
        "DC_SERIES",
        "AO_Y_TO_BRIDGE_Y",
        "AO_D_TO_BRIDGE_D",
        "ENABLE_TO_KB_Y",
        "ENABLE_TO_KB_D",
        "ENABLE_CONVERSION",
        "CB_REFERENCE_Y",
        "CB_REFERENCE_D",
        "REFERENCE_BUS",
        "REF_A_TO_ISOLATION",
        "REF_B_TO_ISOLATION",
        "REF_C_TO_ISOLATION",
        "REF_A_TO_BREAKOUT",
        "REF_B_TO_BREAKOUT",
        "REF_C_TO_BREAKOUT",
    ),
    "RectifierControl": (
        "CURRENT_ERROR",
        "ENABLE_PRODUCT",
        "PI_TO_LIMIT",
        "AO_Y_OUTPUT",
        "AO_D_OUTPUT",
        "ALPHA_OUTPUT",
        "AO_Y_MONITOR",
        "AO_D_MONITOR",
    ),
    "InverterControl": (
        "GAMMA_MIN",
        "GAMMA_ERROR",
        "BETA_TO_ALPHA",
        "PI_TO_ALPHA",
        "ENABLE_PRODUCT",
        "PI_TO_LIMIT",
        "AO_Y_OUTPUT",
        "AO_D_OUTPUT",
        "GAMMA_FANOUT",
        "AO_Y_MONITOR",
        "AO_D_MONITOR",
    ),
    "Initialization": (
        "IORDER_OUTPUT",
        "GAMMA_ORDER_OUTPUT",
        "ENABLE_RECT_OUTPUT",
        "ENABLE_INV_OUTPUT",
        "ENABLE_RECT_CONVERSION",
        "ENABLE_INV_CONVERSION",
        "ENABLE_RECT_MONITOR",
        "ENABLE_INV_MONITOR",
    ),
    "SignalInterface": (
        "VDC_RECT_RAW_TO_UNITY",
        "VDC_RECT_FANOUT",
        "VDC_INV_RAW_TO_NEGATE",
        "VDC_INV_ZERO_TO_NEGATE",
        "VDC_INV_FANOUT",
        "IDC_RAW_TO_UNITY",
        "IDC_FANOUT",
        "AM_Y_TO_MAX", "AM_D_TO_MAX", "ALPHA_MEASURED_OUTPUT",
        "AM_Y_TO_OVERLAP", "AM_D_TO_OVERLAP", "GM_Y_TO_OVERLAP", "GM_D_TO_OVERLAP",
        "PI_TO_OVERLAP_Y", "PI_TO_OVERLAP_D", "OVERLAP_Y_TO_MAX", "OVERLAP_D_TO_MAX", "OVERLAP_MEASURED_OUTPUT",
        "P_RECT_A_TO_SUM", "P_RECT_B_TO_SUM", "P_RECT_C_TO_SUM", "P_RECT_TOTAL_OUTPUT",
        "P_INV_A_TO_SUM", "P_INV_B_TO_SUM", "P_INV_C_TO_SUM", "P_INV_TOTAL_OUTPUT",
    ),
}

OUTPUT_NAMES = {
    "LCC12PulseBridge": (),
    "RectifierControl": ("AO_RECT_Y", "AO_RECT_D"),
    "InverterControl": ("AO_INV_Y", "AO_INV_D", "GAMMA_INV"),
    "Initialization": ("ENABLE_RECT", "ENABLE_INV"),
    "SignalInterface": ("VDC_RECT", "VDC_INV", "IDC"),
}

XNODE_NAMES = (
    "ACY_A",
    "ACY_B",
    "ACY_C",
    "ACD_A",
    "ACD_B",
    "ACD_C",
    "DC_POS",
    "DC_NEG",
    "REF_A",
    "REF_B",
    "REF_C",
)


def write_physical_library_fixture(
    tmp_path: Path,
    *,
    mutation: str | None = None,
) -> Path:
    root = ET.Element(
        "project",
        {
            "name": "cigre_lcc_v1",
            "version": "4.6.2",
            "Target": "Library",
        },
    )
    definitions = ET.SubElement(root, "definitions")
    for definition_index, definition_name in enumerate(PORTS):
        definition = ET.SubElement(
            definitions,
            "Definition",
            {
                "classid": "UserCmpDefn",
                "name": definition_name,
                "id": str(100 + definition_index),
            },
        )
        ET.SubElement(definition, "form")
        svg = ET.SubElement(definition, "svg")
        for port_index, (name, model, mode, port_type) in enumerate(
            PORTS[definition_name]
        ):
            ET.SubElement(
                svg,
                "port",
                {
                    "model": model,
                    "name": name,
                    "x": str(port_index * 18),
                    "y": "0",
                    "dim": "1",
                    "mode": mode,
                    "type": port_type,
                },
            )
        schematic = ET.SubElement(
            definition,
            "schematic",
            {"classid": "UserCanvas"},
        )
        users = list(USERS[definition_name])
        if (
            mutation == "remove_second_bridge"
            and definition_name == "LCC12PulseBridge"
        ):
            users.pop()
        for user_index, scoped_name in enumerate(users):
            user = ET.SubElement(
                schematic,
                "User",
                {
                    "classid": "UserCmp",
                    "id": str(1000 + user_index),
                    "defn": scoped_name,
                    "x": str(180 + user_index * 90),
                    "y": "180",
                },
            )
            if scoped_name == "master:pgb":
                output_index = sum(
                    value == "master:pgb" for value in users[:user_index]
                )
                paramlist = ET.SubElement(user, "paramlist")
                ET.SubElement(
                    paramlist,
                    "param",
                    {
                        "name": "Name",
                        "value": OUTPUT_NAMES[definition_name][output_index],
                    },
                )
            elif scoped_name == "master:xnode":
                xnode_index = sum(
                    value == "master:xnode" for value in users[:user_index]
                )
                paramlist = ET.SubElement(user, "paramlist")
                ET.SubElement(
                    paramlist,
                    "param",
                    {"name": "Name", "value": XNODE_NAMES[xnode_index]},
                )
        wires = list(WIRES[definition_name])
        if (
            mutation == "remove_ao_wire"
            and definition_name == "LCC12PulseBridge"
        ):
            wires.remove("AO_D_TO_BRIDGE_D")
        for wire_index, wire_name in enumerate(wires):
            ET.SubElement(
                schematic,
                "Wire",
                {
                    "id": str(2000 + wire_index),
                    "name": "",
                    "lcc_role": wire_name,
                },
            )

    bridge_svg = definitions.find("./Definition[@name='LCC12PulseBridge']/svg")
    assert bridge_svg is not None
    if mutation == "add_gates_port":
        ET.SubElement(
            bridge_svg,
            "port",
            {
                "model": "Transfer",
                "name": "GATES",
                "x": "0",
                "y": "90",
                "dim": "12",
                "mode": "Input",
                "type": "Integer",
            },
        )
    if mutation == "copy_master_definition":
        ET.SubElement(
            definitions,
            "Definition",
            {"classid": "UserCmpDefn", "name": "master:g6p200"},
        )
    if mutation == "duplicate_definition":
        ET.SubElement(
            definitions,
            "Definition",
            {"classid": "UserCmpDefn", "name": "SignalInterface"},
        )
    if mutation == "add_absolute_path":
        root.set("source", r"C:\vendor\master.pslx")
    if mutation == "add_foreign_scope":
        schematic = definitions.find(
            "./Definition[@name='SignalInterface']/schematic"
        )
        assert schematic is not None
        ET.SubElement(
            schematic,
            "User",
            {
                "classid": "UserCmp",
                "id": "9999",
                "defn": "foreign:Copied",
            },
        )
    path = tmp_path / "cigre_lcc_v1.pslx"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_structural_contract_is_not_a_physical_library(tmp_path):
    path = tmp_path / "structural.pslx"
    path.write_text(
        """<pslx><definitions>
<definition name="cigre_lcc_v1:LCC12PulseBridge">
  <six_pulse_group name="upper" />
  <valve id="V01" definition="master:thyristor_valve" />
</definition>
</definitions></pslx>""",
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as failure:
        audit_companion_library(path)

    assert failure.value.code == "LCC_COMPANION_INVALID"
    assert "structural_only" in {
        item["reason"] for item in failure.value.details["errors"]
    }


def test_physical_bridge_requires_two_g6p200_and_scalar_ao(tmp_path):
    evidence = audit_companion_library(write_physical_library_fixture(tmp_path))

    bridge = evidence["definitions"]["cigre_lcc_v1:LCC12PulseBridge"]
    assert bridge["master_instances"]["master:g6p200"] == 2
    assert bridge["master_instances"]["master:xnode"] == 11
    assert bridge["master_instances"]["master:breakout"] == 3
    assert bridge["master_instances"]["master:resistor"] == 9
    assert bridge["ports"]["AO_Y"] == {
        "kind": "data",
        "dimension": 1,
        "direction": "input",
    }
    assert bridge["ports"]["AO_D"]["dimension"] == 1
    assert "GATES" not in bridge["ports"]
    assert evidence["effective_valves"] == 12
    assert {
        definition.rsplit(":", 1)[-1]: tuple(details["output_channels"])
        for definition, details in evidence["definitions"].items()
    } == OUTPUT_NAMES


def test_generated_bridge_connects_each_phase_resistor_to_breakout(tmp_path):
    root = ET.fromstring(render_library())
    bridge = root.find("./definitions/Definition[@name='LCC12PulseBridge']")
    assert bridge is not None

    def wire_points(name):
        wire = bridge.find(f"./schematic/Wire[@lcc_role='{name}']")
        assert wire is not None
        origin = (int(wire.get("x")), int(wire.get("y")))
        return [
            (origin[0] + int(vertex.get("x")), origin[1] + int(vertex.get("y")))
            for vertex in wire.findall("./vertex")
        ]

    assert wire_points("ACY_A_TO_BREAKOUT") == [(182, 306), (216, 306)]
    assert wire_points("ACY_B_TO_BREAKOUT") == [(182, 342), (216, 342)]
    assert wire_points("ACY_C_TO_BREAKOUT") == [(182, 378), (216, 378)]
    assert wire_points("ACD_A_TO_BREAKOUT") == [(182, 594), (216, 594)]
    assert wire_points("ACD_B_TO_BREAKOUT") == [(182, 630), (216, 630)]
    assert wire_points("ACD_C_TO_BREAKOUT") == [(182, 666), (216, 666)]


def test_generated_bridge_keeps_native_dp_at_logical_dc_pos():
    root = ET.fromstring(render_library())
    bridge = root.find("./definitions/Definition[@name='LCC12PulseBridge']")
    assert [
        user.find("./paramlist/param[@name='UP']").get("value")
        for user in bridge.findall("./schematic/User[@defn='master:g6p200']")
    ] == ["1", "1"]


def test_generated_bridge_uses_ac_node_references_for_phase_locking():
    root = ET.fromstring(render_library())
    schematic = root.find("./definitions/Definition[@name='LCC12PulseBridge']/schematic")
    references = schematic.findall("./User[@defn='master:nodeloop']")
    assert len(references) == 1
    assert schematic.find("./User/paramlist/param[@value='LCC_CB_ZERO']") is None
    bridges = schematic.findall("./User[@defn='master:g6p200']")
    reference = references[0]
    x, y = int(reference.get("x")), int(reference.get("y"))
    assert reference.find("./paramlist/param[@name='View']").get("value") == "1"
    for suffix, bridge, shift in zip(("Y", "D"), bridges, ("-1", "-2"), strict=True):
        assert bridge.find("./paramlist/param[@name='KV']").get("value") == shift
        wire = schematic.find(f"./Wire[@lcc_role='CB_REFERENCE_{suffix}']")
        origin = (int(wire.get("x")), int(wire.get("y")))
        points = [
            (origin[0] + int(v.get("x")), origin[1] + int(v.get("y")))
            for v in wire.findall("./vertex")
        ]
        assert points[0] == ((x, y - 36) if suffix == "Y" else (252, 540))
        assert points[-1] == (int(bridge.get("x")) - 18, int(bridge.get("y")) - 90)
        bus = schematic.find("./Wire[@lcc_role='REFERENCE_BUS']")
        origin = (int(bus.get("x")), int(bus.get("y")))
        bus_points = [
            (origin[0] + int(v.get("x")), origin[1] + int(v.get("y")))
            for v in bus.findall("./vertex")
        ]
        assert (x, y) in bus_points


def test_generated_bridge_passes_enable_to_g6p200_deblock_input(tmp_path):
    root = ET.fromstring(render_library())
    bridge = root.find("./definitions/Definition[@name='LCC12PulseBridge']")
    assert bridge is not None

    def wire_points(name):
        wire = bridge.find(f"./schematic/Wire[@lcc_role='{name}']")
        assert wire is not None
        origin = (int(wire.get("x")), int(wire.get("y")))
        return [
            (origin[0] + int(vertex.get("x")), origin[1] + int(vertex.get("y")))
            for vertex in wire.findall("./vertex")
        ]

    assert wire_points("ENABLE_TO_KB_Y")[0] == (600, 486)
    assert wire_points("ENABLE_TO_KB_D")[0] == (600, 486)
    assert bridge.find("./schematic/User[@defn='master:sumjct']") is None
    assert bridge.find("./schematic/User[@defn='master:consti']") is None


def test_generated_companion_contains_exact_wp1b_output_channels(tmp_path):
    path = tmp_path / "generated.pslx"
    path.write_bytes(render_library())

    evidence = audit_companion_library(path)

    assert sum(
        len(details["output_channels"])
        for details in evidence["definitions"].values()
    ) == 10
    root = ET.fromstring(path.read_bytes())
    assert root.find("./definitions/Definition[@name='Station']") is not None
    assert root.find("./definitions/Definition[@name='Main']") is not None
    assert root.find(
        "./hierarchy/call[@name='cigre_lcc_v1:Station']/call[@name='cigre_lcc_v1:Main']"
    ) is not None
    bridge = root.find("./definitions/Definition[@name='LCC12PulseBridge']")
    assert bridge is not None
    generated_wires = bridge.findall("./schematic/Wire")
    assert all(wire.get("name") == "" for wire in generated_wires)
    assert all(wire.get("lcc_role") for wire in generated_wires)
    assert [
        int(node.get("orient"))
        for node in bridge.findall("./schematic/User[@defn='master:xnode']")
    ] == [2, 2, 2, 2, 2, 2, 6, 4, 2, 2, 2]

    def points(name):
        wire = bridge.find(f"./schematic/Wire[@lcc_role='{name}']")
        assert wire is not None
        origin = (int(wire.get("x")), int(wire.get("y")))
        return [
            (origin[0] + int(vertex.get("x")), origin[1] + int(vertex.get("y")))
            for vertex in wire.findall("./vertex")
        ]

    def crosses(route, point):
        return any(
            left[0] == right[0] == point[0]
            and min(left[1], right[1]) <= point[1] <= max(left[1], right[1])
            or left[1] == right[1] == point[1]
            and min(left[0], right[0]) <= point[0] <= max(left[0], right[0])
            for left, right in pairwise(route)
        )

    assert not crosses(points("ACY_TO_Y_B"), (180, 342))
    assert not crosses(points("ACD_TO_D_B"), (180, 630))
    assert not crosses(points("ACY_TO_Y_BUS"), (216, 342))
    assert not crosses(points("ACD_TO_D_BUS"), (216, 630))
    assert points("DC_POS_PATH") == [(360, 252), (360, 234), (360, 162)]
    assert points("DC_SERIES") == [
        (360, 540),
        (360, 522),
        (360, 450),
        (360, 432),
    ]
    assert points("DC_NEG_PATH") == [(360, 720), (360, 738), (360, 828)]
    g6 = bridge.find("./schematic/User[@defn='master:g6p200']/paramlist")
    assert g6 is not None
    assert [param.get("name") for param in g6.findall("./param")] == [
        "UP",
        "FP",
        "SNUB",
        "KV",
        "View",
        "FR",
        "GP",
        "GI",
        "KP",
        "RON",
        "ROFF",
        "EFVD",
        "EBO",
        "TEXT",
        "CD",
        "RD",
        "FPNM",
        "VVolt",
        "VCurr",
        "SCurr",
        "Tblock",
        "RWSAFB",
        "RWV",
        "PFB",
    ]


@pytest.mark.parametrize(
    ("wire_name", "forbidden_port"),
        [
            ("CB_REFERENCE_Y", (360, 252)),
            ("CB_REFERENCE_D", (360, 540)),
        ],
)
def test_generated_bridge_control_wires_do_not_cross_unrelated_ports(
    wire_name,
    forbidden_port,
):
    root = ET.fromstring(render_library())
    bridge = root.find("./definitions/Definition[@name='LCC12PulseBridge']")
    assert bridge is not None
    wire = bridge.find(f"./schematic/Wire[@lcc_role='{wire_name}']")
    assert wire is not None
    origin = (int(wire.get("x")), int(wire.get("y")))
    route = [
        (origin[0] + int(vertex.get("x")), origin[1] + int(vertex.get("y")))
        for vertex in wire.findall("./vertex")
    ]

    assert not any(
        left[0] == right[0] == forbidden_port[0]
        and min(left[1], right[1]) <= forbidden_port[1] <= max(left[1], right[1])
        or left[1] == right[1] == forbidden_port[1]
        and min(left[0], right[0]) <= forbidden_port[0] <= max(left[0], right[0])
        for left, right in pairwise(route)
    )


def test_generated_bridge_isolates_scalar_phase_ports_before_breakout():
    root = ET.fromstring(render_library())
    bridge = root.find("./definitions/Definition[@name='LCC12PulseBridge']")
    assert bridge is not None

    resistors = bridge.findall("./schematic/User[@defn='master:resistor']")
    assert [(int(item.get("x")), int(item.get("y"))) for item in resistors] == [
        (108, 306),
        (108, 342),
        (108, 378),
        (108, 594),
        (108, 630),
        (108, 666),
        (108, 918),
        (108, 954),
        (108, 990),
    ]
    assert [
        item.find("./paramlist/param[@name='R']").get("value")
        for item in resistors
    ] == ["1.0e-6 [ohm]"] * 9
    assert [
        int(item.get("orient"))
        for item in bridge.findall("./schematic/User[@defn='master:breakout']")
    ] == [4, 4, 4]


def test_generated_control_imports_avoid_reserved_internal_names():
    root = ET.fromstring(render_library())

    for definition_name in ("RectifierControl", "InverterControl"):
        definition = root.find(
            f"./definitions/Definition[@name='{definition_name}']"
        )
        assert definition is not None
        port_names = {
            item.get("name") for item in definition.findall("./svg/port")
        }
        import_names = {
            item.get("value")
            for item in definition.findall(
                "./schematic/User[@defn='master:import']/paramlist/param[@name='Name']"
            )
        }

        assert {"VDC_MEAS", "IDC_MEAS"} <= port_names
        assert {"VDC_MEAS", "IDC_MEAS"} <= import_names
        assert not {"VDC", "IDC"} & import_names


def test_generated_inverter_converts_beta_to_alpha_after_limiting():
    root = ET.fromstring(render_library())
    schematic = root.find("./definitions/Definition[@name='InverterControl']/schematic")
    sums = [
        user for user in schematic.findall("./User[@defn='master:sumjct']")
        if user.find("./paramlist/param[@name='D']").get("value") == "-1"
    ]
    assert len(sums) == 1
    parameters = {p.get("name"): p.get("value") for p in sums[0].findall("./paramlist/param")}
    assert parameters == {"DPath": "1", "A": "0", "B": "1", "C": "0", "D": "-1", "E": "0", "F": "0", "G": "0"}
    constants = schematic.findall("./User[@defn='master:const']")
    assert len(constants) == 1
    assert float(constants[0].find("./paramlist/param[@name='Value']").get("value")) == pytest.approx(3.141592653589793)
    for name, expected in {
        "BETA_TO_ALPHA": [(810, 306), (846, 306)],
        "PI_TO_ALPHA": [(810, 90), (828, 90), (828, 270), (882, 270)],
    }.items():
        wire = schematic.find(f"./Wire[@lcc_role='{name}']")
        origin = (int(wire.get("x")), int(wire.get("y")))
        assert [
            (origin[0] + int(v.get("x")), origin[1] + int(v.get("y")))
            for v in wire.findall("./vertex")
        ] == expected
    for name in ("AO_Y_OUTPUT", "AO_D_OUTPUT", "AO_Y_MONITOR", "AO_D_MONITOR"):
        wire = schematic.find(f"./Wire[@lcc_role='{name}']")
        assert (int(wire.get("x")), int(wire.get("y"))) == (918, 306)


def test_generated_inverter_alpha_nets_are_orthogonal_and_separate():
    from pscad_mcp.topology.connectivity import build_connectivity
    from pscad_mcp.topology.models import ProjectTopology, TopologyConductor

    root = ET.fromstring(render_library())
    schematic = root.find("./definitions/Definition[@name='InverterControl']/schematic")
    ao_names = {"AO_Y_OUTPUT", "AO_D_OUTPUT", "AO_Y_MONITOR", "AO_D_MONITOR"}
    conductors = []
    for name in sorted(ao_names | {"PI_TO_ALPHA", "BETA_TO_ALPHA"}):
        wire = schematic.find(f"./Wire[@lcc_role='{name}']")
        origin = (int(wire.get("x")), int(wire.get("y")))
        vertices = tuple(
            (origin[0] + int(v.get("x")), origin[1] + int(v.get("y")))
            for v in wire.findall("./vertex")
        )
        assert all(a[0] == b[0] or a[1] == b[1] for a, b in pairwise(vertices))
        conductors.append(TopologyConductor(
            key=name, object_id=name, canvas_key="InverterControl",
            kind="wire", namespace="data", vertices=vertices,
        ))
    topology = build_connectivity(ProjectTopology(
        "inverter_alpha", "4.6.2", conductors=tuple(conductors),
    )).topology
    assert {frozenset(net.conductor_keys) for net in topology.nets} == {
        frozenset(ao_names), frozenset({"PI_TO_ALPHA"}), frozenset({"BETA_TO_ALPHA"}),
    }


def test_generated_inverter_gamma_signal_uses_one_nonbranching_trunk():
    root = ET.fromstring(render_library())
    definition = root.find(
        "./definitions/Definition[@name='InverterControl']"
    )
    assert definition is not None

    def points(role):
        wire = definition.find(f"./schematic/Wire[@lcc_role='{role}']")
        assert wire is not None
        origin = (int(wire.get("x")), int(wire.get("y")))
        return [
            (origin[0] + int(vertex.get("x")), origin[1] + int(vertex.get("y")))
            for vertex in wire.findall("./vertex")
        ]

    assert points("GAMMA_MIN") == [
        (126, 198),
        (216, 198),
        (216, 234),
        (252, 234),
    ]
    assert points("GAMMA_ERROR") == [
        (126, 342),
        (342, 342),
        (342, 306),
        (378, 306),
    ]
    assert points("GAMMA_FANOUT") == [
        (324, 234),
        (342, 234),
        (342, 180),
        (396, 180),
        (450, 180),
        (468, 180),
        (468, 342),
        (414, 342),
    ]
    assert definition.find("./schematic/Wire[@lcc_role='GAMMA_OUTPUT']") is None
    assert definition.find("./schematic/Wire[@lcc_role='GAMMA_MONITOR']") is None
    gamma_export = next(
        item
        for item in definition.findall("./schematic/User[@defn='master:export']")
        if item.find("./paramlist/param[@name='Name']").get("value") == "GAMMA"
    )
    assert (int(gamma_export.get("x")), int(gamma_export.get("y"))) == (414, 180)


def test_generated_signal_interface_isolates_raw_inputs_before_fanout():
    root = ET.fromstring(render_library())
    definition = root.find(
        "./definitions/Definition[@name='SignalInterface']"
    )
    assert definition is not None
    assert [item.get("name") for item in definition.findall("./svg/port")] == [
        "VDC_RECT_RAW",
        "VDC_INV_RAW",
        "IDC_RAW",
        "VDC_RECT",
        "VDC_INV",
        "IDC",
        "AM_Y", "AM_D", "GM_Y", "GM_D",
        "P_RECT_A", "P_RECT_B", "P_RECT_C", "P_INV_A", "P_INV_B", "P_INV_C",
        "ALPHA_RECT", "MU_RECT", "P_RECT", "P_INV",
    ]
    assert [
        item.get("value")
        for item in definition.findall(
            "./schematic/User[@defn='master:import']/paramlist/param[@name='Name']"
        )
    ] == ["VDC_RECT_RAW", "VDC_INV_RAW", "IDC_RAW", "AM_Y", "AM_D", "GM_Y", "GM_D", "P_RECT_A", "P_RECT_B", "P_RECT_C", "P_INV_A", "P_INV_B", "P_INV_C"]
    unity = definition.findall("./schematic/User[@defn='master:unity']")
    assert len(unity) == 2
    assert [
        item.find("./paramlist/param[@name='OType']").get("value")
        for item in unity
    ] == ["2", "2"]
    assert {
        item.get("lcc_role") for item in definition.findall("./schematic/Wire")
    } == {
        "VDC_RECT_RAW_TO_UNITY",
        "VDC_RECT_FANOUT",
        "VDC_INV_RAW_TO_NEGATE",
        "VDC_INV_ZERO_TO_NEGATE",
        "VDC_INV_FANOUT",
        "IDC_RAW_TO_UNITY",
        "IDC_FANOUT",
        "AM_Y_TO_MAX", "AM_D_TO_MAX", "ALPHA_MEASURED_OUTPUT",
        "AM_Y_TO_OVERLAP", "AM_D_TO_OVERLAP", "GM_Y_TO_OVERLAP", "GM_D_TO_OVERLAP",
        "PI_TO_OVERLAP_Y", "PI_TO_OVERLAP_D", "OVERLAP_Y_TO_MAX", "OVERLAP_D_TO_MAX", "OVERLAP_MEASURED_OUTPUT",
        "P_RECT_A_TO_SUM", "P_RECT_B_TO_SUM", "P_RECT_C_TO_SUM", "P_RECT_TOTAL_OUTPUT",
        "P_INV_A_TO_SUM", "P_INV_B_TO_SUM", "P_INV_C_TO_SUM", "P_INV_TOTAL_OUTPUT",
    }


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("remove_second_bridge", "master_instance_count"),
        ("add_gates_port", "external_port_mismatch"),
        ("remove_ao_wire", "internal_connection_missing"),
        ("copy_master_definition", "vendor_definition_body"),
        ("duplicate_definition", "duplicate_definition"),
        ("add_absolute_path", "absolute_path"),
        ("add_foreign_scope", "foreign_scope"),
    ],
)
def test_physical_audit_fails_closed(tmp_path, mutation, reason):
    path = write_physical_library_fixture(tmp_path, mutation=mutation)

    with pytest.raises(BackendError) as failure:
        audit_companion_library(path)

    assert reason in {
        item["reason"] for item in failure.value.details["errors"]
    }


def test_physical_audit_rejects_invalid_xml(tmp_path):
    path = tmp_path / "invalid.pslx"
    path.write_text("<project>", encoding="utf-8")

    with pytest.raises(BackendError) as failure:
        audit_companion_library(path)

    assert failure.value.code == "LCC_COMPANION_INVALID"
    assert failure.value.details["errors"][0]["reason"] == "parse_failure"
