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
- [ ] Freeze reachable-instance channel and physical contracts.
- [ ] Instrument derived copies and verify save/reload identity.
- [ ] Implement strict identity, metadata, time, units and physical evaluation.
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
cycles. These criteria are frozen before waveform inspection.

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
