"""Native synchronous-frame PLL and MMC current-control equations."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from .avm_companion import _definition, _script, _PARAMETER_UNITS

PLL_NAME = "MMCSynchronousPLL"
DQ_NAME = "MMCDqCurrentController"
PLL_OUTPUTS = {"ANGLE": ("PLL_ANGLE", "rad"), "FREQUENCY": ("PLL_FREQUENCY", "Hz"),
               "LOCKED": ("PLL_LOCKED", "1"), "ERROR": ("PLL_ERROR", "rad"),
               "INTEGRATOR": ("PLL_INTEGRATOR", "rad/s"), "LIMITED": ("PLL_LIMITED", "1")}
PLL_DEFAULTS = {"Frequency_Hz": 60.0, "Vdc_Order_kV": 640.0, "PLL_Bandwidth_Hz": 10.0,
                "PLL_Damping": 0.707106781186548, "PLL_Frequency_Limit_Hz": 5.0}
DQ_DEFAULTS = {
    "Frequency_Hz": 60.0, "Vdc_Order_kV": 640.0, "P_Order_MW": 1000.0, "Q_Order_MVAr": 0.0,
    "Deblock_Time_s": 0.1, "Ramp_Time_s": 0.2, "Reversal_Time_s": 1.0, "Reversal_Duration_s": 1.0,
    "Control_Mode": 0.0,
    "Startup_Charge_Time_s": 0.5,
    "Recovery_Charge_Time_s": 0.1,
    "DC_Link_Capacitance_F": 0.0,
    "C_eq_F": 6.510416666666667e-5, "L_arm_H": 0.05, "R_arm_ohm": 0.15,
    "P_nonohmic_MW": 1.1, "Kp_Vdc_MW_per_kV": 0.25, "Ti_Vdc_s": 0.1125,
    "Power_Correction_Limit_MW": 1500.0, "Cable_Loss_MW": 0.0, "Converter_Loss_MW": 15.0,
    "Current_Bandwidth_Hz": 80.0, "Current_Damping": 0.707106781186548,
    "Angle_Limit_Deg": 30.0,
    "AC_Current_Limit_kA": 3.0, "Transformer_Leakage_ohm": 16.94,
    "Energy_Gain_per_s": 10.0, "Circulating_Gain_ohm": 18.84955592153876,
    "Circulating_Integral_Time_s": 0.05, "Feedback_Filter_s": 0.02,
    "Energy_Difference_Filter_s": 0.05,
    "Energy_Difference_Gain_per_s": 20.0,
}
ARM_INPUTS = tuple(f"{p}_{q}_{s}" for p in "ABC" for q in ("UPPER", "LOWER") for s in ("VCAP", "I"))
DQ_INPUTS = ("P_MEAS", "Q_MEAS", "VDC_MEAS", "VDC_POS", "VDC_NEG", "PLL_ANGLE", "PLL_LOCKED", "STARTUP_READY", "START_TIME",
             "POWER_READY", "POWER_START", "PROTECTION_TRIP", "RESTART", "RECOVERY_MODE",
             "VA", "VB", "VC", "IA", "IB", "IC", *ARM_INPUTS)
DQ_OUTPUTS = {
    **{f"M_{p}_{q}{suffix}": "1" for p in "ABC" for q in ("UPPER", "LOWER") for suffix in ("", "_RAW")},
    "BLOCK": "1", "SEQUENCE": "1", "ANGLE_COMMAND": "deg", "MODULATION_COMMAND": "1",
    "POWER_CORRECTION": "MW", "P_REFERENCE": "MW", "Q_REFERENCE": "MVAr", "VDC_REFERENCE": "kV",
    **{f"CIRC_{s}_{p}": unit for p in "ABC" for s, unit in (("REFERENCE", "kA"), ("INTEGRATOR", "kV"))},
    "ID_MEASURED": "kA", "IQ_MEASURED": "kA", "ID_REFERENCE": "kA", "IQ_REFERENCE": "kA",
    "VD_MEASURED": "kV", "VQ_MEASURED": "kV", "VD_REFERENCE": "kV", "VQ_REFERENCE": "kV",
    "ID_INTEGRATOR": "kV", "IQ_INTEGRATOR": "kV", "VDC_INTEGRATOR": "MW",
    "MODULATION_UNCLIPPED": "1",
    "ANGLE_UNCLIPPED": "deg",
    "ZERO_SEQUENCE_COMMAND": "kV",
    "CAP_VOLTAGE_REFERENCE": "kV", "CHARGE_POWER_REFERENCE": "MW",
    "DC_CHARGE_POWER_REFERENCE": "MW",
    "POWER_VOLTAGE_BASE": "kV",
    "VALVE_POWER": "MW",
    "LIMIT_ACTIVE": "1", "LIMIT_DURATION": "s",
}


def _ports(inputs, outputs):
    return {**{name: (-108, -432 + 36 * i, "Transfer", "Input") for i, name in enumerate(inputs)},
            **{name: (108, -432 + 36 * i, "Transfer", "Output") for i, name in enumerate(outputs)}}


def append_native_pll_and_dq(root: ET.Element) -> None:
    _PARAMETER_UNITS.update({"PLL_Bandwidth_Hz": "Hz", "PLL_Damping": "1", "PLL_Frequency_Limit_Hz": "Hz",
                             "Current_Bandwidth_Hz": "Hz", "Current_Damping": "1",
                             "AC_Current_Limit_kA": "kA", "Transformer_Leakage_ohm": "ohm"})
    _PARAMETER_UNITS["Angle_Limit_Deg"] = "deg"
    pll = _definition(root, PLL_NAME, _ports(("VA", "VB", "VC", "RESTART"), PLL_OUTPUTS), PLL_DEFAULTS)
    _script(pll, "Dsdyn", """#STORAGE REAL:7
