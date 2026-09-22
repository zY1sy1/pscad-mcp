import math
import os
import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.hvdc.builders.mmc.native_dq import PLL_NAME, DQ_NAME, append_native_pll_and_dq


def _run_native_equations(tmp_path, definition_name, *, declarations, initialize, loop, observations, steps, definition=None):
    compiler = Path("C:/Program Files (x86)/GFortran/4.6/bin/gfortran.exe")
    if not compiler.is_file():
        pytest.skip("Native Fortran compiler is unavailable")
    if definition is None:
        root = ET.Element("project")
        ET.SubElement(root, "definitions")
        append_native_pll_and_dq(root)
        definition = root.find(f"./definitions/Definition[@name='{definition_name}']")
    segment = definition.find("./script/segment[@name='Dsdyn']")
    if segment is None:
        segment = definition.find("./script/segment[@name='Fortran']")
    script = segment.text
    parameters = {p.get("name"): p.findtext("value") for p in definition.findall("./form/category/parameter")}
    ports = [p.get("name") for p in definition.findall("./svg/port")]
    locals_ = re.findall(r"#LOCAL (REAL|INTEGER) (\w+)", script)
    storage_match = re.search(r"#STORAGE REAL:(\d+)", script)
    storage = int(storage_match.group(1)) if storage_match else 1
    body = re.sub(r"^#.*$", "", script, flags=re.MULTILINE)
    body = re.sub(r"\$(\w+)", lambda m: ("PAR_" if m[1] in parameters else "SIG_") + m[1], body)
    variable_declarations = "\n".join(
        [*(f"real(8) :: PAR_{p}" for p in parameters), *(f"real(8) :: SIG_{p}" for p in ports),
         *(f"{'real(8)' if kind == 'REAL' else 'integer'} :: {name}" for kind, name in locals_)]
    )
    values = "\n".join([*(f"PAR_{p} = {value}" for p, value in parameters.items()), *(f"SIG_{p} = 0.0" for p in ports)])
    source = tmp_path / "equations.f90"
    executable = tmp_path / "equations.exe"
    source.write_text(f"""program equations
implicit none
{variable_declarations}
real(8) :: STORF({storage}), TIME, DELT
integer :: NSTORF, sample
logical :: TIMEZERO
{declarations}
{values}
STORF = 0.0
DELT = 0.00005
{initialize}
do sample = 1, {steps}
 TIME = sample * DELT
 TIMEZERO = sample == 1
 NSTORF = 1
 {loop}
 {body}
 {observations}
enddo
end program
""", encoding="ascii")
    environment = {**os.environ, "PATH": str(compiler.parent) + os.pathsep + os.environ.get("PATH", "")}
    environment.pop("GCC_EXEC_PREFIX", None)
    environment.pop("LIBRARY_PATH", None)
    with subprocess.Popen([str(compiler), "-ffree-form", "-ffree-line-length-none", "-fdefault-real-8", "-fdefault-double-8",
                           str(source), "-o", str(executable)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment) as compile_process:
        output, errors = compile_process.communicate(timeout=30)
    assert compile_process.returncode == 0, output + errors
    with subprocess.Popen([str(executable)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment) as process:
        output, errors = process.communicate(timeout=30)
    assert process.returncode == 0, errors
    return [[float(x.replace("D", "E")) for x in line.split()] for line in output.splitlines()]


def test_native_pll_tracks_frequency_and_phase_changes_and_reports_voltage_loss(tmp_path):
    rows = _run_native_equations(tmp_path, PLL_NAME, declarations="real(8) :: grid_angle, magnitude_input", initialize="",
        loop="""grid_angle = 6.283185307179586 * (60.0 * TIME + MAX(0.0, TIME - 0.2))
if (TIME >= 0.5) grid_angle = grid_angle + 0.2
if (TIME >= 1.05) grid_angle = grid_angle + 1.0
magnitude_input = 280.0
if (TIME >= 0.7 .and. TIME < 0.75) magnitude_input = 0.0
SIG_VA = magnitude_input * SIN(grid_angle)
SIG_VB = magnitude_input * SIN(grid_angle - 2.09439510239320)
SIG_VC = magnitude_input * SIN(grid_angle + 2.09439510239320)
""", observations="""if (sample == 9000 .or. sample == 10001 .or. sample == 13000 .or. sample == 14500 .or. sample == 19000 .or. sample == 21250) print *, TIME, SIG_FREQUENCY, SIG_ERROR, SIG_LOCKED, SIG_INTEGRATOR, SIG_LIMITED
""", steps=23000)
    assert len(rows) == 6
    for index in (0, 2, 4):
        _, frequency, error, locked, integrator, limited = rows[index]
        assert frequency == pytest.approx(61.0, abs=0.03)
        assert abs(error) < 0.005
        assert locked == 1.0 and limited == 0.0
        assert integrator == pytest.approx(2 * math.pi, abs=0.2)
    assert rows[1][3] == 1.0  # a brief phase step does not chatter the deblock signal
    assert rows[3][3] == 0.0  # loss of voltage clears lock immediately
    assert rows[5][3] == 0.0 and rows[5][5] == 1.0  # sustained desynchronization is rejected


def test_native_dq_tracks_both_power_directions_through_an_inductive_plant(tmp_path):
    arms = "\n".join(f"SIG_{p}_{q}_VCAP = 320.0\nSIG_{p}_{q}_I = -SIG_P_MEAS / (3.0 * 640.0) {'-' if q == 'UPPER' else '+'} 0.5 * SIG_I{p}"
                     for p in "ABC" for q in ("UPPER", "LOWER"))
    rows = _run_native_equations(tmp_path, DQ_NAME,
        declarations="real(8) :: plant_d, plant_q, angle_input, ac_a, ac_b, dp, dq_step",
        initialize="""plant_d = 0.0
plant_q = 0.0
PAR_P_Order_MW = 300.0
PAR_Reversal_Duration_s = 0.5
SIG_START_TIME = 0.1
SIG_POWER_START = 0.1
SIG_PLL_LOCKED = 1.0
SIG_VDC_MEAS = 640.0
""", loop="""angle_input = 6.283185307179586 * 60.0 * TIME
SIG_PLL_ANGLE = angle_input
SIG_STARTUP_READY = 0.0
if (TIME >= 0.1) SIG_STARTUP_READY = 1.0
SIG_POWER_READY = SIG_STARTUP_READY
SIG_VA = 256.0 * SIN(angle_input)
SIG_VB = 256.0 * SIN(angle_input - 2.09439510239320)
SIG_VC = 256.0 * SIN(angle_input + 2.09439510239320)
ac_a = plant_d * SIN(angle_input) + plant_q * COS(angle_input)
ac_b = -plant_d * COS(angle_input) + plant_q * SIN(angle_input)
SIG_IA = ac_a
SIG_IB = -0.5 * ac_a + 0.866025403784439 * ac_b
SIG_IC = -0.5 * ac_a - 0.866025403784439 * ac_b
SIG_P_MEAS = 1.5 * 256.0 * plant_d
SIG_Q_MEAS = -1.5 * 256.0 * plant_q + 1.5 * PAR_Transformer_Leakage_ohm * (plant_d**2 + plant_q**2)
""" + arms, observations="""if (SIG_BLOCK < 0.5) then
 dp = (256.0 - SIG_VD_REFERENCE - 0.075 * plant_d + 6.283185307179586 * 60.0 * 0.025 * plant_q) / 0.025
 dq_step = (-SIG_VQ_REFERENCE - 0.075 * plant_q - 6.283185307179586 * 60.0 * 0.025 * plant_d) / 0.025
 plant_d = plant_d + DELT * dp
 plant_q = plant_q + DELT * dq_step
endif
if (sample == 18000 .or. sample == 39000) print *, SIG_P_MEAS, SIG_P_REFERENCE, SIG_Q_MEAS, SIG_ID_MEASURED - SIG_ID_REFERENCE, SIG_IQ_MEASURED - SIG_IQ_REFERENCE, SIG_LIMIT_ACTIVE
""", steps=40000)
    assert len(rows) == 2
    for row, expected in zip(rows, (300.0, -300.0)):
        active, reference, reactive, d_error, q_error, limited = row
        assert reference == expected
        assert active == pytest.approx(expected, abs=0.5)
        assert abs(reactive) < 0.5
        assert abs(d_error) < 0.002 and abs(q_error) < 0.002
        assert limited == 0.0


def test_native_outer_integrator_does_not_wind_up_against_unreachable_arm_voltages(tmp_path):
    arms = "\n".join(f"SIG_{p}_{q}_VCAP = 1.0" for p in "ABC" for q in ("UPPER", "LOWER"))
    rows = _run_native_equations(tmp_path, DQ_NAME, declarations="real(8) :: phase_input",
        initialize="""PAR_Control_Mode = 1.0
SIG_STARTUP_READY = 1.0
SIG_START_TIME = 0.0
SIG_PLL_LOCKED = 1.0
SIG_VDC_MEAS = 400.0
""" + arms, loop="""phase_input = 6.283185307179586 * 60.0 * TIME
SIG_PLL_ANGLE = phase_input
SIG_VA = 256.0 * SIN(phase_input)
SIG_VB = 256.0 * SIN(phase_input - 2.09439510239320)
SIG_VC = 256.0 * SIN(phase_input + 2.09439510239320)
""", observations="if (sample == 10000) print *, SIG_VDC_INTEGRATOR, SIG_LIMIT_ACTIVE", steps=10000)
    assert rows[0][1] == 1.0
    assert abs(rows[0][0]) < 0.1


def test_native_charge_power_accounts_for_capacitor_energy_and_waits_for_power_readiness(tmp_path):
    capacitor_fields = "\n".join(f"SIG_{p}_{q}_VCAP = 250.0" for p in "ABC" for q in ("UPPER", "LOWER"))
    rows = _run_native_equations(tmp_path, DQ_NAME, declarations="real(8) :: accumulated_charge",
        initialize="""PAR_C_eq_F = 0.0001041666666666667
SIG_START_TIME = 0.1
SIG_PLL_LOCKED = 1.0
SIG_VDC_MEAS = 500.0
accumulated_charge = 0.0
""" + capacitor_fields, loop="""SIG_STARTUP_READY = 0.0
if (TIME >= 0.1) SIG_STARTUP_READY = 1.0
SIG_POWER_READY = 0.0
""", observations="""accumulated_charge = accumulated_charge + SIG_CHARGE_POWER_REFERENCE * DELT
if (sample == 16000) print *, accumulated_charge, SIG_P_REFERENCE, SIG_SEQUENCE
""", steps=16000)
    expected_energy = 3 * 0.0001041666666666667 * (320.0**2 - 250.0**2)
    assert rows[0][0] == pytest.approx(expected_energy, rel=2e-4)
    assert rows[0][1] == 0.0 and rows[0][2] == 4.0


def test_recovery_keeps_reverse_power_without_replaying_the_initial_reversal(tmp_path):
    arms = "\n".join(f"SIG_{p}_{q}_VCAP = 320.0" for p in "ABC" for q in ("UPPER", "LOWER"))
    rows = _run_native_equations(tmp_path, DQ_NAME, declarations="",
        initialize="""SIG_RECOVERY_MODE = 1.0
SIG_START_TIME = 0.8
SIG_POWER_START = 1.0
SIG_VDC_MEAS = 640.0
SIG_PLL_LOCKED = 1.0""" + "\n" + arms,
        loop="""SIG_STARTUP_READY = 0.0
SIG_POWER_READY = 0.0
if (TIME >= 0.8) SIG_STARTUP_READY = 1.0
if (TIME >= 1.0) SIG_POWER_READY = 1.0""",
        observations="if (sample == 26000 .or. sample == 40000) print *, SIG_P_REFERENCE, SIG_SEQUENCE, SIG_BLOCK", steps=40000)
    assert rows == [[-1000.0, 3.0, 0.0], [-1000.0, 3.0, 0.0]]


def test_dc_charge_feedforward_accounts_for_the_actual_cable_energy_increment(tmp_path):
    arms = "\n".join(f"SIG_{p}_{q}_VCAP = 320.0" for p in "ABC" for q in ("UPPER", "LOWER"))
    rows = _run_native_equations(tmp_path, DQ_NAME, declarations="real(8) :: dc_energy",
        initialize="""PAR_Control_Mode = 1.0
PAR_DC_Link_Capacitance_F = 0.00002647426962004457
SIG_START_TIME = 0.1
SIG_VDC_MEAS = 500.0
SIG_PLL_LOCKED = 1.0
dc_energy = 0.0""" + "\n" + arms,
        loop="SIG_STARTUP_READY = 0.0\nif (TIME >= 0.1) SIG_STARTUP_READY = 1.0",
        observations="""dc_energy = dc_energy + DELT * SIG_DC_CHARGE_POWER_REFERENCE
if (sample == 16000) print *, dc_energy, SIG_DC_CHARGE_POWER_REFERENCE""", steps=16000)
    assert rows[0][0] == pytest.approx(0.5 * 26.47426962004457e-6 * (640.0**2 - 500.0**2), rel=2e-4)
    assert rows[0][1] == 0.0


def test_restart_does_not_invent_a_capacitor_energy_deficit(tmp_path):
    arms = "\n".join(f"SIG_{p}_{q}_VCAP = 320.0" for p in "ABC" for q in ("UPPER", "LOWER"))
    rows = _run_native_equations(tmp_path, DQ_NAME, declarations="",
        initialize="SIG_VDC_MEAS = 640.0\nSIG_PLL_LOCKED = 1.0\nSIG_START_TIME = 0.334\nSIG_RECOVERY_MODE = 1.0\n" + arms,
        loop="""SIG_RESTART = 0.0
if (TIME >= 0.3 .and. TIME < 0.301) SIG_RESTART = 1.0
SIG_STARTUP_READY = 0.0
if (TIME >= 0.334) SIG_STARTUP_READY = 1.0""",
        observations="if (sample == 6700) print *, SIG_CIRC_REFERENCE_A, SIG_CHARGE_POWER_REFERENCE", steps=6700)
    assert rows[0] == pytest.approx([2 * 1.1 / 640.0, 0.0], abs=1e-8)


def test_diagnostic_angle_is_wrapped_without_clipping_its_direction(tmp_path):
    rows = _run_native_equations(tmp_path, DQ_NAME, declarations="",
        initialize="SIG_PLL_ANGLE = 1.571\nSIG_VA = -1.0\nSIG_VB = 0.5\nSIG_VC = 0.5",
        loop="", observations="print *, SIG_ANGLE_COMMAND, SIG_VD_REFERENCE, SIG_VQ_REFERENCE", steps=1)
    angle, d, q = rows[0]
    assert -180 <= angle < 180
    expected = math.atan2(q, d) + 2 * 2 * math.pi * 60 * 0.00005
    assert math.sin(math.radians(angle)) == pytest.approx(math.sin(expected), abs=1e-12)
    assert math.cos(math.radians(angle)) == pytest.approx(math.cos(expected), abs=1e-12)
