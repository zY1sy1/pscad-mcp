"""Real primary overcurrent must isolate the converter's grounded transformer."""

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.hvdc.builders.mmc.pwm_preparation import prepare_routed_pwm_case


def test_installed_pwm_has_measured_ac_overcurrent_isolation(tmp_path):
    source = Path("C:/Users/Public/Documents/PSCAD/4.6/Examples/ModelsInProgress")
    master = Path("C:/Program Files (x86)/PSCAD46/master.pslx")
    if not (source / "H_MMC_Mono_DC.pscx").is_file() or not master.is_file():
        pytest.skip("The immutable installed XML fixture is unavailable")
    prepared = prepare_routed_pwm_case(
        source / "H_MMC_Mono_DC.pscx", source / "intermediate.pslx", master,
        tmp_path / "prepared",
    )
    root = ET.parse(prepared["project"]).getroot()
    main = root.find("./definitions/Definition[@name='Main']/schematic")
    names = {
        p.get("value")
        for p in main.findall("./User[@defn='master:pgb']/paramlist/param[@name='Name']")
    }
    assert "MCP_AC_PROTECTION" in names
    assert "MCP_AC_PROTECTION_CURRENT" in names
    roles = {b["role"] for b in prepared["channels"]["diagnostic_channels"]}
    assert {"ac_protection_trip", "ac_protection_current"} <= roles
    controller = root.find("./definitions/Definition[@name='McpPwmCommands']")
    assert all(
        controller.find(f"./svg/port[@name='IAC_{station}']").get("dim") == "3"
        for station in ("T1", "T2")
    )
    code = controller.find("./script/segment[@name='Dsdyn']").text
    assert "$AC_CURRENT" in code and "$AC_TRIP" in code
    assert "$AC_OPEN = MAX(1.0 - $AC_CLOSE, $AC_TRIP)" in code