#LOCAL REAL ALPHA
#LOCAL REAL BETA
#LOCAL REAL MAGNITUDE
#LOCAL REAL D
#LOCAL REAL Q
#LOCAL REAL THETA
#LOCAL REAL OMEGA
#LOCAL REAL OMEGA_RAW
#LOCAL REAL KP
#LOCAL REAL KI
#LOCAL REAL LIMIT
      IF (TIMEZERO) THEN
        STORF(NSTORF) = 0.0
        STORF(NSTORF+1) = 0.0
        STORF(NSTORF+2) = 0.0
        STORF(NSTORF+3) = 0.0
        STORF(NSTORF+4) = 0.0
        STORF(NSTORF+5) = 0.0
        STORF(NSTORF+6) = 0.0
      ENDIF
      ALPHA = (2.0 * $VA - $VB - $VC) / 3.0
      BETA = ($VB - $VC) * 0.577350269189626
      MAGNITUDE = SQRT(ALPHA**2 + BETA**2)
! Reacquire a restored voltage on the explicit restart edge. Keeping the
! request high must not repeatedly erase the two-cycle lock qualification.
      IF ($RESTART .GE. 0.5 .AND. STORF(NSTORF+6) .LT. 0.5 .AND. MAGNITUDE .GT. 0.1 * $Vdc_Order_kV) THEN
        STORF(NSTORF+1) = 0.0
        STORF(NSTORF+2) = 0.0
        STORF(NSTORF+3) = 0.0
        STORF(NSTORF+4) = 0.0
        STORF(NSTORF+5) = 0.0
      ENDIF
      STORF(NSTORF+6) = $RESTART
      IF (STORF(NSTORF+3) .LT. 0.5 .AND. MAGNITUDE .GT. 0.1 * $Vdc_Order_kV) THEN
        STORF(NSTORF) = ATAN2(ALPHA, -BETA)
        STORF(NSTORF+3) = 1.0
      ENDIF
      THETA = STORF(NSTORF)
      D = ALPHA * SIN(THETA) - BETA * COS(THETA)
      Q = ALPHA * COS(THETA) + BETA * SIN(THETA)
      $ERROR = 0.0
      $LIMITED = 0.0
      OMEGA = 6.283185307179586 * $Frequency_Hz
      KP = 2.0 * $PLL_Damping * 6.283185307179586 * $PLL_Bandwidth_Hz
      KI = (6.283185307179586 * $PLL_Bandwidth_Hz)**2
      LIMIT = 6.283185307179586 * $PLL_Frequency_Limit_Hz
      IF (MAGNITUDE .GT. 0.1 * $Vdc_Order_kV) THEN
        $ERROR = ATAN2(Q, D)
        OMEGA_RAW = KP * $ERROR + STORF(NSTORF+1)
        IF ((OMEGA_RAW .LT. LIMIT .OR. $ERROR .LT. 0.0) .AND. (OMEGA_RAW .GT. -LIMIT .OR. $ERROR .GT. 0.0)) STORF(NSTORF+1) = MAX(-LIMIT, MIN(LIMIT, STORF(NSTORF+1) + KI * $ERROR * DELT))
        OMEGA_RAW = KP * $ERROR + STORF(NSTORF+1)
        IF (ABS(OMEGA_RAW) .GT. LIMIT) $LIMITED = 1.0
        OMEGA = OMEGA + MAX(-LIMIT, MIN(LIMIT, OMEGA_RAW))
      ELSE
        STORF(NSTORF+1) = 0.0
      ENDIF
      IF (MAGNITUDE .GT. 0.1 * $Vdc_Order_kV .AND. ABS($ERROR) .LT. 0.0349065850398866 .AND. $LIMITED .LT. 0.5) THEN
        STORF(NSTORF+2) = STORF(NSTORF+2) + DELT
      ELSE
        STORF(NSTORF+2) = 0.0
      ENDIF
      IF (STORF(NSTORF+2) .GE. 2.0 / $Frequency_Hz) STORF(NSTORF+4) = 1.0
      IF (MAGNITUDE .LE. 0.1 * $Vdc_Order_kV) THEN
        STORF(NSTORF+4) = 0.0
        STORF(NSTORF+5) = 0.0
      ELSE
        IF (ABS($ERROR) .GT. 0.174532925199433 .OR. $LIMITED .GE. 0.5) THEN
          STORF(NSTORF+5) = STORF(NSTORF+5) + DELT
        ELSE
          STORF(NSTORF+5) = 0.0
        ENDIF
        IF (STORF(NSTORF+5) .GE. 0.5 / $Frequency_Hz) STORF(NSTORF+4) = 0.0
      ENDIF
      $LOCKED = STORF(NSTORF+4)
      $ANGLE = THETA
      $FREQUENCY = OMEGA / 6.283185307179586
      $INTEGRATOR = STORF(NSTORF+1)
      STORF(NSTORF) = MODULO(THETA + DELT * OMEGA, 6.283185307179586)
      NSTORF = NSTORF + 7
