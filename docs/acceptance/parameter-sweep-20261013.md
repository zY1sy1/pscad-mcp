# Parameter-sweep licensed acceptance

The vdiv serial three-scenario workflow passed fresh licensed PSCAD 4.6.2 x64
acceptance at `a2aaa33d4188486680d8ae7aa043177c07eeb748`. The working tree was
clean. GFortran 4.2.1 compiled each normal case from its independent project copy.

This result covers explicit planning/creation, serial execution, verified
parameter read-back/restoration, continuation after a deliberate invalid
parameter, OUT/INF collection and statistics. Static evaluation of those finalized
outputs also passed baseline comparison and constrained selection. Cancellation,
restart recovery and PSOUT have offline coverage only. `model_accepted=false`:
this is workflow evidence, not electrical-model or whole-project acceptance.

## Observed result

| Scenario | Result | Owned PSCAD PID | Samples per channel |
| --- | --- | --- | --- |
| baseline_R1, R=1 ohm | succeeded | 43740 | 801 |
| deliberate_failure, nonexistent parameter | expected `SWEEP_PARAMETER_INVALID` | 31268 | none |
| load_R2, R=2 ohm | succeeded after the failure | 29032 | 801 |

The authoritative PIDs are the vendor-returned identities in the attempt
reports; the table must match those identities. Two channels span 0..0.2 s.
All 42 acceptance checks passed, including independent recalculation of eight
statistics for each normal-case channel. All 14 baseline comparisons passed a
separate arithmetic consistency check. With voltage peak constrained to <=70 kV,
maximizing voltage RMS selects load_R2: 47.110565092353184 kV versus
35.3329238192649 kV for the baseline. Selection is limited to evaluated scenarios.

The original source, prepared source, reviewed request and installed Master
retain their hashes. All three recorded managed PIDs exited. A separate process
inspection found no running executable from this campaign's attempt directories.
No external instance was controlled or terminated.

## Durable evidence

Campaign: `D:/PSCAD-Workspace/parameter-sweep-20261013/.pscad-mcp/sweeps/sweep-eb2a1fb64b3542f99124b84e7c06c2c2`.

- `licensed-acceptance.json`: the 42-check verdict and explicit scope.
- `manifest.json`, `checkpoint.json`, `report.json`: source/plan hashes,
  checkpoints and verified result references.
- `attempts/*/attempt-1/result.json` and `outputs/`: owned process identities,
  parameter snapshots, terminal results, metadata and copied waveforms.
- `D:/PSCAD-Workspace/parameter-sweep-20261013/verification/licensed-run04-before.json`
  and `licensed-run04-after.json`: exact revision, clean-tree state and input hashes.
- `licensed-analysis-audit.json` in that verification directory: baseline
  comparisons, constrained ranking, report hash and executable-process check.

## Failed attempts and repairs

All failing reports and original artifacts remain in their own campaign folders.
No failed check was removed, no threshold was lowered, and no old verdict was
promoted to PASS.

| Attempt | Tested revision | Reproduced cause and repair |
| --- | --- | --- |
| run01, sweep-19ea32c156384623a2915bf9ee1d4ad9 | ed6beff | SDK imports replace the controller factory with a module, breaking second-instance discovery; fixed at d88fd53. Repeated native canvas inventory fails while direct queries remain valid; verify targeted live locations, and report rejected inventory explicitly, fixed at b23b123. |
| run02, sweep-2f51947395ac45fcad19241acdaf2b1d | b23b123 | Owned-copy save calls omitted the service's required confirmation; the behavioral fake now enforces that gate and confirmed saves propagate correctly, fixed at 191ee35. |
| run03, sweep-28554cc781554db299e7773fb20c0705 | 191ee35 | Native OUT starts with a description line; reuse the existing strict header reader while still rejecting malformed numeric rows, fixed at a2aaa33. |
| run04, sweep-eb2a1fb64b3542f99124b84e7c06c2c2 | a2aaa33 | Fresh run PASS, superseding the earlier attempts only within the stated scope. |

Focused regressions first reproduced each implementation defect and then passed.
The final complete offline suite passed 4023 tests with 54 opt-in skips; those
skips are not licensed evidence. Changed/new workflow checks, compileall,
dependency checks, Git whitespace checks, wheel building and isolated installed
tool/asset/plan/creation probing passed. Full and sweep inventories are 112 and
8 tools respectively (the latter includes capability discovery).

Verification files and artifact hashes are recorded in
`D:/PSCAD-Workspace/parameter-sweep-20261013/verification/verification-final.json`.
