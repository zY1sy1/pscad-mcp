import os
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.template_audit import (
    audit_mmc_template,
    discover_official_mmc_template,
)
from tests.mmc_parametric_fakes import make_synthetic_official_shape, sha256


def test_audit_reports_sources_roles_and_absolute_paths_without_writes(
    tmp_path: Path,
) -> None:
    project, library = make_synthetic_official_shape(tmp_path)
    before = (project.read_bytes(), library.read_bytes())
    report = audit_mmc_template(project, library)
    assert report["compatible"] is True
    assert report["pscad_version"] == "4.6.2"
    assert report["model_fidelity"] == "detailed_pwm"
    assert report["source_hashes"] == {
        "project": sha256(project),
        "library": sha256(library),
    }
    assert {item["kind"] for item in report["absolute_paths"]} == {
        "startup_snapshot",
        "line_database",
        "line_constants",
    }
    assert before == (project.read_bytes(), library.read_bytes())


def test_discovery_is_bounded_to_public_pscad_46_example_tree(tmp_path: Path) -> None:
    directory = (
        tmp_path / "Documents" / "PSCAD" / "4.6" / "Examples" / "ModelsInProgress"
    )
    project, library = make_synthetic_official_shape(directory)
    assert discover_official_mmc_template(tmp_path) == (
        project.resolve(),
        library.resolve(),
    )


def test_audit_rejects_partial_template_pair(tmp_path: Path) -> None:
    project, _ = make_synthetic_official_shape(tmp_path)
    with pytest.raises(BackendError) as raised:
        audit_mmc_template(project, None)
    assert raised.value.code == "MMC_TEMPLATE_PAIR_INVALID"


def test_audit_rejects_symlinked_template_pair(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path)
    project_alias = tmp_path / "project-alias.pscx"
    library_alias = tmp_path / "library-alias.pslx"
    try:
        project_alias.symlink_to(project)
        library_alias.symlink_to(library)
    except OSError as error:
        pytest.skip(f"file symlinks unavailable: {error}")

    with pytest.raises(BackendError) as raised:
        audit_mmc_template(project_alias, library_alias)

    assert raised.value.code == "MMC_TEMPLATE_NOT_FOUND"


def test_audit_marks_existing_line_constants_as_verified_rebind(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path)
    constants = tmp_path / "line.tlo"
    constants.write_bytes(b"public-lcp-output")
    text = project.read_text(encoding="utf-8")
    project.write_text(
        text.replace(r"C:\synthetic\line_constants.tlo", str(constants)),
        encoding="utf-8",
    )
    report = audit_mmc_template(project, library)
    policies = {
        item["kind"]: item["repair_policy"] for item in report["absolute_paths"]
    }
    assert policies["line_constants"] == "verified_rebind"


def test_audit_records_official_library_object_dependencies(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path)
    library.write_text(
        library.read_text(encoding="utf-8").replace(
            "</library>",
            '<param name="object" value="Obj_Files_2016_03_25\\\\$(Compiler)\\\\x.obj" /></library>',
        ),
        encoding="utf-8",
    )
    support = library.parent / "Obj_Files_2016_03_25" / "gf42"
    support.mkdir(parents=True)
    object_file = support / "x.obj"
    object_file.write_bytes(b"object")

    report = audit_mmc_template(project, library)

    assert report["compiler_support"]["required"] is True
    assert report["compiler_support"]["hashes"]["gf42/x.obj"]
    assert report["compatible"] is True


def test_audit_binds_declared_compiler_libraries_and_legacy_object_union(tmp_path):
    from xml.etree import ElementTree as ET
    project, library = make_synthetic_official_shape(tmp_path)
    tree = ET.parse(library)
    params = ET.SubElement(tree.getroot(), "paramlist", {"name": "Libs"})
    ET.SubElement(params, "param", {"name": "0", "value": r".\lib\$(Compiler)\intermediate.lib"})
    tree.write(library, encoding="utf-8")
    linked = tmp_path / "lib" / "gf42" / "intermediate.lib"
    linked.parent.mkdir(parents=True)
    linked.write_bytes(b"synthetic-compiler-library")
    object_file = tmp_path / "Obj_Files_2016_03_25" / "gf42" / "x.obj"
    object_file.parent.mkdir(parents=True)
    object_file.write_bytes(b"synthetic-object")
    report = audit_mmc_template(project, library)
    support = report["compiler_support"]
    assert support["link_libraries"]["required"] is True
    assert support["link_libraries"]["present"] is True
    assert support["link_libraries"]["files"][0] == {"path": str(linked.resolve()), "relative_path": "lib/gf42/intermediate.lib", "compiler": "gf42", "sha256": sha256(linked)}
    assert {item["relative_path"] for item in support["files"]} == {"lib/gf42/intermediate.lib", "Obj_Files_2016_03_25/gf42/x.obj"}
    assert report["compatible"] is True


