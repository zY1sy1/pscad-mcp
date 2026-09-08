# MMC Fault Evidence Execution

- Branch: `codex/mmc-fault-evidence`
- Baseline: `45069e213fb4f4895599d5269711c57b409db33f`
- Interpreter: `D:/pscad-mcp/.venv/Scripts/python.exe`
- Working directory: `D:/pscad-mcp/.worktrees/mmc-fault-evidence`
- Baseline command: `python -m pytest tests/test_mmc_template_native.py tests/test_mmc_template_audit.py tests/test_blank_mmc_service.py tests/test_mmc_acceptance.py tests/test_output_discovery.py tests/test_hvdc_vsc_mmc_profiles.py -q`
- Observed: `45 passed, 2 skipped in 1.62s`; concurrent-support ancestor check exited 0.

## Checklist

- [x] Read acceptance rules and verify isolated baseline.
- [x] Run and record focused baseline.
- [x] Locate official full-bridge cells and actual fault switch implementation.
- [x] Freeze reachable-instance channel and physical contracts.
- [x] Instrument derived copies and verify save/reload identity.
- [x] Implement strict identity, metadata, time, units and physical evaluation.
- [ ] Run licensed steady state and fault/recovery cases with owned process cleanup.
- [ ] Independently recalculate evidence and freeze channel handoff.
- [ ] Integrate the final A schedule contract and rerun affected acceptance.

## Pre-Run Engineering Criteria

These are new case-specific engineering criteria, not an existing vendor
full-bridge certification specification. The existing fault-current upper bound
of 20 kA is retained. The official 640 kV DC and -900 MW terminal-2 setpoints
define the nonzero operating point. Recovery compares stable complete-cycle
windows before and after the event: DC voltage and active power within 5%, arm
RMS current within 10%, and summed capacitor voltage within 5%. A measured
pre-fault operating point below 90% of the declared voltage or power magnitude
cannot serve as a recovery reference. Voltage and power mean must have the
declared signs. Mean-normalized RMS variation is bounded by 5% for DC voltage
and power; arm RMS is checked on equal-duration windows covering whole 60 Hz
cycles. Independent cycle RMS variation is bounded by 5%. Voltage and terminal-2
controlled power must also be within 5% of their declared nominal reference;
the 90% floor alone is insufficient. These strengthened criteria were fixed
before the third attempt.

Every arm must demonstrate physical negative terminal voltage below -1 kV
during the fault window and physical firing-based blocking, followed by
unblocking throughout the electrical recovery window. The -1 kV threshold is
well above numerical roundoff and below one nominal cell's voltage (640/76 kV).
Actual fault switch state is taken from OPENBR, not the protection pulse named
`Fault mode` or the scheduled fault command.

## Source Findings

The original project SHA-256 is
`1900be93877400fba228b1808a5310980d801b0260d7df998df6c5a2f6a035dd`;
the original companion library SHA-256 is
`08466778704e547d7d9d80af99a48c09292dd3a51056ac26216c3913d5cc3a1b`.
Main reaches two MMC_Hb_PWM instances and three pole instances in each, hence
twelve arms. Shared Definition owner IDs alone identify only prototypes.
FullCellR_n uses DTBP=0 and FiringHBridge. Its external Ntop/Nbtm electrical
ports are valid terminal-voltage sources; its a/b nodes are internal and
conditional. Vc is a 76-element submodule capacitor-voltage vector.

The installed master:fault_sw exposes actual branch current as Iflt but exposes
OPENBR state only to animation. A derived-only clone can append an output for
that exact state while preserving the original electrical implementation.
The project's timer DF is 0.01 s, while the old materializer writes only the
unrelated forwarded FltDur parameter. This discrepancy requires an explicit
timer binding and waveform verification.

## Licensed Diagnostic Attempts

- `fault-evidence-20260908T034450263758Z`: owned PID 20540, licensed startup
  succeeded. First save reallocated the virtual Station document-root link;
  the original strict identity check stopped before compilation. Cleanup passed.
- `fault-evidence-20260908T034749658223Z`: both copies loaded, saved, compiled,
  simulated and produced all 56 required physical channels. No missing channel
  or invalid time/unit evidence. The actual fault lasted from 2.50025 to
  2.51275 seconds, confirming both the unrelated FltDur binding and the
  current-zero-only clearing behavior. Each of twelve arms showed physical
  negative Ntop-minus-Nbtm voltage during the fault and physical blocking.
  The 20 kA fault-current check passed. Nominal operating point and recovery
  failed. All owned processes exited and original inputs remained immutable.

The common Ntop-minus-Nbtm polarity is retained for every cell group; all source
cell instances have orient=0, and positive insertion is the normal series arm
voltage drop in that port direction. The negative-insertion check requires
each arm to demonstrate the opposite terminal polarity at some instant during
the applied fault, not all arms at the same instant. It does not infer passive
blocking merely from current direction or normalize a waveform's sign after
observing it.

## Bounded Control Diagnosis

The original model reaches 625-629 kV early, then falls under the unchanged
900 MW transfer target. The saved native controller outputs show T1 current
reference near its 1 pu limit. Source and generated code also show a separate
hard-coded antiwindup comparator threshold 0.99999; increasing only Imax would
leave the PI frozen. The old output named Reset is a different constant signal
and is not evidence that the actual FrzI signal is inactive.

The third attempt changes only T1 Imax from 1 to 1.05 pu and replaces the
antiwindup constant with an input-connected gain of 0.99999 times the actual
Imax. Both PI saturation and freeze remain enabled. T2 stays at 1 pu. The
unchanged 1000 MVA/370 kV bases give phase current base 1.560406 kA RMS and
2.206748 kA peak; 1.05 pu gives 1.638426 kA RMS and 2.317086 kA peak. At
900 MW/640 kV, the DC arm-current contribution is 0.46875 kA; the AC half-current
peak is 1.158543 kA, before adding observed circulating current. This is a
bounded controller-headroom experiment, not a relaxed physical current limit.
All twelve measured arm peaks remain subject to the existing 3 kA protection.
Actual FrzI and limited Imag are newly instrumented per terminal. Generated
Fortran must confirm that freeze tracks Imax before the run starts.

The native finite-duration fault now binds the real timer DF and selects the
terminal-2 P-N fault branch. Its clearing mode removes the externally imposed
fault at the programmed EMT time. This is explicitly different from a model
of a current-zero-only breaker; its OPENBR output still proves actual removal.
Fault window remains 2.5-2.7 s; pre-fault 2.0-2.4 s and recovery 4.6-5.0 s each
cover 24 complete cycles at the template's declared 60 Hz frequency.
