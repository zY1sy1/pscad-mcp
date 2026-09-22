"""Latched native protection for the normal MMC operating sequence."""

from xml.etree import ElementTree as ET

from .avm_companion import _definition, _script, _PARAMETER_UNITS

PROTECTION_NAME = "MMCNativeProtection"
PROTECTION_INPUTS = ("PRECHARGE_READY", "POWER_READY", "PRECHARGE_FAILED", "CHARGE_FAILED", "RESTART",
                     "FAULT_ACTIVE", "P_IDC", "V_IDC",
                     "P_VDC", "V_VDC", "P_PLL_LOCKED", "V_PLL_LOCKED", "P_LIMIT_ACTIVE", "V_LIMIT_ACTIVE") + tuple(
    f"{s}_V_{p}" for s in ("P", "V") for p in "ABC") + tuple(
    f"{s}_CABLE_{n}" for s in ("P", "V") for n in ("VDC", "VPOS", "VNEG")) + tuple(
    f"{s}_{p}_{q}_{n}" for s in ("P", "V") for p in "ABC" for q in ("UPPER", "LOWER") for n in ("I", "VCAP"))
PROTECTION_OUTPUTS = {"TRIP": ("PROTECTION_TRIP", "1"), "CODE": ("PROTECTION_CODE", "1"),
                      "TRIP_TIME": ("PROTECTION_TIME", "s"), "SATURATION_HOLD": ("PROTECTION_SATURATION_HOLD", "s"),
                      "RESET_ACK": ("PROTECTION_RESET_ACK", "1")}
PROTECTION_OUTPUTS["AC_MIN_PU"] = ("PROTECTION_AC_MIN_PU", "1")
PROTECTION_OUTPUTS.update({f"{s}_{n}": (f"FAULT_{s}_{n}", unit) for s in ("P", "V")
                           for n, unit in (("ARM_PEAK", "kA"), ("DC_PEAK", "kA"), ("CAP_MIN", "kV"), ("CAP_MAX", "kV"))})
PROTECTION_DEFAULTS = {"Vdc_Order_kV": 640.0, "Frequency_Hz": 60.0, "Arm_Current_Limit_kA": 2.3,
                       "P_AC_Voltage_kV": 230.0, "V_AC_Voltage_kV": 230.0}


