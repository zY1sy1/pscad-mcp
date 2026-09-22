"""Latched native protection for the normal MMC operating sequence."""

from xml.etree import ElementTree as ET

from .avm_companion import _definition, _script, _PARAMETER_UNITS

PROTECTION_NAME = "MMCNativeProtection"
PROTECTION_INPUTS = ("PRECHARGE_READY", "POWER_READY", "PRECHARGE_FAILED", "CHARGE_FAILED",
                     "P_VDC", "V_VDC", "P_PLL_LOCKED", "V_PLL_LOCKED", "P_LIMIT_ACTIVE", "V_LIMIT_ACTIVE") + tuple(
    f"{s}_{p}_{q}_{n}" for s in ("P", "V") for p in "ABC" for q in ("UPPER", "LOWER") for n in ("I", "VCAP"))
PROTECTION_OUTPUTS = {"TRIP": ("PROTECTION_TRIP", "1"), "CODE": ("PROTECTION_CODE", "1"),
                      "TRIP_TIME": ("PROTECTION_TIME", "s"), "SATURATION_HOLD": ("PROTECTION_SATURATION_HOLD", "s")}
PROTECTION_DEFAULTS = {"Vdc_Order_kV": 640.0, "Frequency_Hz": 60.0, "Arm_Current_Limit_kA": 2.3}


def append_native_protection(root: ET.Element) -> None:
    _PARAMETER_UNITS["Arm_Current_Limit_kA"] = "kA"
    component = _definition(root, PROTECTION_NAME,
        {**{name: (-90, -432 + i * 36, "Transfer", "Input") for i, name in enumerate(PROTECTION_INPUTS)},
         **{name: (90, -54 + i * 36, "Transfer", "Output") for i, name in enumerate(PROTECTION_OUTPUTS)}},
        PROTECTION_DEFAULTS)
    extremes = "".join(f"      IMAX = MAX(IMAX, ABS(${s}_{p}_{q}_I))\n"
                       f"      CMIN = MIN(CMIN, ${s}_{p}_{q}_VCAP)\n"
                       f"      CMAX = MAX(CMAX, ${s}_{p}_{q}_VCAP)\n"
                       for s in ("P", "V") for p in "ABC" for q in ("UPPER", "LOWER"))
    _script(component, "Dsdyn", """#STORAGE REAL:3
#LOCAL REAL IMAX
#LOCAL REAL CMIN
#LOCAL REAL CMAX
#LOCAL INTEGER REASON
      IF (TIMEZERO) THEN
        STORF(NSTORF) = 0.0
        STORF(NSTORF+1) = -1.0
        STORF(NSTORF+2) = 0.0
      ENDIF
      IMAX = 0.0
      CMIN = $Vdc_Order_kV
      CMAX = 0.0
""" + extremes + """      REASON = 0
      IF (IMAX .GT. $Arm_Current_Limit_kA) REASON = REASON + 1
      IF (MAX($P_VDC, $V_VDC) .GT. 1.10 * $Vdc_Order_kV) REASON = REASON + 2
      IF (CMAX .GT. 0.55 * $Vdc_Order_kV) REASON = REASON + 4
      IF ($POWER_READY .GE. 0.5) THEN
        IF (MIN($P_VDC, $V_VDC) .LT. 0.90 * $Vdc_Order_kV) REASON = REASON + 8
        IF (CMIN .LT. 0.45 * $Vdc_Order_kV) REASON = REASON + 16
      ENDIF
      IF ($PRECHARGE_READY .GE. 0.5) THEN
        IF (MIN($P_PLL_LOCKED, $V_PLL_LOCKED) .LT. 0.5) REASON = REASON + 32
        IF (MAX($P_LIMIT_ACTIVE, $V_LIMIT_ACTIVE) .GE. 0.5) THEN
          STORF(NSTORF+2) = STORF(NSTORF+2) + DELT
        ELSE
          STORF(NSTORF+2) = 0.0
        ENDIF
        IF (STORF(NSTORF+2) .GT. 1.0 / $Frequency_Hz) REASON = REASON + 64
      ENDIF
      IF (MAX($PRECHARGE_FAILED, $CHARGE_FAILED) .GE. 0.5) REASON = REASON + 128
      IF (REASON .GT. 0 .AND. STORF(NSTORF) .LT. 0.5) THEN
        STORF(NSTORF) = REASON
        STORF(NSTORF+1) = TIME
      ENDIF
      $TRIP = 0.0
      IF (STORF(NSTORF) .GE. 0.5) $TRIP = 1.0
      $CODE = STORF(NSTORF)
      $TRIP_TIME = STORF(NSTORF+1)
      $SATURATION_HOLD = STORF(NSTORF+2)
      NSTORF = NSTORF + 3
""")
