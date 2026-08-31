from __future__ import annotations

import xml.etree.ElementTree as ET
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
        ("ENABLE", "Transfer", "Input", "Integer"),
        ("AM_Y", "Transfer", "Output", "Real"),
        ("AM_D", "Transfer", "Output", "Real"),
        ("GM_Y", "Transfer", "Output", "Real"),
        ("GM_D", "Transfer", "Output", "Real"),
    ),
    "RectifierControl": (
        ("VDC", "Transfer", "Input", "Real"),
        ("IDC", "Transfer", "Input", "Real"),
        ("IORDER", "Transfer", "Input", "Real"),
        ("ENABLE", "Transfer", "Input", "Integer"),
        ("AO_Y", "Transfer", "Output", "Real"),
        ("AO_D", "Transfer", "Output", "Real"),
        ("ALPHA", "Transfer", "Output", "Real"),
    ),
    "InverterControl": (
        ("VDC", "Transfer", "Input", "Real"),
        ("IDC", "Transfer", "Input", "Real"),
        ("GM_Y", "Transfer", "Input", "Real"),
        ("GM_D", "Transfer", "Input", "Real"),
        ("GAMMA_ORDER", "Transfer", "Input", "Real"),
        ("ENABLE", "Transfer", "Input", "Integer"),
        ("AO_Y", "Transfer", "Output", "Real"),
        ("AO_D", "Transfer", "Output", "Real"),
        ("GAMMA", "Transfer", "Output", "Real"),
    ),
    "Initialization": (
        ("IORDER", "Transfer", "Output", "Real"),
        ("GAMMA_ORDER", "Transfer", "Output", "Real"),
        ("ENABLE_RECT", "Transfer", "Output", "Integer"),
        ("ENABLE_INV", "Transfer", "Output", "Integer"),
    ),
    "SignalInterface": (
        ("VDC_RECT", "Transfer", "Output", "Real"),
        ("VDC_INV", "Transfer", "Output", "Real"),
        ("IDC", "Transfer", "Output", "Real"),
    ),
}

USERS = {
    "LCC12PulseBridge": (
        "master:g6p200",
        "master:g6p200",
        *("master:pin" for _ in range(8)),
        "master:breakout",
        "master:breakout",
        *("master:import" for _ in range(3)),
        *("master:export" for _ in range(4)),
        "master:consti",
        "master:consti",
        "master:sumjct",
    ),
    "RectifierControl": (
        *("master:import" for _ in range(4)),
        *("master:export" for _ in range(3)),
        "master:unity",
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
        "master:unity",
        "master:maxmin",
        "master:sumjct",
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
        "master:import",
        "master:import",
        "master:import",
        "master:export",
        "master:export",
        "master:export",
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
        "CB_ZERO_Y",
        "CB_ZERO_D",
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
        "ENABLE_PRODUCT",
        "PI_TO_LIMIT",
        "AO_Y_OUTPUT",
        "AO_D_OUTPUT",
        "GAMMA_OUTPUT",
        "AO_Y_MONITOR",
        "AO_D_MONITOR",
        "GAMMA_MONITOR",
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
        "VDC_RECT_IMPORT",
        "VDC_INV_IMPORT",
        "IDC_IMPORT",
        "VDC_RECT_MONITOR",
        "VDC_INV_MONITOR",
        "IDC_MONITOR",
    ),
}

OUTPUT_NAMES = {
    "LCC12PulseBridge": (),
    "RectifierControl": ("AO_RECT_Y", "AO_RECT_D"),
    "InverterControl": ("AO_INV_Y", "AO_INV_D", "GAMMA_INV"),
    "Initialization": ("ENABLE_RECT", "ENABLE_INV"),
    "SignalInterface": ("VDC_RECT", "VDC_INV", "IDC"),
}


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
                {"id": str(2000 + wire_index), "name": wire_name},
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
    assert bridge["master_instances"]["master:pin"] == 8
    assert bridge["master_instances"]["master:breakout"] == 2
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


def test_generated_companion_contains_exact_wp1b_output_channels(tmp_path):
    path = tmp_path / "generated.pslx"
    path.write_bytes(render_library())

    evidence = audit_companion_library(path)

    assert sum(
        len(details["output_channels"])
        for details in evidence["definitions"].values()
    ) == 10


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
