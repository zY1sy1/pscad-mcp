from pathlib import Path
from textwrap import dedent

import pytest

from pscad_mcp.core.backend.base import BackendError
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


@pytest.mark.parametrize(
    "ambiguous_components, expected_role",
    [
        (
            '<component definition="model:RectPole"/><component definition="model:RectPole"/>',
            "rectifier_valve_group",
        ),
        (
            '<component definition="model:InverterPole"/><component definition="model:InverterPole"/>',
            "inverter_valve_group",
        ),
        (
            '<component definition="model:LCC12PulseBridge"/><component definition="model:LCC12PulseBridge"/>',
            "rectifier_valve_group",
        ),
    ],
)
def test_audit_rejects_duplicate_exact_role_instances(tmp_path, ambiguous_components, expected_role):
    source = tmp_path / "ambiguous_role.pscx"
    source.write_text(
        (
            "<project>"
            f"{ambiguous_components}"
            '<component definition="model:RectPole"/>'
            '<component definition="model:InverterPole"/>'
            '<component definition="master:ground"/>'
            "</project>"
        ),
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_AMBIGUOUS"
    assert raised.value.details["compatible"] is False
    assert expected_role in raised.value.details["conflicts"]


def test_audit_rejects_non_master_ammeter_as_electrode_anchor(tmp_path):
    source = tmp_path / "wrong_anchor.pscx"
    source.write_text(
        dedent(
            """\
            <project>
              <component definition="model:LCC12PulseBridge" />
              <component definition="master:ground" x="0" y="0" />
              <component definition="master:ground" x="100" y="0" />
              <component definition="custom:ammeter" x="0" y="0">
                <param name="Name" value="Ielectrode" />
              </component>
            </project>
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_AMBIGUOUS"
    assert "earth_electrode" in raised.value.details["conflicts"]


@pytest.mark.parametrize(
    "grounds, anchors",
    [
        (
            '<component definition="master:ground" x="0" y="0"/>'
            '<component definition="master:ground" x="100" y="0"/>',
            '<component definition="master:ammeter" x="0" y="0"><param name="Name" value="Ielectrode"/></component>'
            '<component definition="master:ammeter" x="100" y="0"><param name="Name" value="Ielectrode"/></component>',
        ),
        (
            '<component definition="master:ground" x="0" y="0"/>'
            '<component definition="master:ground" x="100" y="0"/>',
            "",
        ),
        (
            '<component definition="master:ground" x="0" y="0"/>'
            '<component definition="master:ground" x="100" y="0"/>',
            '<component definition="master:ammeter" x="50" y="0"><param name="Name" value="Ielectrode"/></component>',
        ),
    ],
)
def test_audit_rejects_ambiguous_electrode_evidence(tmp_path, grounds, anchors):
    source = tmp_path / "ambiguous_electrode.pscx"
    source.write_text(
        "<project>"
        '<component definition="model:LCC12PulseBridge"/>'
        f"{grounds}{anchors}"
        "</project>",
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_AMBIGUOUS"
    assert raised.value.details["compatible"] is False
    assert "earth_electrode" in raised.value.details["conflicts"]


def test_audit_accepts_single_ground_without_anchor_with_explicit_evidence(tmp_path):
    source = tmp_path / "single_ground.pscx"
    source.write_text(
        '<project><component definition="model:LCC12PulseBridge"/>'
        '<component definition="master:ground" x="10" y="20"/></project>',
        encoding="utf-8",
    )

    report = audit_lcc_template(source)

    assert report.compatible is True
    evidence = report.roles["earth_electrode"]["evidence"]
    assert evidence["selection_reason"] == "single_exact_ground_without_anchor"
    assert evidence["selected"]["location"] == [10, 20]
