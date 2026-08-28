from pathlib import Path

import pytest

from pscad_mcp.hvdc.builders.mmc.line_constants import (
    LineConstantsArtifact,
    extract_tline_segments,
    rebind_template_line_constants,
    render_tli,
)
from pscad_mcp.hvdc.builders.mmc.catalog import parse_catalog


def test_extract_and_render_public_tline_input(tmp_path: Path) -> None:
    project = tmp_path / "official.pscx"
    project.write_text(
        """<project version=\"4.6.2\"><Definition name=\"DCTL\">\n"
        "<schematic><User defn=\"master:Line_FrePhase_Options\"><paramlist>\n"
        "<param name=\"Interp1\" value=\"1\"/><param name=\"FS\" value=\"0.5\"/>\n"
        "<param name=\"FE\" value=\"1.0E6\"/><param name=\"Numf\" value=\"100\"/>\n"
        "<param name=\"YMaxP\" value=\"20\"/><param name=\"YMaxE\" value=\"0.2\"/>\n"
        "<param name=\"AMaxP\" value=\"20\"/><param name=\"AMaxE\" value=\"0.2\"/>\n"
        "<param name=\"W1\" value=\"1.0\"/><param name=\"W2\" value=\"1000.0\"/>\n"
        "<param name=\"W3\" value=\"1.0\"/></paramlist></User>\n"
        "<User defn=\"master:Line_Ground\"><paramlist>\n"
        "<param name=\"GRRES\" value=\"100.0\"/><param name=\"GPERM\" value=\"1.0\"/>\n"
        "<param name=\"EarthForm\" value=\"0\"/><param name=\"EarthForm3\" value=\"2\"/>\n"
        "</paramlist></User><User defn=\"master:Line_Tower_2_Flat\"><paramlist>\n"
        "<param name=\"TName\" value=\"DC12\"/><param name=\"Y\" value=\"33.2 [m]\"/>\n"
        "<param name=\"XC\" value=\"15.8 [m]\"/><param name=\"ShuntG\" value=\"1e-11 [mho/m]\"/>\n"
        "<param name=\"Transp\" value=\"1\"/><param name=\"ElimGW\" value=\"1\"/>\n"
        "<param name=\"RadiusC\" value=\"0.03801 [m]\"/><param name=\"DCResC\" value=\"0.03182 [ohm/km]\"/>\n"
        "<param name=\"SAGC\" value=\"19.1 [m]\"/><param name=\"NCondB\" value=\"3\"/>\n"
        "<param name=\"BSP\" value=\".4572 [m]\"/><param name=\"RadiusG\" value=\"0.0082 [m]\"/>\n"
        "<param name=\"DCResG\" value=\"0.2943 [ohm/km]\"/><param name=\"SAGG\" value=\"17.8 [m]\"/>\n"
        "<param name=\"YG\" value=\"11.9 [m]\"/><param name=\"XG\" value=\"10 [m]\"/>\n"
        "</paramlist></User><Wire classid=\"TLine\"><User><paramlist>\n"
        "<param name=\"Name\" value=\"TL12a\"/><param name=\"Length\" value=\"200.0 [km]\"/>\n"
        "<param name=\"Freq\" value=\"0.0 [Hz]\"/><param name=\"Dim\" value=\"2\"/>\n"
        "</paramlist></User></Wire></schematic></Definition></project>""",
        encoding="utf-8",
    )

    segments = extract_tline_segments(project)
    assert len(segments) == 1
    assert segments[0].name == "TL12a"
    rendered = render_tli(segments[0])
    assert "Line Name = TL12a" in rendered
    assert "Line Length = 200" in rendered
    assert "Number of Conductors = 2" in rendered
    assert "Line Constants Tower:" in rendered


def test_extract_rejects_missing_dctl_parameters(tmp_path: Path) -> None:
    project = tmp_path / "bad.pscx"
    project.write_text("<project><Wire classid=\"TLine\"><User /></Wire></project>", encoding="utf-8")
    with pytest.raises(ValueError, match="DCTL definition"):
        extract_tline_segments(project)


def test_rebind_template_writes_only_line_constant_paths(tmp_path: Path) -> None:
    source = tmp_path / "source.pscx"
    source.write_text(
        '<project><Wire classid="TLine"><User><paramlist>'
        '<param name="Name" value="TL12a"/>'
        '<param name="const_path" value="C:\\Temp\\my_constants_file.tlo"/>'
        '</paramlist></User></Wire></project>',
        encoding="utf-8",
    )
    artifact = LineConstantsArtifact(
        segment="TL12a",
        input_path="in.tli",
        constants_path=str(tmp_path / "TL12a.tlo"),
        log_path="out.log",
        output_path="out.out",
        input_sha256="i",
        constants_sha256="c",
        log_sha256="l",
        output_sha256="o",
        command=("tline.exe", "TL12a.tli"),
        returncode=0,
    )
    target = tmp_path / "rebound.pscx"
    rebind_template_line_constants(source, (artifact,), target)
    rendered = target.read_text(encoding="utf-8")
    assert artifact.constants_path in rendered
    assert "classid=\"TLine\"" in rendered


def test_packaged_catalog_accepts_pscad_text_dimensions() -> None:
    catalog = parse_catalog(
        {
            "schema_version": 1,
            "pscad_version": "4.6.2",
            "scope": "test",
            "definitions": {
                "test:Arm": {
                    "ports": [{"name": "AC", "kind": "electrical", "dimension": "1"}]
                }
            },
        }
    )
    assert catalog.definitions["test:Arm"].ports[0].dimension == 1
