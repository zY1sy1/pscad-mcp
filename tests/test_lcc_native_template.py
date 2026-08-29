from __future__ import annotations

from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.master_bindings import audit_master_bindings
from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set
from pscad_mcp.hvdc.builders.lcc.native_template import (
    audit_native_lcc_template,
    evaluate_native_lcc_commutation,
    materialize_native_lcc_bundle,
)
from tests.test_master_binding_registry import _master_fixture_xml


def _template(path: Path) -> Path:
    path.write_text(
        '''<project name="Official" version="4.6.2" schema="" Target="EMTDC">
  <paramlist name="Settings">
    <param name="time_duration" value="1" />
    <param name="time_step" value="50" />
    <param name="sample_step" value="250" />
    <param name="PlotType" value="0" />
    <param name="output_filename" value="Official.out" />
  </paramlist>
  <output name="Official"><domain name="Time" unit="s" /><analog>
    <channel index="0" id="100:0" name="DC Current" label="Inverter" dim="1" unit="pu" />
  </analog><digital /></output>
  <definitions>
    <Definition classid="StationDefn" name="Station">
      <schematic classid="StationCanvas"><User classid="UserCmp" defn="Official:Main" id="1" /></schematic>
    </Definition>
    <Definition classid="UserCmpDefn" name="Main">
      <schematic classid="UserCanvas">
        <User classid="UserCmp" name="Official:Rectifier" defn="Official:Rectifier" id="10" x="100" y="100" />
        <User classid="UserCmp" name="Official:Inverter" defn="Official:Inverter" id="11" x="200" y="100" />
        <User classid="UserCmp" name="Official:Rectifier_AC" defn="Official:Rectifier_AC" id="12" x="100" y="200" />
        <User classid="UserCmp" name="Official:Inverter_AC" defn="Official:Inverter_AC" id="13" x="200" y="200" />
        <User classid="UserCmp" defn="master:tfault" id="14" x="300" y="300">
          <paramlist><param name="TF" value="0.3 [s]" /><param name="DF" value="0.05 [s]" /></paramlist>
        </User>
        <User classid="UserCmp" defn="master:pgb" id="15" x="400" y="300">
          <paramlist><param name="Name" value="Existing" /><param name="Group" value="Main" /><param name="Scale" value="1" /><param name="Units" value="state" /></paramlist>
        </User>
      </schematic>
    </Definition>
    <Definition classid="UserCmpDefn" name="Rectifier"><svg><port name="AC" /></svg><schematic /></Definition>
    <Definition classid="UserCmpDefn" name="Inverter"><svg><port name="AC" /></svg><schematic /></Definition>
    <Definition classid="UserCmpDefn" name="Rectifier_AC"><svg><port name="N" /></svg><schematic /></Definition>
    <Definition classid="UserCmpDefn" name="Inverter_AC"><svg><port name="N" /></svg><schematic /></Definition>
  </definitions>
  <hierarchy><call name="Official:Station"><call name="Official:Main" /></call></hierarchy>
</project>''',
        encoding="utf-8",
    )
    return path


def test_audit_requires_the_official_lcc_roles_and_fault_timer(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")

    report = audit_native_lcc_template(source)

    assert report.compatible is True
    assert report.pscad_version == "4.6.2"
    assert set(report.definitions) >= {"Main", "Station", "Rectifier", "Inverter"}
    assert report.fault_timer["definition"] == "master:tfault"


def test_native_audit_verifies_retained_master_references(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")
    master = tmp_path / "master.pslx"
    master.write_text(
        _master_fixture_xml().replace(
            "</pslx>",
            "<Definition name='tfault'><svg /></Definition>"
            "<Definition name='pgb'><svg /></Definition>"
            "</pslx>",
        ),
        encoding="utf-8",
    )
    assets = load_packaged_asset_set()
    assert assets.master_bindings is not None
    audited = audit_master_bindings(master, assets.master_bindings)

    report = audit_native_lcc_template(source, master_registry=audited)

    assert report.master_sha256 == audited.master_sha256
    assert report.master_binding_registry_sha256 == audited.registry.sha256
    assert {item["reference"] for item in report.master_references} == {
        "master:pgb",
        "master:tfault",
    }
    assert all(
        item["verification_state"] == "verified"
        for item in report.master_references
    )


def test_materialize_bundle_rewrites_identity_and_extracts_real_library(
    tmp_path: Path,
) -> None:
    source = _template(tmp_path / "official.pscx")
    project = tmp_path / "derived" / "LCC_CASE.pscx"
    library = tmp_path / "derived" / "cigre_lcc_v1.pslx"
    before = source.read_bytes()

    result = materialize_native_lcc_bundle(
        source,
        project,
        library,
        project_name="LCC_CASE",
        fault_time_s=0.8,
        fault_duration_s=0.1,
    )

    assert source.read_bytes() == before
    assert project.is_file() and library.is_file()
    assert result["source_sha256"] != result["project_sha256"]
    project_text = project.read_text(encoding="utf-8")
    library_text = library.read_text(encoding="utf-8")
    assert '<project name="LCC_CASE"' in project_text
    assert 'name="LCC Fault Active"' in project_text
    assert "cigre_lcc_v1:Rectifier" in project_text
    assert "LCC_CASE:Station" in project_text
    assert "LCC_CASE:Main" in project_text
    assert 'Target="Library"' in library_text
    assert 'name="Rectifier"' in library_text
    assert 'name="Inverter"' in library_text


def test_native_commutation_acceptance_is_fail_closed() -> None:
    samples = {
        "channels": [
            {
                "path": "Fault/LCC Fault Active",
                "units": "state",
                "domain": [0.0, 0.8, 0.9, 1.0],
                "values": [0.0, 1.0, 0.0, 0.0],
            },
            {
                "path": "Inverter/DC Current",
                "units": "pu",
                "domain": [0.0, 0.8, 0.9, 1.0],
                "values": [1.0, 1.2, 1.1, 1.0],
            },
            {
                "path": "Inverter/Gamma",
                "units": "deg",
                "domain": [0.0, 0.8, 0.9, 1.0],
                "values": [18.0, 5.0, 6.0, 18.0],
            },
        ]
    }

    result = evaluate_native_lcc_commutation(
        samples,
        fault_time_s=0.8,
        fault_duration_s=0.1,
        current_limit_pu=2.0,
    )

    assert result["verdict"] == "PASS"
    missing = evaluate_native_lcc_commutation(
        {"channels": []}, fault_time_s=0.8, fault_duration_s=0.1, current_limit_pu=2.0
    )
    assert missing["verdict"] == "INCOMPLETE_ANALYSIS"
    assert "fault_applied" in missing["missing_evidence"]


def test_materialize_rejects_existing_destination(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")
    project = tmp_path / "derived.pscx"
    library = tmp_path / "derived.pslx"
    project.write_text("external", encoding="ascii")

    with pytest.raises(BackendError) as raised:
        materialize_native_lcc_bundle(
            source,
            project,
            library,
            project_name="CASE",
            fault_time_s=0.8,
            fault_duration_s=0.1,
        )
    assert raised.value.code == "LCC_BUILD_CONFLICT"
    assert project.read_text(encoding="ascii") == "external"


def test_audit_rejects_a_symlinked_native_template(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")
    alias = tmp_path / "alias.pscx"
    try:
        alias.symlink_to(source)
    except OSError as error:
        pytest.skip(f"file symlinks unavailable: {error}")

    with pytest.raises(BackendError) as raised:
        audit_native_lcc_template(alias)

    assert raised.value.code == "LCC_TEMPLATE_INCOMPATIBLE"
