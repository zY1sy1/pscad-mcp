# Native MMC Fault Timing And Physical Probes

The remaining parallel signal audit and acceptance preparation are delivered,
and reproducible native timing, channel-selection and output-reader defects
have been repaired. A fresh independently owned PSCAD run passed the scoped
`native_mmc_fault_schedule_and_physical_probes` checks on code revision
`2876c48c50489b26c8ef13ad9f6e9e2ed68288c7`.

This result is **not overall MMC model acceptance**. The report explicitly
retains `model_accepted=false`. Gate-input release is not a substitute for
quantitative voltage, power and current recovery checks or independent golden
comparison.

## Delivered Work

| Work | Durable result |
| --- | --- |
| Master-reference pre-audit | [Historical inventory and mapping candidates](../audits/2026-09-08-mmc-master-offline/README.md), collected at `d226c2d` |
| Native signal audit | [177-channel source/owner/instance audit](../audits/2026-09-08-mmc-native-followup/README.md), including both paired source profiles |
| Acceptance preparation | [Three feasible requests, six rejection guards and 66 scenario recommendations](../audits/2026-09-08-mmc-native-followup/acceptance-matrix.json) |
| Runtime timing and evaluator | `b800d1a`: bind actual Main timer duration; validate polarity, units, selectors and physical epsilon |
| Physical probes | `173c497`: measured cell-stack and DC terminal voltages, real capacitor arrays, fault command/current and firing-block inputs; validate source pairing and route contacts |
| Independent runner | `3add7bd`, corrected by `2876c48`: owned-PID lifecycle, fresh artifacts, one-pass OUT reading and complete INF/INFX identities |

The unitless historical channels remain unchanged. Newly generated probes have
explicit units and traceable physical or control-input sources. Existing
capacitor sums and modulation orders are not substituted for measured inserted
voltage.

## Fresh Licensed Result

Report:

`D:/PSCAD-Workspace/mmc-native-probe-closure-20260908/mmc-native-probe-20260908T043758259583Z-a79738/report.json`

Report SHA-256:

`d919b2c17d4c37b2f5ff015479203356c94367d2a5b855ba5bc6e2bb8a6b7dae`

| Check | Observed |
| --- | --- |
| Runtime | Licensed PSCAD 4.6.2 x64, Legacy managed launch |
| Owned PID | `38320`; cleaned normally, no cleanup errors |
| Concurrent policy | Process-local opt-in; no attachment to or termination of foreign instances |
| Fault requested | 0.8 to 1.0 s |
| Fault measured | 0.8 to 1.00025 s |
| Measured duration | 0.20025 s, within the 0.0005 s sampling tolerance |
| Fault-current peak | 14.908119440333 kA, below the unchanged 20 kA bound |
| Arm terminal voltage | All 12 arms contain values below -1e-9 kV during the fault |
| Firing-block inputs | All 12 assert during the fault and release afterwards |
| Blocking times | 0.805 / 0.8065 s |
| Release times | 1.055 / 1.0565 s |
| Output evidence | 112 OUT parts plus INF/INFX; 940 physical probe traces |
| Capacitor evidence | All 912 per-cell traces present and finite |
| Sample evidence | 8001 points per trace over 0 to 2 s, with 250 us sampling |
| Immutability | Recorded source inputs, code and finalized outputs retained their hashes |

Inserted voltage preserves `Ntop minus Nbtm` polarity. Blocking observations
are the actual `FiringHBridge.Block` inputs; they do not claim that every
internal semiconductor-state detector was exported.

The chosen source pair is the separately archived reference under
`D:/pscad-mcp-official-examples-20260829/mmc-4.6.2/`. Its library namespace is
`VSC_MMC_Lib`, despite the filename `intermediate.pslx`, and its library XML
version is 4.6.1. Its exact port layout and paired project were audited before
use with PSCAD 4.6.2. The installed ModelsInProgress pair has a different
library API and geometry and was not mixed with this run.

## Failure Resolution

