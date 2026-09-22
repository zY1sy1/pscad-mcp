"""Native PSCAD library and two-station AVM integration fixture."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree as ET

from ....core.definition_metadata import read_definition_metadata_document
from .avm_companion import (
    AverageArmParameters,
    _audit_master,
    _definition,
    _make_library,
    _project,
    _script,
    _sha,
    _write_new,
    _Writer,
)
from .cable_companion import (
    DEFAULT_DONOR,
    DEFAULT_MASTER,
    append_native_cable_link,
)

NATIVE_SCOPE = "cigre_mmc_avm_v1"
CONTROL_NAME = "MMCStationModulator"
CLOSED_LOOP_CONTROL_NAME = "MMCStationController"
MEASUREMENT_NAME = "MMCStationMeasurements"
SAMPLE_NAME = "MMCPreviousSolutionSample"
CONTROL_OUTPUTS = (
    "M_A_UPPER",
    "M_A_LOWER",
    "M_B_UPPER",
    "M_B_LOWER",
    "M_C_UPPER",
    "M_C_LOWER",
    "BLOCK",
    "SEQUENCE",
    "ANGLE_COMMAND",
    "MODULATION_COMMAND",
    "POWER_CORRECTION",
    "P_REFERENCE",
    "Q_REFERENCE",
    "VDC_REFERENCE",
)
INSERTION_OUTPUTS = CONTROL_OUTPUTS[:6]
RAW_INSERTION_OUTPUTS = tuple(name + "_RAW" for name in INSERTION_OUTPUTS)
CONTROL_OUTPUTS += RAW_INSERTION_OUTPUTS
MODULATION_OUTPUTS = INSERTION_OUTPUTS + RAW_INSERTION_OUTPUTS
KCL_MEASUREMENTS = {"IDC": "kA", "IDC_NEG": "kA", "VDC_POS": "kV", "VDC_NEG": "kV",
                    **{f"VALVE_{q}_{p}": unit for p in "ABC" for q, unit in (("I", "kA"), ("V", "kV"))}}
CONTROL_DEFAULTS = {
    "Frequency_Hz": 60.0,
    "Modulation_Index": 0.82,
    "Phase_Offset_Deg": 0.0,
    "Deblock_Time_s": 0.10,
    "Reversal_Time_s": 0.30,
    "P_Order_MW": 1000.0,
    "Q_Order_MVAr": 0.0,
    "Vdc_Order_kV": 640.0,
    "Ramp_Time_s": 0.20,
    "Reversal_Duration_s": 0.50,
}
CLOSED_LOOP_DEFAULTS = {
    **CONTROL_DEFAULTS,
    "Ramp_Time_s": 0.20,
    "Reversal_Duration_s": 0.50,
    "P_Order_MW": 1000.0,
    "Q_Order_MVAr": 0.0,
    "Vdc_Order_kV": 640.0,
    "Control_Mode": 0.0,
    "Kp_Active": 0.01,
    "Ti_Active_s": 0.10,
    "Kp_Reactive": 0.00005,
    "Ti_Reactive_s": 0.05,
    "Base_Modulation": 0.90,
    "C_eq_F": 6.510416666666667e-5,
    "Circulating_Gain_ohm": 18.84955592153876,
    "Energy_Gain_per_s": 10.0,
    "R_arm_ohm": 0.15,
    "P_nonohmic_MW": 0.0,
    "Kp_Vdc_MW_per_kV": 3.0,
    "Ti_Vdc_s": 0.30,
    "Feedback_Filter_s": 0.02,
    "Energy_Difference_Filter_s": 0.05,
    "Power_Correction_Limit_MW": 1500.0,
    "Cable_Loss_MW": 0.0,
    "Converter_Loss_MW": 0.0,
}
ARM_FEEDBACK_INPUTS = tuple(
    f"{phase}_{position}_{quantity}"
    for phase in "ABC"
    for position in ("UPPER", "LOWER")
    for quantity in ("VCAP", "I")
) + tuple(f"{phase}_UPPER_VT" for phase in "ABC")


def _feedback_ports(names: tuple[str, ...]) -> dict:
    return {
        name: (-90 - (index // 8) * 108, -180 + (index % 8) * 36, "Transfer", "Input")
        for index, name in enumerate(names)
    }
FIXTURE_CHANNELS = {
    "P_VDC": "kV",
    "V_VDC": "kV",
    "P_A_UPPER_I": "kA",
    "P_A_UPPER_W": "MJ",
    "V_A_UPPER_I": "kA",
    "V_A_UPPER_W": "MJ",
    "P_SEQUENCE": "1",
    "V_SEQUENCE": "1",
    "P_P": "MW",
    "P_Q": "MVAr",
    "P_IDC": "kA",
    "V_P": "MW",
    "V_Q": "MVAr",
    "V_IDC": "kA",
    "P_ANGLE_COMMAND": "deg",
    "P_MODULATION_COMMAND": "1",
    "V_ANGLE_COMMAND": "deg",
    "V_MODULATION_COMMAND": "1",
    "P_POWER_CORRECTION": "MW",
    "V_POWER_CORRECTION": "MW",
}
ARM_OBSERVABLES = {
    "I": ("I_ARM", "kA"),
    "W": ("ENERGY", "MJ"),
    "VCAP": ("V_CAP_EQ", "kV"),
    "V": ("V_INSERTED", "kV"),
    "VT": ("V_ARM", "kV"),
    "ICAP": ("I_CAP", "kA"),
    "PLOSS": ("P_NONOHMIC", "MW"),
}
for _prefix in ("P", "V"):
    FIXTURE_CHANNELS.update({f"{_prefix}_P_REFERENCE": "MW", f"{_prefix}_Q_REFERENCE": "MVAr", f"{_prefix}_VDC_REFERENCE": "kV"})
    FIXTURE_CHANNELS.update({f"{_prefix}_KCL_{name}": unit for name, unit in KCL_MEASUREMENTS.items()})
    FIXTURE_CHANNELS.update({
        f"{_prefix}_VDC_POS": "kV", f"{_prefix}_VDC_NEG": "kV",
        f"{_prefix}_IDC_NEG": "kA", f"{_prefix}_BLOCK": "1",
    })
    for _name in MODULATION_OUTPUTS:
        FIXTURE_CHANNELS[f"{_prefix}_{_name}"] = "1"
    for _phase in "ABC":
        for _quantity, _unit in (("I", "kA"), ("V", "kV")):
            FIXTURE_CHANNELS[f"{_prefix}_{_quantity}_{_phase}"] = _unit
            FIXTURE_CHANNELS[f"{_prefix}_VALVE_{_quantity}_{_phase}"] = _unit
        for _position in ("UPPER", "LOWER"):
            FIXTURE_CHANNELS[f"{_prefix}_{_phase}_{_position}_INET"] = "kA"
            for _suffix, (_, _unit) in ARM_OBSERVABLES.items():
                FIXTURE_CHANNELS[f"{_prefix}_{_phase}_{_position}_{_suffix}"] = _unit


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value: object, name: str, *, positive: bool = False) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be finite and real")
    result = float(value)
    if positive and result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def _format(value: float) -> str:
    return format(value, ".15g")


def _station_control(root: ET.Element) -> ET.Element:
    ports = {
        name: (72, -126 + index * 36, "Transfer", "Output")
        for index, name in enumerate(CONTROL_OUTPUTS)
    }
    control = _definition(root, CONTROL_NAME, ports, CONTROL_DEFAULTS, signed_parameters=("Phase_Offset_Deg", "Q_Order_MVAr"))
    control.find("./paramlist/param[@name='Description']").set(
        "value", "Native scheduled six-arm modulation and blocking"
    )
    _script(
        control,
        "Checks",
        "ERROR Frequency must be positive : Frequency_Hz > 0\n"
        "ERROR Modulation must stay below unity : Modulation_Index >= 0 && Modulation_Index < 1\n"
        "ERROR Reversal must follow deblock : Reversal_Time_s > Deblock_Time_s\n",
    )
    _script(
        control,
        "Fortran",
        """#LOCAL REAL ANGLE
