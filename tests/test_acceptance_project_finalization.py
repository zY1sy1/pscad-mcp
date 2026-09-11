"""Strict authored-to-compiler-normalized PSCX comparison contracts."""

from __future__ import annotations

import copy
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.acceptance.project_finalization import (
    GENERATED_MODULE_POLICY,
    POLICY,
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
        classid="UserCmp",
        id="2",
        defn="master:resistor",
        x="180",
        y="180",
        w="40",
        h="30",
        z="-1",
        orient="0",
    )
    parameters = ET.SubElement(user, "paramlist", name="", link="-1", crc="321")
    ET.SubElement(parameters, "param", name="R", value="10.0")
    ET.SubElement(parameters, "param", name="revisor", value="electrical parameter")
    wire = ET.SubElement(
        schematic, "Wire", id="3", x="180", y="180", w="82", h="10", z="-1"
    )
    ET.SubElement(wire, "vertex", x="0", y="0")
    ET.SubElement(wire, "vertex", x="108", y="0")
    station = ET.SubElement(
        ET.SubElement(root, "hierarchy"),
        "call",
        name="Fixture:Station",
        link="100",
        z="-1",
        view="false",
        instance="0",
    )
    main = ET.SubElement(
        station,
        "call",
        name="Fixture:Main",
        link="101",
        z="-1",
        view="true",
        instance="0",
    )
    ET.SubElement(
        main,
        "call",
        name="mmc_average_arm:MMCAverageArm",
        link="2",
        z="0",
        view="false",
        instance="0",
    )
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


@pytest.mark.parametrize(
    "mutation", ["code", "child_order", "new_parameter", "comment"]
)
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


@pytest.mark.parametrize(
    "xpath,attribute,value",
    [
        (".//User", "w", "112"),
        (".//User", "h", "400"),
        (".//User/paramlist", "crc", "103300890"),
        ("./hierarchy/call", "link", "65436030"),
    ],
)
def test_generated_module_metadata_requires_explicit_optin(
    tmp_path, xpath, attribute, value
):
    path, root = project(tmp_path)
    original_default = snapshot_project_semantics(path)
    authored = snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)
    root.find(xpath).set(attribute, value)
    write(path, root)
    finalized = snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)
    evidence = compare_project_finalization(authored, finalized)
    assert original_default["policy"] == POLICY
    assert evidence["policy"] == GENERATED_MODULE_POLICY
    assert evidence["semantic_structure_unchanged"] is True
    assert len(evidence["metadata_changes"]) == 1
    with pytest.raises(ValueError, match="semantic"):
        compare_project_finalization(original_default, snapshot_project_semantics(path))


@pytest.mark.parametrize(
    "xpath,attribute,value",
    [
        (".//User/paramlist/param[@name='R']", "value", "11"),
        (".//User", "id", "5"),
        (".//User", "defn", "master:inductor"),
        (".//User", "x", "198"),
        (".//User", "y", "198"),
        (".//User", "orient", "1"),
        (".//Wire/vertex", "x", "18"),
        (".//svg/port", "dim", "3"),
        (".//User/paramlist", "link", "0"),
        (".//User/paramlist", "name", "changed"),
        ("./hierarchy/call", "name", "Fixture:Other"),
        ("./hierarchy/call", "z", "0"),
        ("./hierarchy/call", "instance", "1"),
        ("./hierarchy/call/call", "link", "102"),
        ("./hierarchy/call/call/call", "link", "5"),
        ("./hierarchy/call/call/call", "name", "other:MMCAverageArm"),
        ("./hierarchy/call/call/call", "instance", "1"),
        ("./hierarchy/call/call/call", "z", "1"),
        ("./hierarchy/call/call/call", "view", "true"),
    ],
)
def test_generated_module_policy_preserves_physical_and_nested_hierarchy_fields(
    tmp_path, xpath, attribute, value
):
    path, root = project(tmp_path)
    authored = snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)
    root.find(xpath).set(attribute, value)
    write(path, root)
    with pytest.raises(ValueError, match="semantic"):
        compare_project_finalization(
            authored, snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)
        )


@pytest.mark.parametrize("mutation", ["remove_child", "add_child", "order", "script"])
def test_generated_module_policy_preserves_hierarchy_structure_and_script(
    tmp_path, mutation
):
    path, root = project(tmp_path)
    main = root.find("./hierarchy/call/call")
    extra = ET.SubElement(main, "call", name="module:Other", link="3", z="1")
    write(path, root)
    authored = snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)
    if mutation == "remove_child":
        main.remove(extra)
    elif mutation == "add_child":
        ET.SubElement(main, "call", name="module:New", link="4", z="2")
    elif mutation == "order":
        main[:] = list(reversed(main[:]))
    else:
        root.find(".//script").text = "V = R / I"
    write(path, root)
    with pytest.raises(ValueError, match="semantic"):
        compare_project_finalization(
            authored, snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)
        )


@pytest.mark.parametrize(
    "setup_xpath,setup_attribute,setup_value,changed_xpath,changed_attribute",
    [
        (".//User", "classid", "Other", ".//User", "w"),
        (".//User", "classid", "Other", ".//User/paramlist", "crc"),
        (".//User/paramlist", "name", "Other", ".//User/paramlist", "crc"),
        (".//User/paramlist", "link", "0", ".//User/paramlist", "crc"),
        ("./hierarchy/call", "name", "Other:Station", "./hierarchy/call", "link"),
    ],
)
def test_generated_module_exceptions_require_the_exact_context(
    tmp_path,
    setup_xpath,
    setup_attribute,
    setup_value,
    changed_xpath,
    changed_attribute,
):
    path, root = project(tmp_path)
    root.find(setup_xpath).set(setup_attribute, setup_value)
    write(path, root)
    authored = snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)
    root.find(changed_xpath).set(changed_attribute, "999")
    write(path, root)
    with pytest.raises(ValueError, match="semantic"):
        compare_project_finalization(
            authored, snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)
        )


def test_project_finalization_policies_cannot_be_mixed_or_unknown(tmp_path):
    path, _ = project(tmp_path)
    normal = snapshot_project_semantics(path)
    generated = snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)
    with pytest.raises(ValueError, match="polic"):
        compare_project_finalization(normal, generated)
    with pytest.raises(ValueError, match="polic"):
        snapshot_project_semantics(path, policy="ignore_everything")
    forged = copy.deepcopy(generated)
    forged["policy"] = "ignore_everything"
    with pytest.raises(ValueError, match="polic"):
        compare_project_finalization(forged, generated)