""")
    dq = _definition(root, DQ_NAME, _ports(DQ_INPUTS, DQ_OUTPUTS), DQ_DEFAULTS, signed_parameters=("Q_Order_MVAr",))
    _script(dq, "Dsdyn", _dq_script())


def _dq_script() -> str:
    text = """#STORAGE REAL:23
#LOCAL INTEGER K
#LOCAL REAL A
#LOCAL REAL VA
#LOCAL REAL VB
#LOCAL REAL IA
#LOCAL REAL IB
#LOCAL REAL VD
#LOCAL REAL VQ
#LOCAL REAL ID
#LOCAL REAL IQ
#LOCAL REAL THETA
#LOCAL REAL OMEGA
#LOCAL REAL SCALE
#LOCAL REAL PREF
#LOCAL REAL QREF
#LOCAL REAL REVERSE_START
#LOCAL REAL VERR
#LOCAL REAL PCORR
#LOCAL REAL PLOSS
#LOCAL REAL IDREF
#LOCAL REAL IQREF
#LOCAL REAL IMAG
#LOCAL REAL KP
#LOCAL REAL KI
#LOCAL REAL ED
#LOCAL REAL EQ
#LOCAL REAL VDREF
#LOCAL REAL VQREF
#LOCAL REAL VALPHA
#LOCAL REAL VBETA
#LOCAL REAL VZERO
#LOCAL REAL VPHASE_A
#LOCAL REAL VPHASE_B
#LOCAL REAL VPHASE_C
#LOCAL REAL VACOM
#LOCAL REAL ISUM
#LOCAL REAL IREF
#LOCAL REAL IERR
#LOCAL REAL VCOMMON
#LOCAL REAL VMIN
#LOCAL REAL VMAX
#LOCAL REAL WSUM
#LOCAL REAL WDIFF
#LOCAL REAL WREF
#LOCAL REAL VBASE
#LOCAL REAL PVALVE
#LOCAL REAL VMID
#LOCAL REAL VCAP_START
#LOCAL REAL VCAP_REFERENCE
#LOCAL REAL VCAP_RATE
#LOCAL REAL CHARGE_SCALE
#LOCAL REAL CHARGE_POWER
#LOCAL REAL CHARGE_DURATION
#LOCAL REAL VDC_RATE
#LOCAL REAL ANGLE_LIMIT
#LOCAL REAL ANGLE_RAW
#LOCAL REAL VMAG
#LOCAL REAL WREF_RATE
      IF (TIMEZERO .OR. $RESTART .GE. 0.5) THEN
        DO K = 0, 22
          STORF(NSTORF+K) = 0.0
        ENDDO
      ENDIF
      THETA = $PLL_ANGLE
      OMEGA = 6.283185307179586 * $Frequency_Hz
      VA = (2.0 * $VA - $VB - $VC) / 3.0
      VB = ($VB - $VC) * 0.577350269189626
      IA = (2.0 * $IA - $IB - $IC) / 3.0
      IB = ($IB - $IC) * 0.577350269189626
      VD = VA * SIN(THETA) - VB * COS(THETA)
      VQ = VA * COS(THETA) + VB * SIN(THETA)
      ID = IA * SIN(THETA) - IB * COS(THETA)
      IQ = IA * COS(THETA) + IB * SIN(THETA)
      VMID = 0.5 * ($VDC_POS + $VDC_NEG)
      PVALVE = ($VA - VMID) * ($A_LOWER_I - $A_UPPER_I) + ($VB - VMID) * ($B_LOWER_I - $B_UPPER_I) + ($VC - VMID) * ($C_LOWER_I - $C_UPPER_I)
      $VALVE_POWER = PVALVE