The first attempt at `3add7bd` completed compilation and simulation but stopped
in output reading at call ID 248. PSCAD appended `_1` in the INF description
while INFX kept the prototype name and encoded the complete nested instance
path. The reader incorrectly required those two names to be equal.

The failing report was preserved:

`D:/PSCAD-Workspace/mmc-native-probe-closure-20260908/mmc-native-probe-20260908T042623533803Z-be7b57/report.json`

Its recorded hash before and after offline reanalysis is
`c8ac8c4bcfd45d069b3dbc7320f15acb2c5cbdf94434effcaf0570e562f1fe89`.
It remains `FAIL`; it was not rewritten into a passing result. Owned PID
`35592` exited normally, and the inputs and outputs were retained.

The correction was reproduced in a regression fixture, implemented and tested.
The immutable output was then re-evaluated into a separate analysis record.
Finally, the full licensed run was repeated at `2876c48`, producing the fresh
passing report above. The scope never treated a reader defect as a license or
electrical failure.

## Verification

- Final full offline suite at `2876c48`: **2482 passed, 48 skipped** in 51.62 s.
- Focused final native/probe/runner checks and Ruff passed.
- Independent evidence audit verified 377 distinct recorded hash paths:
  11 immutable inputs, 184 code files and 182 generated artifacts.
- A separate strict raw-data pass reproduced all 940 probe traces, the
  measured fault edges, current maximum, twelve arm results and capacitor
  vector completeness. Both the successful and historical failing report
  hashes matched their recorded values.
- A final process check found neither PID `38320` nor any process whose
  executable was inside the successful run directory.

Independent audit:

`D:/PSCAD-Workspace/mmc-native-probe-closure-20260908/mmc-native-probe-20260908T043758259583Z-a79738/independent-evidence-audit-20260908T044907007848Z.json`

Audit SHA-256:

`ec8c3fbc645025e5cede4859f4bc51ede73a656235774368cf61814f4e948dc1`

Later documentation-only commits record this result without changing the
runtime code or model exercised by the named report.

## Reproduction

From this branch's worktree, use a new timestamped run under the isolated root:

```powershell
$env:PSCAD_MCP_ACCEPTANCE = '1'
$env:PSCAD_MCP_ACCEPTANCE_CONCURRENT = '1'
try {
    & 'D:\pscad-mcp\.venv\Scripts\python.exe' scripts/run_mmc_native_probe_acceptance.py --workspace-root 'D:\PSCAD-Workspace\mmc-native-probe-closure-20260908' --template 'D:\pscad-mcp-official-examples-20260829\mmc-4.6.2\H_MMC_Mono_DC.pscx' --library 'D:\pscad-mcp-official-examples-20260829\mmc-4.6.2\intermediate.pslx'
} finally {
    Remove-Item Env:PSCAD_MCP_ACCEPTANCE -ErrorAction SilentlyContinue
    Remove-Item Env:PSCAD_MCP_ACCEPTANCE_CONCURRENT -ErrorAction SilentlyContinue
}
```

Opt-ins apply only to this process environment. Each invocation uses new
projects, an independent connection and its own evidence directory. Both failed
and successful runs retain their complete artifacts and cleanup records.

## Remaining Model Scope

The following is not certified by this probe run:

- Normal steady-state power transfer and the quantitative DC-voltage,
  arm-current, capacitor-ripple and postfault recovery contracts.
- The complete steady/reversal/fault matrix and rating-specific runs.
- Physical fixed/parametric MMC construction, its unresolved Master/catalog
  and companion implementation, and the full-bridge parametric path.
- Independent reviewed reference waveforms, golden comparisons and release
  acceptance. Reference identity, source/output hashes and reviewer approval
  must come from the WP6 reference workflow.

These are separate implementation/model and reference requirements. They are
not described as license contention or silently marked PASS. The program
baseline, final `accepted` state, main checkout, installation and publication
were not changed by this work.

The independent branch `codex/mmc-master-offline-audit` is retained for
integration. The subsequently prepared main-workspace plans for EMTDC timed
control and MMC fault evidence can consume these code revisions and source
manifests; their shared production-path and full-criteria work is not silently
replaced by this standalone diagnostic runner.