#LOCAL REAL OFFSET
#LOCAL REAL MA
#LOCAL REAL MB
#LOCAL REAL MC
      OFFSET = $Phase_Offset_Deg * 0.0174532925199433
      IF (TIME .GE. $Reversal_Time_s) OFFSET = -OFFSET
      $ANGLE_COMMAND = OFFSET / 0.0174532925199433
      $MODULATION_COMMAND = $Modulation_Index
      $POWER_CORRECTION = 0.0
      $P_REFERENCE = $P_Order_MW * MIN(1.0, MAX(0.0, (TIME - $Deblock_Time_s) / $Ramp_Time_s))
      IF (TIME .GE. $Reversal_Time_s) $P_REFERENCE = $P_Order_MW * (1.0 - 2.0 * MIN(1.0, (TIME - $Reversal_Time_s) / $Reversal_Duration_s))
      $Q_REFERENCE = $Q_Order_MVAr * MIN(1.0, MAX(0.0, (TIME - $Deblock_Time_s) / $Ramp_Time_s))
      $VDC_REFERENCE = $Vdc_Order_kV
      ANGLE = 6.28318530717959 * $Frequency_Hz * TIME + OFFSET
      MA = $Modulation_Index * SIN(ANGLE)
      MB = $Modulation_Index * SIN(ANGLE - 2.09439510239320)
      MC = $Modulation_Index * SIN(ANGLE + 2.09439510239320)
      $M_A_UPPER = 0.5 * (1.0 - MA)
      $M_A_LOWER = 0.5 * (1.0 + MA)
      $M_B_UPPER = 0.5 * (1.0 - MB)
      $M_B_LOWER = 0.5 * (1.0 + MB)
      $M_C_UPPER = 0.5 * (1.0 - MC)
      $M_C_LOWER = 0.5 * (1.0 + MC)
      $BLOCK = 0.0
      $SEQUENCE = 2.0
      IF (TIME .LT. $Deblock_Time_s) THEN
        $BLOCK = 1.0
        $SEQUENCE = 1.0
      ELSEIF (TIME .GE. $Reversal_Time_s) THEN
        $SEQUENCE = 3.0
      ENDIF
""" + "".join(f"      ${name}_RAW = ${name}\n" for name in INSERTION_OUTPUTS),
    )
    return control


def _station_measurements(root: ET.Element) -> ET.Element:
    inputs = ("VA", "VB", "VC", "IA", "IB", "IC", "VDC", "IDC")
    ports = {
        name: (-72, -126 + index * 36, "Transfer", "Input")
        for index, name in enumerate(inputs)
    }
    ports.update(
        {
            name: (72, -18 + index * 36, "Transfer", "Output")
            for index, name in enumerate(("P", "Q"))
        }
    )
    measurements = _definition(root, MEASUREMENT_NAME, ports, {})
    measurements.find("./paramlist/param[@name='Description']").set(
        "value", "Native three-phase instantaneous power measurements"
    )
    _script(
        measurements,
        "Fortran",
        """      $P = $VA * $IA + $VB * $IB + $VC * $IC
      $Q = 0.577350269189626 * (($VB - $VC) * $IA + ($VC - $VA) * $IB + ($VA - $VB) * $IC)
""",
    )
    return measurements


def _closed_loop_control(root: ET.Element, master: dict, defaults: dict) -> dict:
    errors = _definition(
        root,
        "MMCControlErrors",
        {
            "P_MEAS": (-72, -72, "Transfer", "Input"),
            "Q_MEAS": (-72, -36, "Transfer", "Input"),
            "VDC_MEAS": (-72, 0, "Transfer", "Input"),
            "POWER_CORRECTION": (-72, 36, "Transfer", "Input"),
            "VDC_REFERENCE": (-72, 72, "Transfer", "Input"),
            "ACTIVE_ERROR": (72, -72, "Transfer", "Output"),
            "Q_ERROR": (72, -36, "Transfer", "Output"),
            "BLOCK": (72, 0, "Transfer", "Output"),
            "SEQUENCE": (72, 36, "Transfer", "Output"),
            "VDC_ERROR": (72, 72, "Transfer", "Output"),
            "P_REFERENCE": (72, 108, "Transfer", "Output"),
            "Q_REFERENCE": (72, 144, "Transfer", "Output"),
        },
        {
            name: CLOSED_LOOP_DEFAULTS[name]
            for name in (
                "P_Order_MW",
                "Q_Order_MVAr",
                "Vdc_Order_kV",
                "Control_Mode",
                "Deblock_Time_s",
                "Reversal_Time_s",
                "Ramp_Time_s",
                "Reversal_Duration_s",
                "Cable_Loss_MW",
                "Converter_Loss_MW",
            )
        },
        signed_parameters=("Q_Order_MVAr",),
    )
    _script(
        errors,
        "Fortran",
        """#LOCAL REAL SCALE
#LOCAL REAL REVERSE_SCALE
#LOCAL REAL PREF
      SCALE = 0.0
      IF (TIME .GE. $Deblock_Time_s) SCALE = MIN(1.0, MAX(0.0, (TIME - $Deblock_Time_s) / $Ramp_Time_s))
      PREF = SCALE * $P_Order_MW
      $SEQUENCE = 1.0
      IF (TIME .GE. $Deblock_Time_s) $SEQUENCE = 2.0
      IF (TIME .GE. $Reversal_Time_s) THEN
        REVERSE_SCALE = MIN(1.0, MAX(0.0, (TIME - $Reversal_Time_s) / $Reversal_Duration_s))
        PREF = $P_Order_MW * (1.0 - 2.0 * REVERSE_SCALE)
        $SEQUENCE = 3.0
      ENDIF
      $P_REFERENCE = PREF
      IF ($Control_Mode .GE. 0.5) $P_REFERENCE = -PREF + $POWER_CORRECTION + $Converter_Loss_MW + $Cable_Loss_MW * (PREF / $P_Order_MW)**2
      $ACTIVE_ERROR = $P_MEAS - $P_REFERENCE
      $VDC_ERROR = $VDC_REFERENCE - $VDC_MEAS
      IF ($Control_Mode .LT. 0.5) $VDC_ERROR = 0.0
      $Q_REFERENCE = SCALE * $Q_Order_MVAr
      $Q_ERROR = $Q_MEAS - $Q_REFERENCE
      $BLOCK = 0.0
      IF (TIME .LT. $Deblock_Time_s) THEN
        $ACTIVE_ERROR = 0.0
        $Q_ERROR = 0.0
        $VDC_ERROR = 0.0
        $BLOCK = 1.0
      ENDIF
""",
    )
    reference_frame = _definition(
        root,
        "MMCVoltageReferenceFrame",
        {
            **_feedback_ports(tuple(f"{phase}_UPPER_VT" for phase in "ABC")),
            "D": (72, -36, "Transfer", "Output"),
            "Q": (72, 0, "Transfer", "Output"),
        },
        {"Frequency_Hz": CLOSED_LOOP_DEFAULTS["Frequency_Hz"]},
    )
    _script(reference_frame, "Fortran", """#LOCAL REAL THETA
#LOCAL REAL VALPHA
#LOCAL REAL VBETA
      THETA = 6.28318530717959 * $Frequency_Hz * TIME
      VALPHA = (-2.0 * $A_UPPER_VT + $B_UPPER_VT + $C_UPPER_VT) / 3.0
      VBETA = ($C_UPPER_VT - $B_UPPER_VT) * 0.577350269189626
      $D = VALPHA * SIN(THETA) - VBETA * COS(THETA)
      $Q = VALPHA * COS(THETA) + VBETA * SIN(THETA)
""")
    energy_difference = _definition(
        root,
        "MMCArmEnergyDifference",
        {
            **_feedback_ports(tuple(f"{phase}_{position}_VCAP" for phase in "ABC" for position in ("UPPER", "LOWER"))),
            **{f"D{phase}": (72, -36 + index * 36, "Transfer", "Output") for index, phase in enumerate("ABC")},
            **{f"S{phase}": (72, 72 + index * 36, "Transfer", "Output") for index, phase in enumerate("ABC")},
        },
        {"C_eq_F": CLOSED_LOOP_DEFAULTS["C_eq_F"]},
    )
    _script(energy_difference, "Fortran", "".join(
        f"      $D{phase} = 0.5 * $C_eq_F * (${phase}_UPPER_VCAP**2 - ${phase}_LOWER_VCAP**2)\n"
        f"      $S{phase} = 0.5 * $C_eq_F * (${phase}_UPPER_VCAP**2 + ${phase}_LOWER_VCAP**2)\n"
        for phase in "ABC"
    ))
    synthesis = _definition(
        root,
        "MMCModulationSynthesis",
        {
            **_feedback_ports(("ANGLE_COMMAND", "MODULATION_COMMAND", "VDC_MEAS", "P_MEAS", "FRAME_D", "FRAME_Q", *ARM_FEEDBACK_INPUTS, "DWA", "DWB", "DWC", "SWA", "SWB", "SWC")),
            **{
                name: (72, -126 + index * 36, "Transfer", "Output")
                for index, name in enumerate(MODULATION_OUTPUTS)
            },
        },
        {name: CLOSED_LOOP_DEFAULTS[name] for name in (
            "Frequency_Hz", "Vdc_Order_kV", "C_eq_F", "Circulating_Gain_ohm", "Energy_Gain_per_s", "R_arm_ohm", "P_nonohmic_MW"
        )},
    )
    _script(
        synthesis,
        "Fortran",
        """#LOCAL REAL ANGLE