def test_audit_rejects_missing_declared_link_library(tmp_path):
    from xml.etree import ElementTree as ET
    project, library = make_synthetic_official_shape(tmp_path)
    tree = ET.parse(library)
    params = ET.SubElement(tree.getroot(), "paramlist", {"name": "Libs"})
    ET.SubElement(params, "param", {"name": "0", "value": r".\lib\$(Compiler)\intermediate.lib"})
    tree.write(library, encoding="utf-8")
    report = audit_mmc_template(project, library)
    assert report["compatible"] is False
    assert report["compiler_support"]["link_libraries"]["present"] is False


def test_audit_legacy_fixture_without_libs_remains_compatible(tmp_path):
    project, library = make_synthetic_official_shape(tmp_path)
    report = audit_mmc_template(project, library)
    assert report["compatible"] is True
    assert report["compiler_support"]["link_libraries"] == {"required": False, "present": True, "declarations": [], "files": []}


@pytest.mark.parametrize("declared", [r"\lib\intermediate.lib", r"C:lib\intermediate.lib"])
def test_audit_rejects_windows_anchored_nonabsolute_link_paths(tmp_path, declared):
    from xml.etree import ElementTree as ET
    project, library = make_synthetic_official_shape(tmp_path)
    tree = ET.parse(library)
    params = ET.SubElement(tree.getroot(), "paramlist", {"name": "Libs"})
    ET.SubElement(params, "param", {"name": "0", "value": declared})
    tree.write(library, encoding="utf-8")
    substitute = tmp_path / "lib" / "intermediate.lib"
    substitute.parent.mkdir()
    substitute.write_bytes(b"unrelated-sibling")
    report = audit_mmc_template(project, library)
    assert report["compatible"] is False
    assert report["compiler_support"]["files"] == []


