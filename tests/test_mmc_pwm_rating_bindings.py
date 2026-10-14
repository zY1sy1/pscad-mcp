"""Independent fixtures for the control and arm parameter chains of PWM cases."""

from pathlib import Path

from pscad_mcp.hvdc.builders.mmc.template_audit import audit_mmc_template
from tests.mmc_parametric_fakes import make_synthetic_official_shape


def test_hierarchical_pwm_audit_includes_reachable_arm_ratings(tmp_path: Path):
    project, library = make_synthetic_official_shape(tmp_path / "sources")
    project.write_text(
        '<project name="rating_fixture" version="4.6.2">'
        '<definitions><Definition name="Main"><schematic>'
        '<User classid="UserCmp" id="21" defn="rating_fixture:VSCConverter"><paramlist>'
        '<param name="dmode" value="1"/><param name="Sbase" value="1000 [MVA]"/>'
        "</paramlist></User>"
        '<User classid="UserCmp" id="22" defn="rating_fixture:VSCConverter"><paramlist>'
        '<param name="dmode" value="0"/><param name="Sbase" value="1000 [MVA]"/>'
        "</paramlist></User>"
        '<User classid="UserCmp" id="31" defn="rating_fixture:MMC_Hb_PWM"><paramlist>'
        '<param name="VdcBase" value="640 [kV]"/>'
        '<param name="fref" value="60 [Hz]"/>'
        "</paramlist></User>"
        '<User classid="UserCmp" id="32" defn="rating_fixture:MMC_Hb_PWM"><paramlist>'
        '<param name="VdcBase" value="640 [kV]"/>'
        '<param name="fref" value="60 [Hz]"/>'
        "</paramlist></User></schematic></Definition>"
        '<Definition name="VSCConverter"><schematic/></Definition>'
        '<Definition name="MMC_Hb_PWM"><schematic>'
        '<User classid="UserCmp" id="41" defn="intermediate:Cell"><paramlist/></User>'
        "</schematic></Definition></definitions>"
        '<hierarchy><call link="10" name="rating_fixture:Station">'
        '<call link="11" name="rating_fixture:Main">'
        '<call link="21" name="rating_fixture:VSCConverter"/>'
        '<call link="22" name="rating_fixture:VSCConverter"/>'
        '<call link="31" name="rating_fixture:MMC_Hb_PWM"/>'
        '<call link="32" name="rating_fixture:MMC_Hb_PWM"/>'
        "</call></call></hierarchy></project>",
        encoding="utf-8",
    )
    before = project.read_bytes()
    audit = audit_mmc_template(project, library)
    assert audit["compatible"] is True
    bindings = {
        (item["owner"], item["parameter"])
        for item in audit["writable_parameter_bindings"]
    }
    assert {
        ("31", "VdcBase"),
        ("32", "VdcBase"),
        ("31", "fref"),
        ("32", "fref"),
    } <= bindings
    assert project.read_bytes() == before
