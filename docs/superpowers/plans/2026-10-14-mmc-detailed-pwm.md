# Detailed PWM closure (2026-10-14)

Worktree: `codex/mmc-detailed-pwm`, starting at `a8fce2d`.
The user accepted the proposed detailed PWM work by asking to start. The
overhead-line AVM work belongs to another chat and keeps its own worktree,
PSCAD instance and output directory. This task uses `D:/PA/pwm14`.

Read `docs/acceptance-criteria.md` before interpreting or running acceptance.
The preserved October diagnostic reports `HVDC_MAPPING_MISSING` for the
unbound `reset_command`. Default guessed OnOff/Dblk/fault-option bindings
remain disabled. Original examples, Master, compiler libraries, reports and
electrical thresholds remain immutable.

1. Reproduce and repair reachable arm-rating audit and control/arm frequency
   writes using independent fixtures. Preserve the initial failing regression.
2. Prepare a derived full-bridge PWM case with eight actual command sources,
   routed reset, block, AC/DC isolation and fault branches. Expose actual
   voltage/current/power/capacitor and switch-state measurements. Resolve
   bindings from these verified routes, with declared units and polarity.
3. Bind the requested ratings to controller, converter, grid and line together.
   Refuse unsupported mappings rather than executing a partial rating change.
4. Run cold-start, forward steady, P/Q steps, reversal, reverse steady, both AC
   faults, both DC faults and recovery. Preserve failures and fix their causes.
   Keep all eleven scenario names and original physical requirements.
5. Load the saved model in an independent owned instance and repeat affected
   checks. Freeze source/code/artifact identities and verify owned cleanup.

Offline tests, compile and previously accepted joint-fault outputs cannot
establish acceptance of this new parameterized PWM path. Delivery must state
the exact tested request/revision and any remaining scope or external blocker.