def append_native_protection(root: ET.Element) -> None:
    _PARAMETER_UNITS["Arm_Current_Limit_kA"] = "kA"
    _PARAMETER_UNITS.update({"P_AC_Voltage_kV": "kV", "V_AC_Voltage_kV": "kV"})
    component = _definition(root, PROTECTION_NAME,
        {**{name: (-90, -432 + i * 36, "Transfer", "Input") for i, name in enumerate(PROTECTION_INPUTS)},
         **{name: (90, -54 + i * 36, "Transfer", "Output") for i, name in enumerate(PROTECTION_OUTPUTS)}},
        PROTECTION_DEFAULTS)
    extremes = "".join(f"      IMAX = MAX(IMAX, ABS(${s}_{p}_{q}_I))\n"
                       f"      CMIN = MIN(CMIN, ${s}_{p}_{q}_VCAP)\n"
                       f"      CMAX = MAX(CMAX, ${s}_{p}_{q}_VCAP)\n"
                       for s in ("P", "V") for p in "ABC" for q in ("UPPER", "LOWER"))
    peak_update = ""
    for index, station in enumerate(("P", "V")):
        offset = 5 + 4 * index
        for phase in "ABC":
            for position in ("UPPER", "LOWER"):
                prefix = f"{station}_{phase}_{position}"
                peak_update += f"      STORF(NSTORF+{offset}) = MAX(STORF(NSTORF+{offset}), ABS(${prefix}_I))\n"
                peak_update += f"      STORF(NSTORF+{offset+2}) = MIN(STORF(NSTORF+{offset+2}), ${prefix}_VCAP)\n"
                peak_update += f"      STORF(NSTORF+{offset+3}) = MAX(STORF(NSTORF+{offset+3}), ${prefix}_VCAP)\n"
        peak_update += f"      STORF(NSTORF+{offset+1}) = MAX(STORF(NSTORF+{offset+1}), ABS(${station}_IDC))\n"
    peak_exports = "".join(f"      ${s}_{n} = STORF(NSTORF+{5+4*j+k})\n" for j, s in enumerate(("P", "V"))
                           for k, n in enumerate(("ARM_PEAK", "DC_PEAK", "CAP_MIN", "CAP_MAX")))
    voltage_envelope = "      $AC_MIN_PU = 1.0E6\n"
    for i, (station, phase) in enumerate((s, p) for s in ("P", "V") for p in "ABC"):
        signal = f"${station}_V_{phase}"
        voltage_envelope += f"      DERIVATIVE = ({signal} - STORF(NSTORF+{13+i})) / (6.283185307179586 * $Frequency_Hz * DELT)\n"
        voltage_envelope += f"      $AC_MIN_PU = MIN($AC_MIN_PU, SQRT({signal}**2 + DERIVATIVE**2) / (0.816496580927726 * ${station}_AC_Voltage_kV))\n"
        voltage_envelope += f"      STORF(NSTORF+{13+i}) = {signal}\n"
    _script(component, "Dsdyn", """#STORAGE REAL:19
#LOCAL REAL IMAX
#LOCAL REAL CMIN
#LOCAL REAL CMAX
#LOCAL INTEGER REASON
#LOCAL INTEGER K
#LOCAL REAL DERIVATIVE
      IF (TIMEZERO) THEN
        STORF(NSTORF) = 0.0
        STORF(NSTORF+1) = -1.0
        STORF(NSTORF+2) = 0.0
        STORF(NSTORF+3) = 0.0
        DO K = 4, 18
          STORF(NSTORF+K) = 0.0
        ENDDO
        STORF(NSTORF+7) = $Vdc_Order_kV
        STORF(NSTORF+11) = $Vdc_Order_kV
      ENDIF
      IMAX = 0.0
      CMIN = $Vdc_Order_kV
      CMAX = 0.0
""" + extremes + voltage_envelope + """      IF ($FAULT_ACTIVE .GE. 0.5) STORF(NSTORF+4) = 1.0
! Peak evidence is accumulated on every EMTDC step, including steps between
! OUT samples. A controller restart does not erase this fault evidence.
      IF (STORF(NSTORF+4) .GE. 0.5) THEN
""" + peak_update + """      ENDIF
      REASON = 0
      IF (IMAX .GT. $Arm_Current_Limit_kA) REASON = REASON + 1
      IF (MAX($P_VDC, $V_VDC) .GT. 1.10 * $Vdc_Order_kV) REASON = REASON + 2
      IF (CMAX .GT. 0.55 * $Vdc_Order_kV) REASON = REASON + 4
      IF ($POWER_READY .GE. 0.5) THEN
        IF (MIN($P_VDC, $V_VDC) .LT. 0.90 * $Vdc_Order_kV) REASON = REASON + 8
        IF (CMIN .LT. 0.45 * $Vdc_Order_kV) REASON = REASON + 16
        IF (MAX(ABS($P_CABLE_VPOS + $P_CABLE_VNEG), ABS($V_CABLE_VPOS + $V_CABLE_VNEG)) .GT. 0.01 * $Vdc_Order_kV) REASON = REASON + 256
        IF (MIN($P_CABLE_VDC, $V_CABLE_VDC) .LT. 0.90 * $Vdc_Order_kV) REASON = REASON + 512
      ENDIF
      IF ($PRECHARGE_READY .GE. 0.5) THEN
        IF ($AC_MIN_PU .LT. 0.2) REASON = REASON + 1024
        IF (MIN($P_PLL_LOCKED, $V_PLL_LOCKED) .LT. 0.5) REASON = REASON + 32
        IF (MAX($P_LIMIT_ACTIVE, $V_LIMIT_ACTIVE) .GE. 0.5) THEN
          STORF(NSTORF+2) = STORF(NSTORF+2) + DELT
        ELSE
          STORF(NSTORF+2) = 0.0
        ENDIF
        IF (STORF(NSTORF+2) .GT. 1.0 / $Frequency_Hz) REASON = REASON + 64
      ENDIF
      IF (MAX($PRECHARGE_FAILED, $CHARGE_FAILED) .GE. 0.5) REASON = REASON + 128
! Reset is an explicit scenario command. Readiness is rebuilt separately;
! a reset request cannot bypass live electrical limits or an unlocked PLL.
      IF ($RESTART .GE. 0.5 .AND. STORF(NSTORF) .GE. 0.5) THEN
        IF (REASON .EQ. 0 .AND. $AC_MIN_PU .GE. 0.8 .AND. IMAX .LE. 0.1 * $Arm_Current_Limit_kA .AND. MIN($P_PLL_LOCKED, $V_PLL_LOCKED) .GE. 0.5 .AND. CMIN .GE. 0.325 * $Vdc_Order_kV .AND. MIN($P_VDC, $V_VDC, $P_CABLE_VDC, $V_CABLE_VDC) .GE. 0.65 * $Vdc_Order_kV) THEN
          STORF(NSTORF) = 0.0
          STORF(NSTORF+2) = 0.0
          STORF(NSTORF+3) = 1.0
        ENDIF
      ENDIF
      IF (REASON .GT. 0 .AND. STORF(NSTORF) .LT. 0.5) THEN
        STORF(NSTORF) = REASON
        IF (STORF(NSTORF+1) .LT. 0.0) STORF(NSTORF+1) = TIME
      ENDIF
      $TRIP = 0.0
      IF (STORF(NSTORF) .GE. 0.5) $TRIP = 1.0
      $CODE = STORF(NSTORF)
      $TRIP_TIME = STORF(NSTORF+1)
      $SATURATION_HOLD = STORF(NSTORF+2)
      $RESET_ACK = STORF(NSTORF+3)
""" + peak_exports + "      NSTORF = NSTORF + 19\n")