! A controller reset does not empty physical capacitors. Seed observers from
! their measured states so deblocking cannot request fictitious recharge.
      IF ($RESTART .GE. 0.5) THEN
        STORF(NSTORF+1) = $VDC_MEAS
        STORF(NSTORF+2) = $P_MEAS
        STORF(NSTORF+3) = $Q_MEAS
        STORF(NSTORF+22) = VD
        STORF(NSTORF+8) = 0.5 * $C_eq_F * ($A_UPPER_VCAP**2 + $A_LOWER_VCAP**2)
        STORF(NSTORF+9) = 0.5 * $C_eq_F * ($B_UPPER_VCAP**2 + $B_LOWER_VCAP**2)
        STORF(NSTORF+10) = 0.5 * $C_eq_F * ($C_UPPER_VCAP**2 + $C_LOWER_VCAP**2)
        STORF(NSTORF+11) = 0.5 * $C_eq_F * ($A_UPPER_VCAP**2 - $A_LOWER_VCAP**2)
        STORF(NSTORF+12) = 0.5 * $C_eq_F * ($B_UPPER_VCAP**2 - $B_LOWER_VCAP**2)
        STORF(NSTORF+13) = 0.5 * $C_eq_F * ($C_UPPER_VCAP**2 - $C_LOWER_VCAP**2)
      ENDIF
      A = 1.0 - EXP(-DELT / $Feedback_Filter_s)
