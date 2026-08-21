from pathlib import Path
from textwrap import dedent

from pscad_mcp.hvdc.builders.lcc.template_audit import audit_lcc_template


def test_audit_reports_exact_roles_without_mutation(tmp_path):
    source = tmp_path / "template.pscx"
    original = '<project><component definition="cigre_lcc_v1:LCC12PulseBridge"/><component definition="master:ground"/></project>'
    source.write_text(original, encoding="utf-8")
    report = audit_lcc_template(source)
    assert report.compatible is True
    assert report.roles["rectifier_valve_group"]["definition"] == "cigre_lcc_v1:LCC12PulseBridge"
    assert source.read_text(encoding="utf-8") == original


def test_audit_accepts_real_template_roles_and_electrode_evidence(tmp_path):
    source = tmp_path / "real_template.pscx"
    source.write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="utf-8"?>
            <pscx>
              <Definition name="Main">
                <Canvas name="Main">
                  <User classid="UserCmp" defn="HVDC_Bipolar_1000MW_500kV:RectPole" x="612" y="594" />
                  <User classid="UserCmp" defn="HVDC_Bipolar_1000MW_500kV:InverterPole" x="1152" y="594" />
                  <User classid="UserCmp" defn="master:ground" x="738" y="432" />
                  <User classid="UserCmp" defn="master:ground" x="1026" y="432" />
                  <User classid="UserCmp" defn="master:ammeter" x="666" y="432">
                    <paramlist>
                      <param name="Name" value="Ielectrode" />
                    </paramlist>
                  </User>
                </Canvas>
              </Definition>
            </pscx>
            """
        ),
        encoding="utf-8",
    )

    report = audit_lcc_template(source)

    assert report.compatible is True
    assert report.roles["rectifier_valve_group"]["definition"] == "HVDC_Bipolar_1000MW_500kV:RectPole"
    assert report.roles["inverter_valve_group"]["definition"] == "HVDC_Bipolar_1000MW_500kV:InverterPole"
    assert report.roles["earth_electrode"]["definition"] == "master:ground"
    assert report.roles["earth_electrode"]["evidence"]["anchor"]["parameters"]["Name"] == "Ielectrode"
    assert report.roles["earth_electrode"]["evidence"]["selected"]["location"] == [738, 432]
