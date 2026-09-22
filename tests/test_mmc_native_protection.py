from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.hvdc.builders.mmc.native_protection import PROTECTION_NAME, append_native_protection
from pscad_mcp.hvdc.builders.mmc.native_dq import DQ_NAME
from tests.test_mmc_native_dq import _run_native_equations


def _definition():
    root = ET.Element("project")
    ET.SubElement(root, "definitions")
    append_native_protection(root)
    return root.find(f"./definitions/Definition[@name='{PROTECTION_NAME}']")


def _healthy():
    return "\n".join(["SIG_PRECHARGE_READY = 1.0", "SIG_POWER_READY = 1.0",
        *(f"SIG_{s}_VDC = 640.0\nSIG_{s}_PLL_LOCKED = 1.0" for s in ("P", "V")),
        *(f"SIG_{s}_CABLE_VDC = 640.0\nSIG_{s}_CABLE_VPOS = 320.0\nSIG_{s}_CABLE_VNEG = -320.0" for s in ("P", "V")),
        *(f"SIG_{s}_{p}_{q}_VCAP = 320.0" for s in ("P", "V") for p in "ABC" for q in ("UPPER", "LOWER"))])


@pytest.mark.parametrize("field,bad,code", [
    ("P_A_UPPER_I", 2.4, 1), ("P_VDC", 710.0, 2),
    ("V_C_LOWER_VCAP", 353.0, 4), ("V_VDC", 570.0, 8),
    ("P_B_UPPER_VCAP", 287.0, 16), ("V_PLL_LOCKED", 0.0, 32),
    ("CHARGE_FAILED", 1.0, 128),
    ("P_CABLE_VPOS", 330.0, 256), ("V_CABLE_VDC", 570.0, 512),
])
def test_native_protection_latches_first_cause_after_the_fault_disappears(tmp_path, field, bad, code):
    restore = 320.0 if field.endswith(("VCAP", "VPOS")) else 640.0 if field.endswith("VDC") else 1.0 if field.endswith("LOCKED") else 0.0
    rows = _run_native_equations(tmp_path, PROTECTION_NAME, definition=_definition(), declarations="",
        initialize=_healthy(), loop=f"""SIG_{field} = {restore}
if (TIME >= 0.1 .and. TIME < 0.102) SIG_{field} = {bad}""",
        observations="if (sample == 3000 .or. sample == 5000) print *, SIG_TRIP, SIG_CODE, SIG_TRIP_TIME", steps=5000)
    assert len(rows) == 2
    for trip, reason, instant in rows:
        assert trip == 1 and reason == code
        assert instant == pytest.approx(0.1, abs=0.00005)


def test_brief_saturation_is_reset_but_continuous_saturation_trips(tmp_path):
    rows = _run_native_equations(tmp_path, PROTECTION_NAME, definition=_definition(), declarations="",
        initialize=_healthy(), loop="""SIG_P_LIMIT_ACTIVE = 0.0
if (TIME >= 0.05 .and. TIME < 0.055) SIG_P_LIMIT_ACTIVE = 1.0
if (TIME >= 0.08 .and. TIME < 0.09) SIG_P_LIMIT_ACTIVE = 1.0
if (TIME >= 0.12) SIG_P_LIMIT_ACTIVE = 1.0""",
        observations="if (sample == 2000 .or. sample == 3000) print *, SIG_TRIP, SIG_CODE, SIG_TRIP_TIME", steps=3000)
    assert rows[0] == [0.0, 0.0, -1.0]
    assert rows[1][:2] == [1.0, 64.0]
    assert rows[1][2] == pytest.approx(0.12 + 1 / 60, abs=0.00005)


def test_trip_blocks_dq_valves_and_clears_remaining_power_sequence(tmp_path):
    rows = _run_native_equations(tmp_path, DQ_NAME, declarations="",
        initialize="""SIG_PROTECTION_TRIP = 1.0
SIG_PLL_LOCKED = 1.0
SIG_STARTUP_READY = 1.0
SIG_POWER_READY = 1.0
SIG_VDC_MEAS = 640.0""",
        loop="", observations="print *, SIG_BLOCK, SIG_SEQUENCE, SIG_P_REFERENCE, SIG_Q_REFERENCE, SIG_ID_REFERENCE, SIG_IQ_REFERENCE", steps=1)
    assert rows == [[1.0, 5.0, 0.0, 0.0, 0.0, 0.0]]