#LOCAL REAL MODULATION
#LOCAL REAL MA
#LOCAL REAL MB
#LOCAL REAL MC
#LOCAL REAL WREF
#LOCAL REAL WPAIR
#LOCAL REAL ISUM
#LOCAL REAL IREF
#LOCAL REAL VCOMMON
#LOCAL REAL VACOM
#LOCAL REAL PLOSS
      ANGLE = 6.28318530717959 * $Frequency_Hz * TIME
      IF ($FRAME_D * $FRAME_D + $FRAME_Q * $FRAME_Q .GT. 1.0) ANGLE = ANGLE + ATAN2($FRAME_Q, $FRAME_D)
      ANGLE = ANGLE + $ANGLE_COMMAND * 0.0174532925199433
      MODULATION = MIN(0.98, MAX(0.10, $MODULATION_COMMAND))
      MA = MODULATION * SIN(ANGLE)
      MB = MODULATION * SIN(ANGLE - 2.09439510239320)
      MC = MODULATION * SIN(ANGLE + 2.09439510239320)
      WREF = 0.25 * $C_eq_F * $Vdc_Order_kV * $Vdc_Order_kV
""" + "".join(
            f"""      WPAIR = $SW{phase}
      ISUM = 0.5 * (${phase}_UPPER_I + ${phase}_LOWER_I)
      PLOSS = 2.0 * $P_nonohmic_MW + $R_arm_ohm * (${phase}_UPPER_I**2 + ${phase}_LOWER_I**2)
      VACOM = 0.5 * $Vdc_Order_kV * M{phase}
      IREF = (PLOSS - $P_MEAS / 3.0 - $Energy_Gain_per_s * (WPAIR - WREF)) / MAX(0.1 * $Vdc_Order_kV, $VDC_MEAS)
      IREF = IREF + 5.0 * $DW{phase} * VACOM / MAX(1.0, (0.5 * $Vdc_Order_kV * MODULATION)**2)
      VCOMMON = 0.5 * $VDC_MEAS + $Circulating_Gain_ohm * (ISUM - IREF)
      $M_{phase}_UPPER_RAW = (VCOMMON - VACOM) / MAX(0.1 * $Vdc_Order_kV, 2.0 * ${phase}_UPPER_VCAP)
      $M_{phase}_LOWER_RAW = (VCOMMON + VACOM) / MAX(0.1 * $Vdc_Order_kV, 2.0 * ${phase}_LOWER_VCAP)
      $M_{phase}_UPPER = MIN(1.0, MAX(0.0, $M_{phase}_UPPER_RAW))
      $M_{phase}_LOWER = MIN(1.0, MAX(0.0, $M_{phase}_LOWER_RAW))
