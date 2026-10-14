"""Instance parameters, cell capacitance and real carrier determine PWM sizing."""

from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.hvdc.builders.mmc.pwm_reference import audit_pwm_physical_reference


def test_instantiated_dimension_overrides_the_form_default():
    root = ET.fromstring(
        '<project name="fixture"><paramlist><param name="time_step" value="50"/><param name="sample_step" value="250"/></paramlist><definitions><Definition name="Main"><form><category><parameter name="NoCells1"><value>38</value></parameter></category></form><schematic/></Definition><Definition name="Station"><schematic><Wire><User defn="fixture:Main" id="entry"><paramlist><param name="NoCells1" value="76"/><param name="Freq" value="60"/></paramlist></User></Wire></schematic></Definition></definitions></project>'
    )
    main = root.find("./definitions/Definition[@name='Main']/schematic")
    for index, carrier in enumerate(("23", "3")):
        component = ET.SubElement(
            main, "User", defn="fixture:MMC_Hb_PWM", id=str(index)
        )
        group = ET.SubElement(component, "paramlist")
        for key, value in {
            "Cdc": "2800 [uF]",
            "Lsmth": "50 [mH]",
            "RSOn": "0.005 [ohm]",
            "VdcBase": "640 [kV]",
            "Cfreq": carrier,
        }.items():
            ET.SubElement(group, "param", name=key, value=value)
    reference = audit_pwm_physical_reference(root)
    assert reference["reference_cells_per_arm"] == 76
    assert reference["form_default_used"] is False
    assert reference["switching_frequency_hz"] == 1380
    assert reference["stored_energy_mj"] == pytest.approx(90.5431578947)
    assert reference["equivalent_arm_capacitance_f"] == pytest.approx(0.0028 / 76)
    assert reference["equivalent_capacitor_voltage_target_kv"] == 640


def test_reference_without_a_runtime_dimension_stays_unavailable():
    assert (
        audit_pwm_physical_reference(
            ET.fromstring("<project><definitions/></project>")
        )["available"]
        is False
    )