! Power-to-current normalization must not feed instantaneous PCC voltage
! changes back into current demand through the network/interface dynamics.
! Raw VD/VQ remain available to the inner-loop voltage feedforward below.
      STORF(NSTORF+22) = STORF(NSTORF+22) + A * (VD - STORF(NSTORF+22))
      VBASE = MAX(0.1 * $Vdc_Order_kV, STORF(NSTORF+22))
      $POWER_VOLTAGE_BASE = VBASE
      STORF(NSTORF+1) = STORF(NSTORF+1) + A * ($VDC_MEAS - STORF(NSTORF+1))
      STORF(NSTORF+2) = STORF(NSTORF+2) + A * ($P_MEAS - STORF(NSTORF+2))
      STORF(NSTORF+3) = STORF(NSTORF+3) + A * ($Q_MEAS - STORF(NSTORF+3))
      $BLOCK = 1.0
      IF ($STARTUP_READY .GE. 0.5 .AND. $PLL_LOCKED .GE. 0.5 .AND. $PROTECTION_TRIP .LT. 0.5) $BLOCK = 0.0
      VCAP_START = ($A_UPPER_VCAP + $A_LOWER_VCAP + $B_UPPER_VCAP + $B_LOWER_VCAP + $C_UPPER_VCAP + $C_LOWER_VCAP) / 3.0
      IF ($STARTUP_READY .GE. 0.5 .AND. STORF(NSTORF+21) .LT. 0.5) THEN
        STORF(NSTORF+19) = VCAP_START
        STORF(NSTORF+20) = $VDC_MEAS
        STORF(NSTORF+21) = 1.0
      ENDIF
      CHARGE_SCALE = 0.0
      VCAP_RATE = 0.0
      CHARGE_DURATION = $Startup_Charge_Time_s
      IF ($RECOVERY_MODE .GE. 0.5) CHARGE_DURATION = $Recovery_Charge_Time_s
      IF ($STARTUP_READY .GE. 0.5) THEN
        CHARGE_SCALE = MIN(1.0, MAX(0.0, (TIME - $START_TIME) / CHARGE_DURATION))
        IF (CHARGE_SCALE .LT. 1.0) VCAP_RATE = ($Vdc_Order_kV - STORF(NSTORF+19)) / CHARGE_DURATION
      ENDIF
      VCAP_REFERENCE = STORF(NSTORF+19) + CHARGE_SCALE * ($Vdc_Order_kV - STORF(NSTORF+19))
      CHARGE_POWER = 1.5 * $C_eq_F * VCAP_REFERENCE * VCAP_RATE
      WREF_RATE = 0.5 * $C_eq_F * VCAP_REFERENCE * VCAP_RATE
      $CAP_VOLTAGE_REFERENCE = VCAP_REFERENCE
      $CHARGE_POWER_REFERENCE = CHARGE_POWER
      SCALE = 0.0
      IF ($POWER_READY .GE. 0.5) SCALE = MIN(1.0, MAX(0.0, (TIME - $POWER_START) / $Ramp_Time_s))
      PREF = SCALE * $P_Order_MW
      IF ($RECOVERY_MODE .GE. 0.5) PREF = -PREF
      QREF = SCALE * $Q_Order_MVAr
      $SEQUENCE = 1.0
      IF ($STARTUP_READY .GE. 0.5) $SEQUENCE = 4.0
      IF ($POWER_READY .GE. 0.5) $SEQUENCE = 2.0
      IF ($POWER_READY .GE. 0.5 .AND. $RECOVERY_MODE .GE. 0.5) $SEQUENCE = 3.0
      REVERSE_START = $POWER_START + $Reversal_Time_s - $Deblock_Time_s
      IF ($POWER_READY .GE. 0.5 .AND. TIME .GE. REVERSE_START .AND. $RECOVERY_MODE .LT. 0.5) THEN
        PREF = $P_Order_MW * (1.0 - 2.0 * MIN(1.0, (TIME - REVERSE_START) / $Reversal_Duration_s))
        $SEQUENCE = 3.0
      ENDIF
      $VDC_REFERENCE = STORF(NSTORF+20) + CHARGE_SCALE * ($Vdc_Order_kV - STORF(NSTORF+20))