""" for phase in "ABC"
        ),
    )
    ports = {
        **_feedback_ports(("P_MEAS", "Q_MEAS", "VDC_MEAS", *ARM_FEEDBACK_INPUTS)),
        **{
            name: (90, -180 + index * 36, "Transfer", "Output")
            for index, name in enumerate(CONTROL_OUTPUTS)
        },
    }
    controller = _definition(root, CLOSED_LOOP_CONTROL_NAME, ports, CLOSED_LOOP_DEFAULTS, signed_parameters=("Q_Order_MVAr", "Phase_Offset_Deg"))
    controller.find("./paramlist/param[@name='Description']").set(
        "value", "Native P/Q or Vdc/Q closed-loop six-arm modulation"
    )
    _script(
        controller,
        "Checks",
        "ERROR Frequency must be positive : Frequency_Hz > 0\n"
        "ERROR Deblock ramp must be positive : Ramp_Time_s > 0\n"
        "ERROR Reversal must follow the initial ramp : Reversal_Time_s > Deblock_Time_s + Ramp_Time_s\n"
        "ERROR Active PI time constant must be positive : Ti_Active_s > 0\n"
        "ERROR Reactive PI time constant must be positive : Ti_Reactive_s > 0\n"
        "ERROR Base modulation must be bounded : Base_Modulation > 0.1 && Base_Modulation < 0.98\n",
    )
    writer = _Writer(root, master, defaults)
    add = lambda role, scoped, parameters, bindings: writer.add(
        controller, role, scoped, parameters, bindings
    )
    for name in ("P_MEAS", "Q_MEAS", "VDC_MEAS", *ARM_FEEDBACK_INPUTS):
        add("input_" + name, "master:import", {"Name": name}, {"N": name})
    for name in CLOSED_LOOP_DEFAULTS:
        add("parameter_" + name, "master:import", {"Name": name}, {"N": name})
    add(
        "voltage_reference_frame",
        f"{NATIVE_SCOPE}:MMCVoltageReferenceFrame",
        {"Frequency_Hz": "Frequency_Hz"},
        {
            **{f"{phase}_UPPER_VT": f"{phase}_UPPER_VT" for phase in "ABC"},
            "D": "FRAME_D_RAW", "Q": "FRAME_Q_RAW",
        },
    )
    add(
        "arm_energy_difference",
        f"{NATIVE_SCOPE}:MMCArmEnergyDifference",
        {"C_eq_F": "C_eq_F"},
        {
            **{f"{phase}_{position}_VCAP": f"{phase}_{position}_VCAP" for phase in "ABC" for position in ("UPPER", "LOWER")},
            **{f"D{phase}": f"DW{phase}_RAW" for phase in "ABC"},
            **{f"S{phase}": f"SW{phase}_RAW" for phase in "ABC"},
        },
    )
    add(
        "errors",
        f"{NATIVE_SCOPE}:MMCControlErrors",
        {
            name: name
            for name in (
                "P_Order_MW",
                "Q_Order_MVAr",
                "Vdc_Order_kV",
                "Control_Mode",
                "Deblock_Time_s",
                "Reversal_Time_s",
                "Ramp_Time_s",
                "Reversal_Duration_s",
                "Cable_Loss_MW",
                "Converter_Loss_MW",
            )
        },
        {
            "P_MEAS": "P_FILTERED",
            "Q_MEAS": "Q_FILTERED",
            "VDC_MEAS": "VDC_FILTERED",
            "POWER_CORRECTION": "CTRL_POWER_CORRECTION",
            "VDC_REFERENCE": "CTRL_VDC_REFERENCE",
            "ACTIVE_ERROR": "ACTIVE_ERROR",
            "Q_ERROR": "Q_ERROR",
            "BLOCK": "CTRL_BLOCK",
            "SEQUENCE": "CTRL_SEQUENCE",
            "VDC_ERROR": "VDC_ERROR",
            "P_REFERENCE": "CTRL_P_REFERENCE",
            "Q_REFERENCE": "CTRL_Q_REFERENCE",
        },
    )
    for role, source, output, limit in (
        ("p_filter", "P_MEAS", "P_FILTERED", 10000.0),
        ("q_filter", "Q_MEAS", "Q_FILTERED", 10000.0),
        ("vdc_filter", "VDC_MEAS", "VDC_FILTERED", 2000.0),
        ("voltage_reference_ramp", "Vdc_Order_kV", "CTRL_VDC_REFERENCE", 2000.0),
        ("frame_d_filter", "FRAME_D_RAW", "FRAME_D", 2000.0),
        ("frame_q_filter", "FRAME_Q_RAW", "FRAME_Q", 2000.0),
        *((f"energy_difference_{phase}", f"DW{phase}_RAW", f"DW{phase}", 1000.0) for phase in "ABC"),
        *((f"energy_sum_{phase}", f"SW{phase}_RAW", f"SW{phase}", 1000.0) for phase in "ABC"),
    ):
        add(
            role,
            "master:realpole",
            {
                "Limit": "0",
                "COM": role,
                "Reset": "2" if role == "voltage_reference_ramp" else "0",
                "YO": "0.0",
                "Dim": "1",
                "G": "1.0",
                "T": (
                    "0.1 [s]" if role == "voltage_reference_ramp"
                    else "Energy_Difference_Filter_s" if role.startswith("energy_difference_")
                    else "Feedback_Filter_s"
                ),
                "Max": str(limit),
                "Min": str(-limit),
            },
            {"I:Dim": source, "O:Dim": output},
        )
    # EMTDC_XPI is parallel: GP*e + integral(e/TI). Scaling its input and
    # using GP=1 realizes the declared Kp*(e + integral(e/Ti)) controller.
    add(
        "voltage_error_gain",
        "master:gain",
        {"G": "Kp_Vdc_MW_per_kV", "Dim": "1", "COM": "Vdc PI output is active-power correction in MW"},
        {"IN:Dim": "VDC_ERROR", "OUT:Dim": "VDC_PI_INPUT"},
    )
    add(
        "voltage_power_lower_limit",
        "master:gain",
        {"G": "-1.0", "Dim": "1", "COM": "Negative physical power correction limit"},
        {"IN:Dim": "Power_Correction_Limit_MW", "OUT:Dim": "POWER_CORRECTION_MIN"},
    )
    add(
        "voltage_pi",
        "master:pi_ctlr",
        {"GP": "1.0", "TI": "Ti_Vdc_s", "YHI": "Power_Correction_Limit_MW",
         "YLO": "POWER_CORRECTION_MIN", "YINIT": "0.0", "Mthd": "0", "INTR": "0"},
        {"IN": "VDC_PI_INPUT", "OUT": "CTRL_POWER_CORRECTION"},
    )
    add(
        "active_error_gain",
        "master:gain",
        {"G": "Kp_Active", "Dim": "1", "COM": "PI input scaled for Ki=Kp/Ti"},
        {"IN:Dim": "ACTIVE_ERROR", "OUT:Dim": "ACTIVE_PI_INPUT"},
    )
    add(
        "reactive_error_gain",
        "master:gain",
        {"G": "Kp_Reactive", "Dim": "1", "COM": "PI input scaled for Ki=Kp/Ti"},
        {"IN:Dim": "Q_ERROR", "OUT:Dim": "REACTIVE_PI_INPUT"},
    )
    add(
        "active_pi",
        "master:pi_ctlr",
        {
            "GP": "1.0",
            "TI": "Ti_Active_s",
            "YHI": "30.0",
            "YLO": "-30.0",
            "YINIT": "0.0",
            "Mthd": "0",
            "INTR": "0",
        },
        {"IN": "ACTIVE_PI_INPUT", "OUT": "CTRL_ANGLE_COMMAND"},
    )
    add(
        "reactive_pi",
        "master:pi_ctlr",
        {
            "GP": "1.0",
            "TI": "Ti_Reactive_s",
            "YHI": "0.98",
            "YLO": "0.10",
            "YINIT": "Base_Modulation",
            "Mthd": "0",
            "INTR": "0",
        },
        {"IN": "REACTIVE_PI_INPUT", "OUT": "CTRL_MODULATION_COMMAND"},
    )
    add(
        "synthesis",
        f"{NATIVE_SCOPE}:MMCModulationSynthesis",
        {name: name for name in (
            "Frequency_Hz", "Vdc_Order_kV", "C_eq_F", "Circulating_Gain_ohm", "Energy_Gain_per_s", "R_arm_ohm", "P_nonohmic_MW"
        )},
        {
            "ANGLE_COMMAND": "CTRL_ANGLE_COMMAND",
            "MODULATION_COMMAND": "CTRL_MODULATION_COMMAND",
            "VDC_MEAS": "VDC_MEAS",
            "P_MEAS": "P_FILTERED",
            "FRAME_D": "FRAME_D",
            "FRAME_Q": "FRAME_Q",
            **{f"DW{phase}": f"DW{phase}" for phase in "ABC"},
            **{f"SW{phase}": f"SW{phase}" for phase in "ABC"},
            **{name: name for name in ARM_FEEDBACK_INPUTS},
            **{name: "CTRL_" + name for name in MODULATION_OUTPUTS},
        },
    )
    for name in CONTROL_OUTPUTS:
        add(
            "output_" + name,
            "master:export",
            {"Name": name},
            {"N": "CTRL_" + name},
        )
    writer.verify()
    return {"routes": writer.routes, "electrical_nets": dict(writer.nets)}


def _copy_constants(added: dict, destination: Path) -> dict[str, str]:
    destination.mkdir(parents=True, exist_ok=False)
    hashes = {}
    evidence = Path(added["constants"]["evidence_path"])
    for filename, expected in added["constants"]["produced_files"].items():
        source = evidence.parent / filename
        target = destination / filename
        shutil.copy2(source, target)
        if _hash(target) != expected:
            raise ValueError("Copied native cable artifact differs from its receipt")
        hashes[str(target.resolve())] = expected
    receipt = destination / "evidence.json"
    shutil.copy2(evidence, receipt)
    hashes[str(receipt.resolve())] = _hash(receipt)
    return hashes


def materialize_native_avm_library(
    destination: str | Path,
    *,
    constants_evidence: str | Path,
    master_path: str | Path = DEFAULT_MASTER,
    source_project: str | Path = DEFAULT_DONOR,
) -> dict:
    """Create the physical arm, modulator and cable in one native library."""
    target = Path(destination).resolve()
    if target.exists() or target.is_symlink():
        raise FileExistsError("Native AVM library destination must be new")
    master = Path(master_path).resolve()
    source = Path(source_project).resolve()
    metadata, master_hash, defaults = _audit_master(master)
    root, arm_writer = _make_library(metadata, defaults, scope=NATIVE_SCOPE)
    _station_control(root)
    _station_measurements(root)
    sample = _definition(root, SAMPLE_NAME,
                         {"IN": (-36, 0, "Transfer", "Input"), "OUT": (36, 0, "Transfer", "Output")}, {})
    _script(sample, "Dsdyn", "      $OUT = $IN\n")
    closed_loop = _closed_loop_control(root, metadata, defaults)
    evidence = Path(constants_evidence).resolve()
    constants_name = Path(
        json.loads(evidence.read_text(encoding="utf-8"))["constants_path"]
    ).name
    constants_path = target.parent / "constants" / constants_name
    added = append_native_cable_link(
        root,
        constants_evidence=evidence,
        source_project=source,
        master_path=master,
        local_constants=constants_path,
    )
    delivered_constants = _copy_constants(added, constants_path.parent)
    library_hash = _write_new(target, root)
    if _hash(master) != master_hash:
        raise ValueError("Master changed while materializing the native AVM library")
    return {
        "schema_version": 1,
        "scope": "native_mmc_avm_library",
        "library_path": str(target),
        "library_sha256": library_hash,
        "master_path": str(master),
        "master_sha256": master_hash,
        "source_project": str(source),
        "source_hashes": added["input_hashes"],
        "constants_path": str(constants_path),
        "constants_sha256": added["constants"]["constants_sha256"],
        "constants_receipt": str(evidence),
        "constants_artifacts": delivered_constants,
        "cable_name": added["constants"]["segment"],
        "cable_length_km": added["constants"]["length_km"],
        "cable_configuration_id": added["configuration"].get("id"),
        "cable_topology": {
            "module_wires": added["module_wires"],
            "source_definition_receipts": added["source_definition_receipts"],
            "geometry_semantics_sha256": added["geometry_semantics_sha256"],
        },
        "arm_topology": {
            "electrical_nets": {
                name: dict(nets) for name, nets in arm_writer.nets.items()
            },
            "routes": arm_writer.routes,
        },
        "control": {
            "definition": f"{NATIVE_SCOPE}:{CONTROL_NAME}",
            "kind": "scheduled_open_loop",
            "outputs": list(CONTROL_OUTPUTS),
        },
        "measurements": {
            "definition": f"{NATIVE_SCOPE}:{MEASUREMENT_NAME}",
            "inputs": ["VA", "VB", "VC", "IA", "IB", "IC", "VDC", "IDC"],
            "outputs": ["P", "Q"],
        },
        "closed_loop_control": {
            "definition": f"{NATIVE_SCOPE}:{CLOSED_LOOP_CONTROL_NAME}",
            "kind": "p_q_and_vdc_q_feedback",
            "routes": closed_loop["routes"],
        },
        "model_accepted": False,
    }


def _source_parameters(
    name: str,
    voltage_kv: float,
    frequency_hz: float,
    grid_r_ohm: float,
    grid_x_ohm: float,
) -> dict:
    impedance = math.hypot(grid_r_ohm, grid_x_ohm)
    angle = math.degrees(math.atan2(grid_x_ohm, grid_r_ohm))
    return {
        "Name": name,
        "View": "1",
        "Type": "3",
        "Ctrl": "0",
        "MVA": "1000.0 [MVA]",
        "Vm": f"{_format(voltage_kv)} [kV]",
        "F": f"{_format(frequency_hz)} [Hz]",
        "Tc": "0.05 [s]",
        "ZSeq": "0",
        "Imp": "1",
        "Term": "0",
        "Z1": f"{_format(impedance)} [ohm]",
        "Phi1": f"{_format(angle)} [deg]",
        "Es": f"{_format(voltage_kv)} [kV]",
        "F0": f"{_format(frequency_hz)} [Hz]",
        "Ph": "0.0 [deg]",
    }


def _transformer_parameters(
    name: str,
    primary_voltage_kv: float,
    secondary_voltage_kv: float,
    frequency_hz: float,
    rating_mva: float,
) -> dict:
    return {
        "Name": name,
        "Tmva": f"{_format(rating_mva)} [MVA]",
        "f": f"{_format(frequency_hz)} [Hz]",
        "YD1": "0",
        "YD2": "1",
        "Lead": "1",
        "Xl": "0.15 [pu]",
        "Ideal": "1",
        "NLL": "0.0 [pu]",
        "CuL": "0.0 [pu]",
        "View": "1",
        "V1": f"{_format(primary_voltage_kv)} [kV]",
        "V2": f"{_format(secondary_voltage_kv)} [kV]",
        "Sat": "0",
    }


def _hierarchy_call(
    parent: ET.Element, component: ET.Element, *, z: int, instance: int
) -> ET.Element:
    return ET.SubElement(
        parent,
        "call",
        {
            "link": component.get("id"),
            "name": component.get("defn"),
            "z": str(z),
            "view": "false",
            "instance": str(instance),
        },
    )


def materialize_native_avm_fixture(
    destination: str | Path,
    *,
    constants_evidence: str | Path,
    master_path: str | Path = DEFAULT_MASTER,
    source_project: str | Path = DEFAULT_DONOR,
    project_name: str = "mmc_native_avm_fixture",
    frequency_hz: float = 60.0,
    ac_voltage_kv: float | None = None,
    station_p_ac_voltage_kv: float | None = None,
    station_vdc_ac_voltage_kv: float | None = None,
    station_p_valve_voltage_kv: float | None = None,
    station_vdc_valve_voltage_kv: float | None = None,
    station_p_grid_r_ohm: float = 2.0,
    station_p_grid_x_ohm: float = 19.8997487421,
    station_vdc_grid_r_ohm: float = 2.0,
    station_vdc_grid_x_ohm: float = 19.8997487421,
    transformer_rating_mva: float = 1200.0,
    modulation_index: float = 0.82,
    control_kind: str = "scheduled_open_loop",
    active_power_order_mw: float = 1000.0,
    reactive_power_order_mvar: float = 0.0,
    vdc_order_kv: float = 640.0,
    ramp_time_s: float = 0.20,
    p_control_kp: float = 0.01,
    vdc_control_kp: float = 0.01,
    active_control_ti_s: float = 0.10,
    reactive_control_kp: float = 0.00005,
    reactive_control_ti_s: float = 0.05,
    dc_voltage_control_kp: float = 3.0,
    dc_voltage_control_ti_s: float = 0.30,
    energy_control_gain: float = 10.0,
    circulating_control_bandwidth_hz: float = 60.0,
    feedback_filter_s: float = 0.02,
    energy_difference_filter_s: float = 0.05,
    cable_loss_mw: float = 0.0,
    converter_loss_mw: float = 0.0,
    dc_grounding_resistance_ohm: float = 1e6,
    valve_grounding_resistance_ohm: float = 1e6,
    deblock_time_s: float = 0.10,
    reversal_time_s: float = 0.30,
    reversal_duration_s: float = 0.50,
    simulation_duration_s: float = 0.5,
    time_step_s: float = 20e-6,
    output_step_s: float = 100e-6,
    arm_parameters: AverageArmParameters | None = None,
) -> dict:
    """Create a complete two-station, twelve-arm native integration fixture."""
    folder = Path(destination).resolve()
    if folder.exists() or folder.is_symlink():
        raise FileExistsError("Native AVM fixture directory must be new")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", project_name):
        raise ValueError("project_name must be a PSCAD-safe identifier")
    common_voltage = 230.0 if ac_voltage_kv is None else _number(
        ac_voltage_kv, "ac_voltage_kv", positive=True
    )
    station_p_ac_voltage_kv = _number(
        common_voltage if station_p_ac_voltage_kv is None else station_p_ac_voltage_kv,
        "station_p_ac_voltage_kv",
        positive=True,
    )
    station_vdc_ac_voltage_kv = _number(
        common_voltage
        if station_vdc_ac_voltage_kv is None
        else station_vdc_ac_voltage_kv,
        "station_vdc_ac_voltage_kv",
        positive=True,
    )
    station_p_valve_voltage_kv = _number(
        station_p_ac_voltage_kv
        if station_p_valve_voltage_kv is None
        else station_p_valve_voltage_kv,
        "station_p_valve_voltage_kv",
        positive=True,
    )
    station_vdc_valve_voltage_kv = _number(
        station_vdc_ac_voltage_kv
        if station_vdc_valve_voltage_kv is None
        else station_vdc_valve_voltage_kv,
        "station_vdc_valve_voltage_kv",
        positive=True,
    )
    frequency_hz = _number(frequency_hz, "frequency_hz", positive=True)
    dc_grounding_resistance_ohm = _number(dc_grounding_resistance_ohm, "dc_grounding_resistance_ohm", positive=True)
    valve_grounding_resistance_ohm = _number(valve_grounding_resistance_ohm, "valve_grounding_resistance_ohm", positive=True)
    transformer_rating_mva = _number(
        transformer_rating_mva, "transformer_rating_mva", positive=True
    )
    if control_kind not in {"scheduled_open_loop", "closed_loop"}:
        raise ValueError("control_kind must be scheduled_open_loop or closed_loop")
    active_power_order_mw = _number(
        active_power_order_mw, "active_power_order_mw", positive=True
    )
    reactive_power_order_mvar = _number(
        reactive_power_order_mvar, "reactive_power_order_mvar"
    )
    vdc_order_kv = _number(vdc_order_kv, "vdc_order_kv", positive=True)
    cable_loss_mw = _number(cable_loss_mw, "cable_loss_mw")
    converter_loss_mw = _number(converter_loss_mw, "converter_loss_mw")
    if min(cable_loss_mw, converter_loss_mw) < 0:
        raise ValueError("Native loss feedforward must be nonnegative")
    ramp_time_s = _number(ramp_time_s, "ramp_time_s", positive=True)
    p_control_kp = _number(p_control_kp, "p_control_kp", positive=True)
    vdc_control_kp = _number(vdc_control_kp, "vdc_control_kp", positive=True)
    active_control_ti_s = _number(
        active_control_ti_s, "active_control_ti_s", positive=True
    )
    reactive_control_kp = _number(
        reactive_control_kp, "reactive_control_kp", positive=True
    )
    reactive_control_ti_s = _number(
        reactive_control_ti_s, "reactive_control_ti_s", positive=True
    )
    control_settings = {
        "Kp_Vdc_MW_per_kV": _number(dc_voltage_control_kp, "dc_voltage_control_kp", positive=True),
        "Ti_Vdc_s": _number(dc_voltage_control_ti_s, "dc_voltage_control_ti_s", positive=True),
        "Energy_Gain_per_s": _number(energy_control_gain, "energy_control_gain", positive=True),
        "Feedback_Filter_s": _number(feedback_filter_s, "feedback_filter_s", positive=True),
        "Energy_Difference_Filter_s": _number(energy_difference_filter_s, "energy_difference_filter_s", positive=True),
    }
    circulating_control_bandwidth_hz = _number(circulating_control_bandwidth_hz, "circulating_control_bandwidth_hz", positive=True)
    station_p_grid_r_ohm = _number(
        station_p_grid_r_ohm, "station_p_grid_r_ohm", positive=True
    )
    station_vdc_grid_r_ohm = _number(
        station_vdc_grid_r_ohm, "station_vdc_grid_r_ohm", positive=True
    )
    station_p_grid_x_ohm = _number(
        station_p_grid_x_ohm, "station_p_grid_x_ohm"
    )
    station_vdc_grid_x_ohm = _number(
        station_vdc_grid_x_ohm, "station_vdc_grid_x_ohm"
    )
    deblock_time_s = _number(deblock_time_s, "deblock_time_s")
    if min(station_p_grid_x_ohm, station_vdc_grid_x_ohm, deblock_time_s) < 0:
        raise ValueError("Grid reactance and deblock time must be nonnegative")
    modulation_index = _number(modulation_index, "modulation_index")
    reversal_time_s = _number(reversal_time_s, "reversal_time_s", positive=True)
    reversal_duration_s = _number(reversal_duration_s, "reversal_duration_s", positive=True)
    simulation_duration_s = _number(
        simulation_duration_s, "simulation_duration_s", positive=True
    )
    time_step_s = _number(time_step_s, "time_step_s", positive=True)
    output_step_s = _number(output_step_s, "output_step_s", positive=True)
    if (
        not 0 <= modulation_index < 1
        or reversal_time_s <= deblock_time_s
        or (
            control_kind == "closed_loop"
            and reversal_time_s <= deblock_time_s + ramp_time_s
        )
        or simulation_duration_s <= reversal_time_s
        or output_step_s < time_step_s
    ):
        raise ValueError("Native AVM timing or modulation parameters are inconsistent")
    folder.mkdir(parents=True)
    library = folder / f"{NATIVE_SCOPE}.pslx"
    library_receipt = materialize_native_avm_library(
        library,
        constants_evidence=constants_evidence,
        master_path=master_path,
        source_project=source_project,
    )
    master_metadata, master_hash, master_defaults = _audit_master(
        Path(master_path).resolve()
    )
    library_metadata = read_definition_metadata_document(library.read_bytes())
    root = _project(project_name, library=False)
    settings = root.find("./paramlist[@name='Settings']")
    for name, value in {
        "time_duration": _format(simulation_duration_s),
        "time_step": _format(time_step_s * 1e6),
        "sample_step": _format(output_step_s * 1e6),
        "PlotType": "1",
        "StartType": "0",
        "output_filename": project_name + ".out",
    }.items():
        settings.find(f"param[@name='{name}']").set("value", value)
    writer = _Writer(
        root,
        master_metadata,
        master_defaults,
        {NATIVE_SCOPE: library_metadata},
    )
    main = root.find("./definitions/Definition[@name='Main']")
    hierarchy = root.find("./hierarchy/call/call")
    custom: list[tuple[ET.Element, str]] = []
    arm_values = asdict(arm_parameters or AverageArmParameters(L_arm_H=0.1))

    for station, prefix, phase_offset, station_voltage, valve_voltage, grid_r, grid_x in (
        (
            "P",
            "P",
            5.0,
            station_p_ac_voltage_kv,
            station_p_valve_voltage_kv,
            station_p_grid_r_ohm,
            station_p_grid_x_ohm,
        ),
        (
            "VDC",
            "V",
            0.0,
            station_vdc_ac_voltage_kv,
            station_vdc_valve_voltage_kv,
            station_vdc_grid_r_ohm,
            station_vdc_grid_x_ohm,
        ),
    ):
        explicit_grid_r = min(0.1, grid_r)
        source = writer.add(
            main,
            prefix + "_source",
            "master:source3",
            _source_parameters(
                prefix + "_SOURCE",
                station_voltage,
                frequency_hz,
                grid_r - explicit_grid_r,
                grid_x,
            ),
            {"N3": prefix + "_SOURCE_VECTOR", "N": "GND"},
        )
        writer.add(
            main,
            prefix + "_source_breakout",
            "master:breakout",
            {"Com": "0", "Dis": "0"},
            {
                "N": prefix + "_SOURCE_VECTOR",
                "N1": prefix + "_SOURCE_A",
                "N2": prefix + "_SOURCE_B",
                "N3": prefix + "_SOURCE_C",
            },
        )
        for phase in "ABC":
            writer.add(
                main,
                prefix + "_grid_resistor_" + phase,
                "master:resistor",
                {"R": f"{_format(explicit_grid_r)} [ohm]"},
                {
                    "A": prefix + "_SOURCE_" + phase,
                    "B": prefix + "_GRID_R_" + phase,
                },
            )
            writer.add(
                main,
                prefix + "_grid_current_" + phase,
                "master:ammeter",
                {"Name": prefix + "_I_" + phase},
                {
                    "N1": prefix + "_GRID_R_" + phase,
                    "N2": prefix + "_GRID_" + phase,
                },
            )
        writer.add(
            main,
            prefix + "_grid_merger",
            "master:breakout",
            {"Com": "0", "Dis": "0"},
            {
                "N": prefix + "_GRID",
                "N1": prefix + "_GRID_A",
                "N2": prefix + "_GRID_B",
                "N3": prefix + "_GRID_C",
            },
        )
        transformer = writer.add(
            main,
            prefix + "_transformer",
            "master:xfmr-3p2w",
            _transformer_parameters(
                prefix + "_XFMR",
                station_voltage,
                valve_voltage,
                frequency_hz,
                transformer_rating_mva,
            ),
            {
                "N1": prefix + "_GRID",
                "N2": prefix + "_VALVE_VECTOR",
                "G1": "GND",
            },
        )
        writer.add(
            main,
            prefix + "_breakout",
            "master:breakout",
            {"Com": "0", "Dis": "0"},
            {
                "N": prefix + "_VALVE_VECTOR",
                "N1": prefix + "_VALVE_A",
                "N2": prefix + "_VALVE_B",
                "N3": prefix + "_VALVE_C",
            },
        )
        if control_kind == "scheduled_open_loop":
            control = writer.add(
                main,
                prefix + "_modulator",
                f"{NATIVE_SCOPE}:{CONTROL_NAME}",
                {
                    **CONTROL_DEFAULTS,
                    "Frequency_Hz": frequency_hz,
                    "Modulation_Index": modulation_index,
                    "Phase_Offset_Deg": phase_offset,
                    "Deblock_Time_s": deblock_time_s,
                    "Reversal_Time_s": reversal_time_s,
                    "P_Order_MW": active_power_order_mw,
                    "Q_Order_MVAr": reactive_power_order_mvar,
                    "Vdc_Order_kV": vdc_order_kv,
                    "Ramp_Time_s": ramp_time_s,
                    "Reversal_Duration_s": reversal_duration_s,
                },
                {name: prefix + "_" + name for name in CONTROL_OUTPUTS},
            )
            custom.append((control, CONTROL_NAME))
        else:
            control = writer.add(
                main,
                prefix + "_controller",
                f"{NATIVE_SCOPE}:{CLOSED_LOOP_CONTROL_NAME}",
                {
                    **CLOSED_LOOP_DEFAULTS,
                    **control_settings,
                    "Frequency_Hz": frequency_hz,
                    "P_Order_MW": active_power_order_mw,
                    "Q_Order_MVAr": reactive_power_order_mvar,
                    "Vdc_Order_kV": vdc_order_kv,
                    "Control_Mode": 0.0 if station == "P" else 1.0,
                    "Kp_Active": (
                        p_control_kp if station == "P" else vdc_control_kp
                    ),
                    "Ti_Active_s": active_control_ti_s,
                    "Kp_Reactive": reactive_control_kp,
                    "Ti_Reactive_s": reactive_control_ti_s,
                    "Base_Modulation": modulation_index,
                    "Power_Correction_Limit_MW": 1.5 * active_power_order_mw,
                    "Cable_Loss_MW": cable_loss_mw,
                    "Converter_Loss_MW": converter_loss_mw,
                    "C_eq_F": arm_values["C_eq_F"],
                    "R_arm_ohm": arm_values["R_arm_ohm"],
                    "P_nonohmic_MW": arm_values["P_nonohmic_MW"],
                    "Circulating_Gain_ohm": 2 * math.pi * circulating_control_bandwidth_hz * arm_values["L_arm_H"],
                    "Deblock_Time_s": deblock_time_s,
                    "Reversal_Time_s": reversal_time_s,
                    "Ramp_Time_s": ramp_time_s,
                    "Reversal_Duration_s": reversal_duration_s,
                },
                {
                    "P_MEAS": prefix + "_P",
                    "Q_MEAS": prefix + "_Q",
                    "VDC_MEAS": prefix + "_VDC",
                    **{name: prefix + "_" + name for name in ARM_FEEDBACK_INPUTS},
                    **{name: prefix + "_" + name for name in CONTROL_OUTPUTS},
                },
            )
            custom.append((control, CLOSED_LOOP_CONTROL_NAME))
        for phase in "ABC":
            writer.add(
                main, prefix + "_valve_current_" + phase, "master:ammeter",
                {"Name": prefix + "_VALVE_I_" + phase},
                {"N1": prefix + "_VALVE_" + phase, "N2": prefix + "_PHASE_" + phase},
            )
            writer.add(
                main, prefix + "_valve_ground_" + phase, "master:resistor",
                {"R": f"{_format(valve_grounding_resistance_ohm)} [ohm]"},
                {"A": prefix + "_PHASE_" + phase, "B": "GND"},
            )
            writer.add(
                main, prefix + "_valve_voltage_" + phase, "master:voltmeter",
                {"Name": prefix + "_VALVE_V_" + phase},
                {"N1": prefix + "_PHASE_" + phase, "N2": "GND"},
            )
            for position in ("UPPER", "LOWER"):
                role = f"{prefix}_{phase}_{position}"
                inputs = (
                    (prefix + "_DC_POS", prefix + "_PHASE_" + phase)
                    if position == "UPPER"
                    else (prefix + "_PHASE_" + phase, prefix + "_DC_NEG")
                )
                arm = writer.add(
                    main,
                    role,
                    f"{NATIVE_SCOPE}:MMCAverageArm",
                    arm_values,
                    {
                        "IN": inputs[0],
                        "OUT": inputs[1],
                        "M": prefix + f"_M_{phase}_{position}",
                        "BLOCK": prefix + "_BLOCK",
                        **{
                            port: role + "_" + suffix
                            for suffix, (port, _) in ARM_OBSERVABLES.items()
                        },
                    },
                )
                custom.append((arm, "MMCAverageArm"))
            writer.add(
                main,
                prefix + "_phase_voltage_" + phase,
                "master:voltmeter",
                {"Name": prefix + "_V_" + phase},
                {"N1": prefix + "_GRID_" + phase, "N2": "GND"},
            )
        if source is None or transformer is None:
            raise ValueError(f"Native station {station} instances were not authored")

    for prefix in ("P", "V"):
        writer.add(
            main,
            prefix + "_dc_current",
            "master:ammeter",
            {"Name": prefix + "_IDC"},
            {"N1": prefix + "_DC_POS", "N2": prefix + "_CABLE_POS"},
        )
        writer.add(
            main, prefix + "_dc_negative_current", "master:ammeter",
            {"Name": prefix + "_IDC_NEG"},
            {"N1": prefix + "_DC_NEG", "N2": prefix + "_CABLE_NEG"},
        )
    cable = writer.add(
        main,
        "DC_CABLE",
        f"{NATIVE_SCOPE}:MMCCableLink",
        {},
        {
            "SEND_POS": "P_CABLE_POS",
            "SEND_NEG": "P_CABLE_NEG",
            "RECV_POS": "V_CABLE_POS",
            "RECV_NEG": "V_CABLE_NEG",
        },
    )
    custom.append((cable, "MMCCableLink"))
    writer.add(main, "neutral_ground", "master:ground", {}, {"A": "GND"})
    for prefix in ("P", "V"):
        for pole in ("POS", "NEG"):
            writer.add(
                main, prefix + "_pole_ground_" + pole, "master:resistor",
                {"R": f"{_format(dc_grounding_resistance_ohm)} [ohm]"},
                {"A": prefix + "_DC_" + pole, "B": "GND"},
            )
            writer.add(
                main, prefix + "_pole_voltage_" + pole, "master:voltmeter",
                {"Name": prefix + "_VDC_" + pole},
                {"N1": prefix + "_DC_" + pole, "N2": "GND"},
            )
        writer.add(
            main,
            prefix + "_vdc_meter",
            "master:voltmeter",
            {"Name": prefix + "_VDC"},
            {"N1": prefix + "_DC_POS", "N2": prefix + "_DC_NEG"},
        )
        writer.add(
            main,
            prefix + "_measurements",
            f"{NATIVE_SCOPE}:{MEASUREMENT_NAME}",
            {},
            {
                "VA": prefix + "_V_A",
                "VB": prefix + "_V_B",
                "VC": prefix + "_V_C",
                "IA": prefix + "_I_A",
                "IB": prefix + "_I_B",
                "IC": prefix + "_I_C",
                "VDC": prefix + "_VDC",
                "IDC": prefix + "_IDC",
                "P": prefix + "_P",
                "Q": prefix + "_Q",
            },
        )
    selected_signals = {name: name for name in FIXTURE_CHANNELS}
    for prefix in ("P", "V"):
        for phase in "ABC":
            for position in ("UPPER", "LOWER"):
                selected_signals[f"{prefix}_{phase}_{position}_INET"] = f"{prefix}_{phase}_{position}_I"
        # Arm exports are written in DSDYN from the preceding DSOUT solution.
        # Copy the independent Main meters in that same phase; do not shift or
        # interpolate OUT samples after the simulation to manufacture KCL.
        for name in KCL_MEASUREMENTS:
            writer.add(main, prefix + "_kcl_sample_" + name, NATIVE_SCOPE + ":" + SAMPLE_NAME, {},
                       {"IN": prefix + "_" + name, "OUT": prefix + "_KCL_" + name})
    for name, signal in selected_signals.items():
        writer.add(
            main,
            "probe_" + name,
            "master:pgb",
            {
                "Name": name,
                "Units": FIXTURE_CHANNELS[name],
                "Group": "MMC_NATIVE",
                "UseSignalName": "0",
                "enab": "1",
                "Display": "1",
                "Scale": "1.0",
                "mrun": "0",
                "Pol": "0",
                "Max": "1000.0",
                "Min": "-1000.0",
            },
            {"Signl": signal},
        )
    writer.verify()
    arm_instances = {
        "P_A_UPPER": 0,
        "P_A_LOWER": 1,
        "P_B_UPPER": 2,
        "P_B_LOWER": 3,
        "P_C_UPPER": 11,
        "P_C_LOWER": 5,
        "V_A_UPPER": 4,
        "V_A_LOWER": 10,
        "V_B_UPPER": 6,
        "V_B_LOWER": 7,
        "V_C_UPPER": 8,
        "V_C_LOWER": 9,
    }
    hierarchy_order = {
        **{
            f"P_{phase}_{position}": 30 + index * 10
            for index, (phase, position) in enumerate(
                (phase, position)
                for phase in "ABC"
                for position in ("UPPER", "LOWER")
            )
        },
        **{
            f"V_{phase}_{position}": 110 + index * 10
            for index, (phase, position) in enumerate(
                (phase, position)
                for phase in "ABC"
                for position in ("UPPER", "LOWER")
            )
        },
        "DC_CABLE": 170,
        "P_controller": 10,
        "V_controller": 90,
    }
    for component, definition in custom:
        if definition == CONTROL_NAME:
            continue
        call = _hierarchy_call(
            hierarchy,
            component,
            z=hierarchy_order[component.get("name")],
            instance=(
                arm_instances[component.get("name")] if definition == "MMCAverageArm"
                else 1 if component.get("name") == "V_controller" else 0
            ),
        )
        if definition == "MMCCableLink":
            ET.SubElement(
                call,
                "call",
                {
                    "link": library_receipt["cable_configuration_id"],
                    "name": f"{NATIVE_SCOPE}:Cable2",
                    "z": "-1",
                    "view": "false",
                    "instance": "0",
                },
            )
    project = folder / (project_name + ".pscx")
    project_hash = _write_new(project, root)
    receipt = {
        "schema_version": 1,
        "scope": "native_two_station_twelve_arm_avm_fixture",
        "project_name": project_name,
        "project_path": str(project),
        "project_sha256": project_hash,
        "library": library_receipt,
        "master_sha256": master_hash,
        "parameters": {
            "frequency_hz": frequency_hz,
            "station_p_ac_voltage_kv": station_p_ac_voltage_kv,
            "station_vdc_ac_voltage_kv": station_vdc_ac_voltage_kv,
            "station_p_valve_voltage_kv": station_p_valve_voltage_kv,
            "station_vdc_valve_voltage_kv": station_vdc_valve_voltage_kv,
            "station_p_grid_r_ohm": station_p_grid_r_ohm,
            "station_p_grid_x_ohm": station_p_grid_x_ohm,
            "station_vdc_grid_r_ohm": station_vdc_grid_r_ohm,
            "station_vdc_grid_x_ohm": station_vdc_grid_x_ohm,
            "control_settings": control_settings,
            "circulating_control_bandwidth_hz": circulating_control_bandwidth_hz,
            "dc_grounding_resistance_ohm": dc_grounding_resistance_ohm,
            "valve_grounding_resistance_ohm": valve_grounding_resistance_ohm,
            "transformer_rating_mva": transformer_rating_mva,
            "modulation_index": modulation_index,
            "control_kind": control_kind,
            "active_power_order_mw": active_power_order_mw,
            "reactive_power_order_mvar": reactive_power_order_mvar,
            "vdc_order_kv": vdc_order_kv,
            "ramp_time_s": ramp_time_s,
            "p_control_kp": p_control_kp,
            "vdc_control_kp": vdc_control_kp,
            "active_control_ti_s": active_control_ti_s,
            "reactive_control_kp": reactive_control_kp,
            "reactive_control_ti_s": reactive_control_ti_s,
            "cable_loss_mw": cable_loss_mw,
            "converter_loss_mw": converter_loss_mw,
            "deblock_time_s": deblock_time_s,
            "reversal_time_s": reversal_time_s,
            "reversal_duration_s": reversal_duration_s,
            "simulation_duration_s": simulation_duration_s,
            "time_step_s": time_step_s,
            "output_step_s": output_step_s,
            "cable_length_km": library_receipt["cable_length_km"],
            "arm": arm_values,
        },
        "electrical_nets": {name: dict(nets) for name, nets in writer.nets.items()},
        "routes": writer.routes,
        "channels": FIXTURE_CHANNELS,
        "network_identity_sampling": "DSDYN copies of the preceding network solution; arm resistance branch current exports",
        "control_kind": control_kind,
        "model_accepted": False,
        "licensed_acceptance": "NOT_RUN",
    }
    receipt["topology"] = audit_native_avm_fixture(project, receipt)
    receipt["source_hashes_after"] = {
        path: _hash(Path(path)) for path in library_receipt["source_hashes"]
    }
    if receipt["source_hashes_after"] != library_receipt["source_hashes"]:
        raise ValueError("Native AVM source inputs changed during materialization")
    receipt_path = folder / "native-avm-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return receipt


def audit_native_avm_fixture(
    project_path: str | Path,
    receipt: dict,
    *,
    finalized_library_sha256: str | None = None,
) -> dict:
    root = ET.parse(project_path).getroot()
    if root.get("name") != receipt["project_name"] or root.get("version") != "4.6.2":
        raise ValueError("Native AVM project identity changed")
    main = root.find("./definitions/Definition[@name='Main']")
    counts = Counter(user.get("defn") for user in main.findall("./schematic/User"))
    control_definition = (
        CLOSED_LOOP_CONTROL_NAME
        if receipt["control_kind"] == "closed_loop"
        else CONTROL_NAME
    )
    required = {
        f"{NATIVE_SCOPE}:MMCAverageArm": 12,
        f"{NATIVE_SCOPE}:{control_definition}": 2,
        f"{NATIVE_SCOPE}:{MEASUREMENT_NAME}": 2,
        f"{NATIVE_SCOPE}:MMCCableLink": 1,
        "master:source3": 2,
        "master:xfmr-3p2w": 2,
        "master:breakout": 6,
        "master:resistor": 16,
        "master:ammeter": 16,
        "master:ground": 1,
        "master:voltmeter": 18,
        "master:pgb": len(FIXTURE_CHANNELS),
    }
    if any(counts[name] != count for name, count in required.items()):
        raise ValueError("Native AVM fixture is missing a required physical component")
    nets = receipt["electrical_nets"]["Main"]
    if {
        "P_source:N",
        "P_transformer:G1",
        "V_source:N",
        "V_transformer:G1",
        "neutral_ground:A",
    } - set(nets["GND"]):
        raise ValueError("Native AVM source and transformer neutrals are not grounded")
    for prefix in ("P", "V"):
        if {
            f"{prefix}_source:N3",
            f"{prefix}_source_breakout:N",
        } - set(nets[prefix + "_SOURCE_VECTOR"]):
            raise ValueError("Native AVM source does not feed the source breakout")
        if {
            f"{prefix}_grid_merger:N",
            f"{prefix}_transformer:N1",
        } - set(nets[prefix + "_GRID"]):
            raise ValueError("Native AVM grid merger does not feed the transformer")
        for phase_index, phase in enumerate("ABC", start=1):
            if {
            f"{prefix}_source_breakout:N{phase_index}",
            f"{prefix}_grid_resistor_{phase}:A",
            } - set(nets[prefix + "_SOURCE_" + phase]) or {
                f"{prefix}_grid_resistor_{phase}:B",
                f"{prefix}_grid_current_{phase}:N1",
            } - set(nets[prefix + "_GRID_R_" + phase]) or {
                f"{prefix}_grid_current_{phase}:N2",
                f"{prefix}_grid_merger:N{phase_index}",
                f"{prefix}_phase_voltage_{phase}:N1",
            } - set(nets[prefix + "_GRID_" + phase]):
                raise ValueError("Native AVM explicit grid impedance is incomplete")
    for prefix in ("P", "V"):
        for pole in ("POS", "NEG"):
            if f"{prefix}_pole_ground_{pole}:A" not in nets[prefix + "_DC_" + pole] or f"{prefix}_pole_ground_{pole}:B" not in nets["GND"]:
                raise ValueError("Native AVM symmetric high-impedance grounding is incomplete")
        for phase in "ABC":
            if {
                f"{prefix}_{phase}_UPPER:OUT",
                f"{prefix}_{phase}_LOWER:IN",
                f"{prefix}_valve_current_{phase}:N2",
                f"{prefix}_valve_voltage_{phase}:N1",
                f"{prefix}_valve_ground_{phase}:A",
            } - set(nets[prefix + "_PHASE_" + phase]):
                raise ValueError("Native AVM phase midpoint is incomplete")
            if f"{prefix}_valve_ground_{phase}:B" not in nets["GND"]:
                raise ValueError("Native AVM valve-side common-mode reference is incomplete")
            if {f"{prefix}_breakout:N{'ABC'.index(phase) + 1}", f"{prefix}_valve_current_{phase}:N1"} - set(nets[prefix + "_VALVE_" + phase]):
                raise ValueError("Native AVM valve current measurement path is incomplete")
        if not all(
            f"{prefix}_{phase}_UPPER:IN" in nets[prefix + "_DC_POS"]
            and f"{prefix}_{phase}_LOWER:OUT" in nets[prefix + "_DC_NEG"]
            for phase in "ABC"
        ):
            raise ValueError("Native AVM DC arm polarity is incomplete")
        if {
            f"{prefix}_dc_current:N2",
            f"DC_CABLE:{'SEND_POS' if prefix == 'P' else 'RECV_POS'}",
        } - set(nets[prefix + "_CABLE_POS"]):
            raise ValueError("Native AVM DC current measurement path is incomplete")
        if {
            f"{prefix}_dc_negative_current:N2",
            f"DC_CABLE:{'SEND_NEG' if prefix == 'P' else 'RECV_NEG'}",
        } - set(nets[prefix + "_CABLE_NEG"]):
            raise ValueError("Native AVM negative DC current measurement path is incomplete")
    if set(nets["P_DC_POS"]) & set(nets["P_DC_NEG"]) or set(nets["V_DC_POS"]) & set(
        nets["V_DC_NEG"]
    ):
        raise ValueError("Native AVM DC poles are crossed")
    library = Path(receipt["library"]["library_path"])
    expected_library_sha256 = (
        receipt["library"]["library_sha256"]
        if finalized_library_sha256 is None
        else finalized_library_sha256
    )
    if _hash(library) != expected_library_sha256:
        raise ValueError("Native AVM companion library changed")
    definitions = {
        definition.get("name")
        for definition in ET.parse(library).findall("./definitions/Definition")
    }
    if (
        not {
            "MMCAverageArm",
            "MMCAverageCoupling",
            CONTROL_NAME,
            CLOSED_LOOP_CONTROL_NAME,
            "MMCControlErrors",
            "MMCModulationSynthesis",
            MEASUREMENT_NAME,
            "MMCCableLink",
            "Cable2",
        }
        <= definitions
    ):
        raise ValueError("Native AVM companion definitions are incomplete")
    return {
        "two_stations": True,
        "arm_count": 12,
        "phase_breakout_count": 2,
        "coupled_cable_count": 1,
        "control_kind": receipt["control_kind"],
        "physical_power_control_closed": receipt["control_kind"] == "closed_loop",
    }


__all__ = [
    "CONTROL_DEFAULTS",
    "CONTROL_NAME",
    "CONTROL_OUTPUTS",
    "CLOSED_LOOP_CONTROL_NAME",
    "CLOSED_LOOP_DEFAULTS",
    "FIXTURE_CHANNELS",
    "MEASUREMENT_NAME",
    "NATIVE_SCOPE",
    "audit_native_avm_fixture",
    "materialize_native_avm_fixture",
    "materialize_native_avm_library",
]