def test_audit_rejects_object_directory_resolving_outside_library(tmp_path, monkeypatch):
    project, library = make_synthetic_official_shape(tmp_path)
    library.write_text(library.read_text().replace("</library>", '<param name="object" value="Obj_Files_2016_03_25/gf42/x.obj" /></library>'))
    support = tmp_path / "Obj_Files_2016_03_25"
    support.mkdir()
    (support / "x.obj").write_bytes(b"synthetic-object")
    real_resolve = Path.resolve
    outside = tmp_path.parent / "foreign-object-tree"
    def resolve(path, *args, **kwargs):
        if path == support or support in path.parents:
            return outside / path.relative_to(support)
        return real_resolve(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", resolve)
    report = audit_mmc_template(project, library)
    assert report["compatible"] is False
    assert report["compiler_support"]["present"] is False
    assert report["compiler_support"]["files"] == []


def test_audit_records_template_native_emt_control_contract(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path)
    text = project.read_text(encoding="utf-8")
    text = text.replace(
        "</project>",
        """
        <User classid='UserCmp' id='9001' defn='master:time-sig' />
        <User classid='UserCmp' id='9002' defn='master:tfaultn' />
        <User classid='UserCmp' id='9003' defn='master:var'>
          <param name='Name' value='Fault Time' />
          <param name='Value' value='2.5' />
        </User>
        <User classid='UserCmp' id='9004' defn='master:var_switch'>
          <param name='Name' value='AC Fault type' />
          <param name='Value' value='0' />
        </User>
        </project>""",
    )
    project.write_text(text, encoding="utf-8")

    report = audit_mmc_template(project, library)

    native = report["template_native_controls"]
    assert native["available"] is True
    assert native["time_basis"] == "EMTDC"
    assert native["components"]["Fault Time"] == {
        "owner": "9003",
        "definition": "master:var",
        "parameter": "Value",
        "value": "2.5",
    }
    assert native["components"]["AC Fault type"]["owner"] == "9004"


def test_audit_detects_native_full_cell_and_hbridge_contract(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path)
    project_text = project.read_text(encoding="utf-8").replace(
        "</schematic>",
        """
        <User classid='UserCmp' id='9101' defn='intermediate:FullCellR_n'>
          <paramlist><param name='DTBP' value='0' /></paramlist>
        </User>
        <User classid='UserCmp' id='9102' defn='intermediate:FiringHBridge' />
        </schematic>""",
    )
    project.write_text(project_text, encoding="utf-8")
    library_text = library.read_text(encoding="utf-8").replace(
        "</library>",
        "<Definition classid='UserCmpDefn' name='FullCellR_n' />"
        "<Definition classid='UserCmpDefn' name='FiringHBridge' /></library>",
    )
    library.write_text(library_text, encoding="utf-8")

    report = audit_mmc_template(project, library)

    assert report["submodule_topology"]["declared"] == "full_bridge"
    assert report["submodule_topology"]["full_cell_instances"] == 1
    assert report["submodule_topology"]["firing_hbridge_instances"] == 1


def test_audit_does_not_count_library_prototypes_as_half_bridge_instances(
    tmp_path: Path,
) -> None:
    project, library = make_synthetic_official_shape(tmp_path)
    project_text = project.read_text(encoding="utf-8").replace(
        "</schematic>",
        """
        <User classid='UserCmp' id='9201' defn='intermediate:HalfCell_Sdt' />
        <User classid='UserCmp' id='9202' defn='intermediate:FiringBlockVSC' />
        </schematic>""",
        1,
    )
    project.write_text(project_text, encoding="utf-8")
    library_text = library.read_text(encoding="utf-8").replace(
        "</library>",
        """
        <Definition classid='UserCmpDefn' name='FullCellR_n'>
          <schematic><User classid='UserCmp' id='p1' defn='intermediate:FullCellR_n' /></schematic>
        </Definition>
        <Definition classid='UserCmpDefn' name='FiringHBridge'>
          <schematic><User classid='UserCmp' id='p2' defn='intermediate:FiringHBridge' /></schematic>
        </Definition>
        </library>""",
        1,
    )
    library.write_text(library_text, encoding="utf-8")

    report = audit_mmc_template(project, library)

    assert report["submodule_topology"]["declared"] == "half_bridge"
    assert report["submodule_topology"]["full_cell_instances"] == 0
    assert report["submodule_topology"]["firing_hbridge_instances"] == 0
    assert report["submodule_topology"]["half_cell_instances"] == 1


def test_installed_example_contract_is_read_only() -> None:
    try:
        project, library = discover_official_mmc_template()
    except BackendError as error:
        if error.code == "MMC_TEMPLATE_NOT_FOUND":
            pytest.skip("PSCAD 4.6 MMC example is not installed")
        raise
    before = (sha256(project), sha256(library))
    report = audit_mmc_template(project, library)
    assert report["source_hashes"] == {"project": before[0], "library": before[1]}
    assert before == (sha256(project), sha256(library))
    if os.environ.get("PSCAD_MCP_MMC_ACCEPTANCE") == "1":
        assert report["pscad_version"] == "4.6.2"


def test_installed_example_exposes_station_and_pwm_hierarchy_roles() -> None:
    try:
        project, library = discover_official_mmc_template()
    except BackendError as error:
        if error.code == "MMC_TEMPLATE_NOT_FOUND":
            pytest.skip("PSCAD 4.6 MMC example is not installed")
        raise
    report = audit_mmc_template(project, library)
    roles = {item["role"] for item in report["role_bindings"]}
    assert report["compatible"] is True
    assert {"station_p", "station_vdc"} <= roles
    assert len([role for role in roles if role.startswith("pwm_converter_")]) >= 2


def test_installed_topology_counts_reachable_arm_instances():
    try:
        project, library = discover_official_mmc_template()
    except BackendError:
        pytest.skip("Installed MMC source is unavailable")
    report = audit_mmc_template(project, library)
    assert report["submodule_topology"]["full_cell_instances"] == 12
    cells = [item for item in report["instance_bindings"] if item["definition"] == "intermediate:FullCellR_n"]
    assert len(cells) == 12
    assert len({item["instance_path"] for item in cells}) == 12
    assert all("Main[" in item["instance_path"] and "MMC_Hb_PWM[" in item["instance_path"] for item in cells)


def test_unused_fullbridge_definition_cannot_override_active_halfbridge(tmp_path):
    from xml.etree import ElementTree as ET
    project, library = make_synthetic_official_shape(tmp_path)
    tree = ET.parse(project)
    main = tree.find("./definitions/Definition/schematic")
    ET.SubElement(main, "User", {"classid": "UserCmp", "id": "active-half", "defn": "intermediate:HalfCell_Sdt"})
    unused = ET.SubElement(tree.find("definitions"), "Definition", {"name": "UnusedFullbridge"})
    canvas = ET.SubElement(unused, "schematic")
    ET.SubElement(canvas, "User", {"classid": "UserCmp", "id": "unused-cell", "defn": "intermediate:FullCellR_n"})
    ET.SubElement(canvas, "User", {"classid": "UserCmp", "id": "unused-firing", "defn": "intermediate:FiringHBridge"})
    tree.write(project, encoding="utf-8")
    report = audit_mmc_template(project, library)
    assert report["submodule_topology"]["declared"] == "half_bridge"
    assert report["submodule_topology"]["full_cell_instances"] == 0