! The cable energy ramp is a known demand. Its feedforward must stop with
! the reference ramp; raw DC feedback avoids retaining the ramp's filter lag.
      VDC_RATE = 0.0
      IF ($STARTUP_READY .GE. 0.5 .AND. CHARGE_SCALE .LT. 1.0) VDC_RATE = ($Vdc_Order_kV - STORF(NSTORF+20)) / CHARGE_DURATION
      $DC_CHARGE_POWER_REFERENCE = 0.0
      IF ($Control_Mode .GE. 0.5 .AND. $BLOCK .LT. 0.5) $DC_CHARGE_POWER_REFERENCE = $DC_Link_Capacitance_F * $VDC_REFERENCE * VDC_RATE
      VERR = $VDC_REFERENCE - $VDC_MEAS
      IF ($Control_Mode .LT. 0.5) VERR = 0.0
      PCORR = $Kp_Vdc_MW_per_kV * VERR + STORF(NSTORF)
      IF ($BLOCK .LT. 0.5 .AND. STORF(NSTORF+18) .LT. 0.5) THEN
        IF ((PCORR .LT. $Power_Correction_Limit_MW .OR. VERR .LT. 0.0) .AND. (PCORR .GT. -$Power_Correction_Limit_MW .OR. VERR .GT. 0.0)) STORF(NSTORF) = STORF(NSTORF) + DELT * $Kp_Vdc_MW_per_kV * VERR / $Ti_Vdc_s
      ELSEIF ($BLOCK .GE. 0.5) THEN
        STORF(NSTORF) = 0.0
      ENDIF
      $POWER_CORRECTION = MAX(-$Power_Correction_Limit_MW, MIN($Power_Correction_Limit_MW, $Kp_Vdc_MW_per_kV * VERR + STORF(NSTORF)))
      IF ($Control_Mode .GE. 0.5) PREF = -PREF + $POWER_CORRECTION + $Converter_Loss_MW + $Cable_Loss_MW * (PREF / $P_Order_MW)**2
      PREF = PREF + CHARGE_POWER + $DC_CHARGE_POWER_REFERENCE
      IF ($PROTECTION_TRIP .GE. 0.5) THEN
        PREF = 0.0
        QREF = 0.0
        $SEQUENCE = 5.0
      ENDIF
      $P_REFERENCE = PREF
      $Q_REFERENCE = QREF
      PLOSS = 1.5 * $Transformer_Leakage_ohm * (ID**2 + IQ**2)
      IF ($BLOCK .LT. 0.5 .AND. STORF(NSTORF+18) .LT. 0.5) THEN
        STORF(NSTORF+4) = MAX(-0.2 * $P_Order_MW, MIN(0.2 * $P_Order_MW, STORF(NSTORF+4) + DELT * 2.0 * (PREF - $P_MEAS)))
        STORF(NSTORF+5) = MAX(-0.5 * $P_Order_MW, MIN(0.5 * $P_Order_MW, STORF(NSTORF+5) + DELT * 2.0 * (STORF(NSTORF+3) - QREF)))
      ELSEIF ($BLOCK .GE. 0.5) THEN
        STORF(NSTORF+4) = 0.0
        STORF(NSTORF+5) = 0.0
      ENDIF
      IDREF = (PREF + 0.1 * (PREF - $P_MEAS) + STORF(NSTORF+4)) / (1.5 * VBASE)
      IQREF = -(QREF - PLOSS - 0.1 * (STORF(NSTORF+3) - QREF) - STORF(NSTORF+5)) / (1.5 * VBASE)
      IMAG = SQRT(IDREF**2 + IQREF**2)
      $LIMIT_ACTIVE = 0.0
      IF (IMAG .GT. $AC_Current_Limit_kA) THEN
        IDREF = IDREF * $AC_Current_Limit_kA / IMAG
        IQREF = IQREF * $AC_Current_Limit_kA / IMAG
        $LIMIT_ACTIVE = 1.0
      ENDIF
      IF ($BLOCK .GE. 0.5) THEN
        IDREF = 0.0
        IQREF = 0.0
      ENDIF
      ED = ID - IDREF
      EQ = IQ - IQREF
      KP = $Current_Damping * $L_arm_H * 6.283185307179586 * $Current_Bandwidth_Hz
      KI = 0.5 * $L_arm_H * (6.283185307179586 * $Current_Bandwidth_Hz)**2
      IF ($BLOCK .LT. 0.5) THEN
        IF ($LIMIT_ACTIVE .LT. 0.5 .AND. STORF(NSTORF+18) .LT. 0.5) THEN
          STORF(NSTORF+6) = MAX(-0.5 * $Vdc_Order_kV, MIN(0.5 * $Vdc_Order_kV, STORF(NSTORF+6) + DELT * KI * ED))
          STORF(NSTORF+7) = MAX(-0.5 * $Vdc_Order_kV, MIN(0.5 * $Vdc_Order_kV, STORF(NSTORF+7) + DELT * KI * EQ))
        ENDIF
      ELSE
        STORF(NSTORF+6) = 0.0
        STORF(NSTORF+7) = 0.0
      ENDIF
      VDREF = VD - 0.5 * $R_arm_ohm * ID + 0.5 * OMEGA * $L_arm_H * IQ + KP * ED + STORF(NSTORF+6)
      VQREF = VQ - 0.5 * $R_arm_ohm * IQ - 0.5 * OMEGA * $L_arm_H * ID + KP * EQ + STORF(NSTORF+7)
      ANGLE_RAW = MODULO(ATAN2(VQREF, VDREF) + 2.0 * OMEGA * DELT + 3.141592653589793, 6.283185307179586) - 3.141592653589793
      $ANGLE_UNCLIPPED = ANGLE_RAW * 57.2957795130823
      ANGLE_LIMIT = $Angle_Limit_Deg / 57.2957795130823
      IF ($BLOCK .LT. 0.5 .AND. ABS(ANGLE_RAW) .GT. ANGLE_LIMIT) THEN
        VMAG = SQRT(VDREF**2 + VQREF**2)
        ANGLE_RAW = MAX(-ANGLE_LIMIT, MIN(ANGLE_LIMIT, ANGLE_RAW)) - 2.0 * OMEGA * DELT
        VDREF = VMAG * COS(ANGLE_RAW)
        VQREF = VMAG * SIN(ANGLE_RAW)
        $LIMIT_ACTIVE = 1.0
      ENDIF
      $MODULATION_UNCLIPPED = 2.0 * SQRT(VDREF**2 + VQREF**2) / $Vdc_Order_kV
      IF ($MODULATION_UNCLIPPED .GT. 0.98) THEN
        VDREF = VDREF * 0.98 / $MODULATION_UNCLIPPED
        VQREF = VQREF * 0.98 / $MODULATION_UNCLIPPED
        $LIMIT_ACTIVE = 1.0
      ENDIF
