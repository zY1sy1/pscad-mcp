# Native overhead-line MMC AVM

User requested implementation on 2026-10-14 after selecting this next scope.
Work is isolated on `codex/mmc-overhead-avm` from `a8fce2d`.

At the start, the request parser supported `overhead_line`, but the public
native AVM engine rejected it and its producer, loss planning and receipt
assumed a coax cable.

1. Reproduce that rejection with a public-planner regression.
2. Audit the installed two-conductor DCTL geometry. Generate fresh native
   frequency-dependent phase constants for the requested total length, bind
   immutable inputs and validate coefficient, fitting and output evidence.
3. Connect a four-terminal overhead module using verified Master interfaces.
   Preserve the existing converter, control, protection and physical criteria.
4. Route public planning and execution by the requested medium. Use actual
   bundle DC resistance without rating scaling and native phase capacitance.
5. Verify focused regressions, source immutability, portable constants and
   clean frozen revisions. Run the opt-in normal/four-fault/independent-reload
   suite on a 200 km, 640 kV, 1000 MW, 60 Hz full-bridge request, then the
   matching 500 kV/750 MW/+100 MVAr and 800 kV/1200 MW/−120 MVAr/50 Hz matrix.
6. Record exact accepted requests, revisions and reports. Preserve earlier
   failures and keep electrical scope boundaries explicit.

PSCAD 5.x, detailed PWM, arbitrary tower geometries, intrinsic blocking without
external isolation, device stress and individual cell balance are outside
this task. Existing license opt-ins and physical thresholds remain required.

## Completed implementation and verification

The public-planner rejection was reproduced before implementation. Commits
`01966e0` and `7900ff2` add audited geometry, native phase constants with two
delay groups, request-aware source discovery, physical bundle resistance and
the four-terminal overhead module. Licensed compilation then exposed two
interface defects: canonical saved XML metadata (`5f33b7d`) and separate
endpoint arrangement (`Mode=0`, `22150e9`). Both were repaired under the
existing strict semantic comparison.

Startup waveforms exposed excessive common-mode voltage. Four actual series
RC branches fixed the damping (`047b609`). The first bank size delayed DC
fault reset; its physical capacitance was halved in `7432030` to preserve
the original reset/recovery window. No acceptance thresholds, protection
logic or deadlines were relaxed. Parallel EMTDC runs subsequently exposed
a communication-port collision; the final suites were run serially.

All three exact requests passed normal operation, four faults and independent
portable reload at frozen runtime commit
`743203006a60333c02dfdd13216cd13756f68f84`: 18 stages, three accepted models.
The final read-only audit verified 557 files and 1898 checks per suite,
including stored physical verdicts, source/producer/output hashes, strict
executable relinking and cleanup of each owned PID. Earlier failures and
the separate audit-script relink mistake remain preserved.

The final runtime revision passed the broad MMC regression (1345 passed,
7 skipped, 2839 deselected), affected tests (49 passed), package build and
isolated installed-package planning. Changed-file Ruff comparison against
`a8fce2d` found no new issues. Detailed evidence, requests, suite hashes and
portable project links are in
[the acceptance record](../../acceptance/mmc-overhead-avm-20261014.md).

Closeout updates the documentation and status assertions separately from the
tested runtime. The three overhead subscopes are explicit, historical cable
records retain their tested commits, and broad `parametric_mmc` remains
`PARTIAL`. This work stays on the local feature branch; no merge or push is
performed.

Closeout manifest/auditor/documentation checks passed (24 tests); the updated
inventory assertion file passes Ruff. Full inventory integrity has no invalid
evidence; its two existing missing-report scopes remain unchanged. All three
new overhead records verify, and the 22 other historical scope records are
identical to the baseline.
