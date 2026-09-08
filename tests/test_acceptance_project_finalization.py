"""Strict authored-to-compiler-normalized PSCX comparison contracts."""

from __future__ import annotations

import copy
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.acceptance.project_finalization import (
    compare_project_finalization,
    snapshot_project_semantics,
)


def project(tmp_path):
    path = tmp_path / "fixture.pscx"
    root = ET.Element("project", name="Fixture", version="4.6.2")
    settings = ET.SubElement(root, "paramlist", name="Settings")
    ET.SubElement(settings, "param", name="revisor", value="user, 0")
    ET.SubElement(settings, "param", name="output_filename", value="Fixture.out")
    definition = ET.SubElement(
        ET.SubElement(root, "definitions"),
        "Definition",
        name="Main",
        id="1",
        date="0",
        crc="123",
    )
    svg = ET.SubElement(definition, "svg")
    ET.SubElement(svg, "port", name="IN", x="0", y="0", dim="1").text = "true"
    code = ET.SubElement(definition, "script")
    code.text = "\n  V = R * I\n"
    schematic = ET.SubElement(definition, "schematic")
    sequence = ET.SubElement(schematic, "paramlist")
    ET.SubElement(sequence, "param", name="auto_sequence", value="1")
    user = ET.SubElement(
        schematic,
        "User",
        id="2",
        defn="master:resistor",
        x="180",
        y="180",
        w="40",
        h="30",
        z="-1",
        orient="0",
    )
    parameters = ET.SubElement(user, "paramlist", crc="321")
    ET.SubElement(parameters, "param", name="R", value="10.0")
    ET.SubElement(parameters, "param", name="revisor", value="electrical parameter")
    wire = ET.SubElement(
        schematic, "Wire", id="3", x="180", y="180", w="82", h="10", z="-1"
    )
    ET.SubElement(wire, "vertex", x="0", y="0")
    ET.SubElement(wire, "vertex", x="108", y="0")
    write(path, root)
    return path, root


def write(path, root):
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_known_native_metadata_changes_preserve_authored_semantics(tmp_path):
    path, root = project(tmp_path)
    authored = snapshot_project_semantics(path)
    root.find("./paramlist/param[@name='revisor']").set("value", "user, 100")
    definition = root.find("./definitions/Definition")
    definition.set("date", "100")
    definition.set("crc", "456")
    definition.find("./schematic/User").set("z", "1")
    wire = definition.find("./schematic/Wire")
    wire.set("z", "2")
    wire.set("w", "118")
    wire.set("h", "28")
    write(path, root)
    finalized = snapshot_project_semantics(path)
    result = compare_project_finalization(authored, finalized)
    assert result["semantic_structure_unchanged"] is True
    assert authored["sha256"] != finalized["sha256"]
    assert authored["semantics_sha256"] == finalized["semantics_sha256"]
    assert len(result["metadata_changes"]) == 7


@pytest.mark.parametrize(
    "xpath,attribute,value",
    [
        ("./paramlist/param[@name='output_filename']", "value", "Other.out"),
        ("./definitions/Definition", "id", "4"),
        (".//User", "id", "4"),
        (".//User", "defn", "master:inductor"),
        (".//User", "x", "198"),
        (".//User", "y", "198"),
        (".//User", "orient", "1"),
        (".//User", "w", "44"),
        (".//User/paramlist", "crc", "999"),
        (".//User/paramlist/param[@name='R']", "value", "11.0"),
        (".//User/paramlist/param[@name='revisor']", "value", "changed"),
        (".//Wire", "id", "4"),
        (".//Wire", "x", "198"),
        (".//Wire/vertex", "x", "18"),
        (".//svg/port", "dim", "3"),
        (".//schematic/paramlist/param", "value", "0"),
    ],
)
def test_parameter_identity_port_and_geometry_changes_are_rejected(
    tmp_path, xpath, attribute, value
):
    path, root = project(tmp_path)
    authored = snapshot_project_semantics(path)
    root.find(xpath).set(attribute, value)
    write(path, root)
    with pytest.raises(ValueError, match="semantic"):
        compare_project_finalization(authored, snapshot_project_semantics(path))


@pytest.mark.parametrize("mutation", ["code", "child_order", "new_parameter", "comment"])
def test_content_and_structure_are_not_discarded(tmp_path, mutation):
    path, root = project(tmp_path)
    authored = snapshot_project_semantics(path)
    if mutation == "code":
        root.find(".//script").text = "\n  V = R / I\n"
    elif mutation == "child_order":
        wire = root.find(".//Wire")
        wire[:] = list(reversed(wire[:]))
    elif mutation == "new_parameter":
        ET.SubElement(root.find(".//User/paramlist"), "param", name="L", value="1")
    else:
        root.append(ET.Comment("new content"))
    write(path, root)
    with pytest.raises(ValueError, match="semantic"):
        compare_project_finalization(authored, snapshot_project_semantics(path))


def test_execution_order_stays_semantic_without_automatic_sequencing(tmp_path):
    path, root = project(tmp_path)
    root.find(".//schematic/paramlist/param").set("value", "0")
    write(path, root)
    authored = snapshot_project_semantics(path)
    root.find(".//User").set("z", "10")
    write(path, root)
    with pytest.raises(ValueError, match="semantic"):
        compare_project_finalization(authored, snapshot_project_semantics(path))


def test_xml_indentation_is_not_semantic_but_leaf_text_whitespace_is(tmp_path):
    path, root = project(tmp_path)
    authored = snapshot_project_semantics(path)
    ET.indent(root)
    write(path, root)
    assert compare_project_finalization(authored, snapshot_project_semantics(path))[
        "semantic_structure_unchanged"
    ]
    root.find(".//script").text = "\n V = R * I\n"
    write(path, root)
    with pytest.raises(ValueError, match="semantic"):
        compare_project_finalization(authored, snapshot_project_semantics(path))


def test_forged_snapshot_hash_does_not_hide_a_structure_change(tmp_path):
    path, _ = project(tmp_path)
    authored = snapshot_project_semantics(path)
    finalized = copy.deepcopy(authored)
    finalized["semantics"]["attributes"]["name"] = "Other"
    with pytest.raises(ValueError, match="hash"):
        compare_project_finalization(authored, finalized)


def test_non_project_xml_is_rejected(tmp_path):
    path = tmp_path / "not-project.xml"
    path.write_text("<other />", encoding="utf-8")
    with pytest.raises(ValueError, match="project"):
        snapshot_project_semantics(path)