! Native module and voltage-source interfaces apply this command two steps
! after its network measurements. Advance the synthesis frame, not the
! measurement frame, to compensate that physical carrier-phase delay.
      VALPHA = VDREF * SIN(THETA + 2.0 * OMEGA * DELT) + VQREF * COS(THETA + 2.0 * OMEGA * DELT)
      VBETA = -VDREF * COS(THETA + 2.0 * OMEGA * DELT) + VQREF * SIN(THETA + 2.0 * OMEGA * DELT)
      VPHASE_A = VALPHA
      VPHASE_B = -0.5 * VALPHA + 0.866025403784439 * VBETA
      VPHASE_C = -0.5 * VALPHA - 0.866025403784439 * VBETA
      VZERO = -0.5 * (MAX(VPHASE_A, VPHASE_B, VPHASE_C) + MIN(VPHASE_A, VPHASE_B, VPHASE_C))
      $ZERO_SEQUENCE_COMMAND = VZERO
      $ANGLE_COMMAND = MODULO((ATAN2(VQREF, VDREF) + 2.0 * OMEGA * DELT) * 57.2957795130823 + 180.0, 360.0) - 180.0
      $MODULATION_COMMAND = 2.0 * SQRT(VDREF**2 + VQREF**2) / $Vdc_Order_kV
      WREF = 0.25 * $C_eq_F * VCAP_REFERENCE**2
"""
    for i, phase in enumerate("ABC"):
        ac = f"VPHASE_{phase} + VZERO"
        text += f"""      WSUM = 0.5 * $C_eq_F * (${phase}_UPPER_VCAP**2 + ${phase}_LOWER_VCAP**2)
      WDIFF = 0.5 * $C_eq_F * (${phase}_UPPER_VCAP**2 - ${phase}_LOWER_VCAP**2)
      STORF(NSTORF+{8+i}) = STORF(NSTORF+{8+i}) + A * (WSUM - STORF(NSTORF+{8+i}))
      STORF(NSTORF+{11+i}) = STORF(NSTORF+{11+i}) + (1.0 - EXP(-DELT / $Energy_Difference_Filter_s)) * (WDIFF - STORF(NSTORF+{11+i}))
      VACOM = {ac}
      ISUM = 0.5 * (${phase}_UPPER_I + ${phase}_LOWER_I)
      PLOSS = 2.0 * $P_nonohmic_MW + $R_arm_ohm * (${phase}_UPPER_I**2 + ${phase}_LOWER_I**2)
      IREF = (PLOSS - PVALVE / 3.0 + WREF_RATE - $Energy_Gain_per_s * (STORF(NSTORF+{8+i}) - WREF)) / MAX(0.1 * $Vdc_Order_kV, $VDC_MEAS)
! The circulating PI has about 0.5 in-phase gain at the AC fundamental.
! A 20/s difference gain therefore gives roughly 10/s mean-energy response;
! the 50 ms observer gives an averaged damping ratio of about 0.707.
      IREF = IREF + $Energy_Difference_Gain_per_s * STORF(NSTORF+{11+i}) * VACOM / MAX(1.0, VDREF**2 + VQREF**2)
      IERR = ISUM - IREF
      IF ($BLOCK .GE. 0.5) STORF(NSTORF+{14+i}) = 0.0
      VCOMMON = 0.5 * $VDC_MEAS - $R_arm_ohm * IREF + $Circulating_Gain_ohm * IERR + STORF(NSTORF+{14+i})
      VMIN = ABS(VACOM)
      VMAX = MIN(2.0 * ${phase}_UPPER_VCAP + VACOM, 2.0 * ${phase}_LOWER_VCAP - VACOM)
      IF ($BLOCK .LT. 0.5 .AND. VMAX .GE. VMIN) THEN
        IF ((VCOMMON .LT. VMAX .OR. IERR .LT. 0.0) .AND. (VCOMMON .GT. VMIN .OR. IERR .GT. 0.0)) STORF(NSTORF+{14+i}) = MAX(-0.5 * $Vdc_Order_kV, MIN(0.5 * $Vdc_Order_kV, STORF(NSTORF+{14+i}) + DELT * $Circulating_Gain_ohm * IERR / $Circulating_Integral_Time_s))
      ENDIF
      VCOMMON = 0.5 * $VDC_MEAS - $R_arm_ohm * IREF + $Circulating_Gain_ohm * IERR + STORF(NSTORF+{14+i})
      $M_{phase}_UPPER_RAW = (VCOMMON - VACOM) / MAX(0.1 * $Vdc_Order_kV, 2.0 * ${phase}_UPPER_VCAP)
      $M_{phase}_LOWER_RAW = (VCOMMON + VACOM) / MAX(0.1 * $Vdc_Order_kV, 2.0 * ${phase}_LOWER_VCAP)
      $M_{phase}_UPPER = MIN(1.0, MAX(0.0, $M_{phase}_UPPER_RAW))
      $M_{phase}_LOWER = MIN(1.0, MAX(0.0, $M_{phase}_LOWER_RAW))
      IF (MIN($M_{phase}_UPPER_RAW, $M_{phase}_LOWER_RAW) .LT. 0.0 .OR. MAX($M_{phase}_UPPER_RAW, $M_{phase}_LOWER_RAW) .GT. 1.0) $LIMIT_ACTIVE = 1.0
      $CIRC_REFERENCE_{phase} = IREF
      $CIRC_INTEGRATOR_{phase} = STORF(NSTORF+{14+i})
"""
    return text + """      IF ($BLOCK .GE. 0.5) $LIMIT_ACTIVE = 0.0
      IF ($LIMIT_ACTIVE .GE. 0.5) STORF(NSTORF+17) = STORF(NSTORF+17) + DELT
      $LIMIT_DURATION = STORF(NSTORF+17)
      $ID_MEASURED = ID
      $IQ_MEASURED = IQ
      $ID_REFERENCE = IDREF
      $IQ_REFERENCE = IQREF
      $VD_MEASURED = VD
      $VQ_MEASURED = VQ
      $VD_REFERENCE = VDREF
      $VQ_REFERENCE = VQREF
      $ID_INTEGRATOR = STORF(NSTORF+6)
      $IQ_INTEGRATOR = STORF(NSTORF+7)
      $VDC_INTEGRATOR = STORF(NSTORF)
      STORF(NSTORF+18) = $LIMIT_ACTIVE
      NSTORF = NSTORF + 23
"""
