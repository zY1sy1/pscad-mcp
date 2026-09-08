# MMC Timing and Fault Integration

## Scope and Baseline

This work connects the two user-authorized implementation branches. It does
not promote the current MMC diagnostic model to physical acceptance.

- Worktree: `D:/pscad-mcp/.worktrees/mmc-timing-fault-integration`.
- Branch: `codex/mmc-timing-fault-integration`.
- Integration baseline: `c90fd87d2147575df598560eb0c9e54590cc729e`.
- Timing branch input: `16c7bf948bdd9724283478f2a66ae5bf097a188d`.
- Timing production and licensed revision: `216c18ba187f0b86194c4f91dfd3c19d1b281714`.
- Fault branch input: `9451bfa0ffad113c5fdceda53141a3eb60c782c6`.
- Cross-module baseline: 136 passed, 1 skipped in 13.21 s.
- Interpreter: `D:/pscad-mcp/.venv/Scripts/python.exe`.

Read `AGENTS.md` and `docs/acceptance-criteria.md` before execution. The main
checkout and the two feature worktrees are separate from this worktree.

## Ownership

The timing worker now owns the public-service integration here:

- `pscad_mcp/hvdc/builders/mmc/blank_service.py`.
- `tests/test_blank_mmc_service.py` and directly affected public-builder tests.
- A dedicated joint timing/fault integration test and this execution record.

The fault worker retains `fault_channels.py`, `template_native.py`, MMC
`acceptance.py`, model diagnostics and their tests on its feature branch.
Share stable commits for these dependencies; do not edit the same helper in
both worktrees. Coordinate additional request/tool schema changes with root.

Make the public blank-service change a self-contained commit that the fault
branch can cherry-pick without importing the timing branch's new modules.
Keep the subsequent joint timing test in a separate commit.

## Production Contracts

Use the production `fault_channels.default_fault_checks()`, not a function
imported from `tests`. At the current baseline it fixes 5 s duration, 25 us
integration, 250 us output, a 2.5-2.7 s fault, 2.0-2.4 s pre-fault and
4.6-5.0 s recovery windows, plus the documented physical limits.

Available fault-worker APIs include:

- `materialize_template_native_scenario` for actual timer/branch bindings.
- `materialize_voltage_control_headroom` for the audited nominal controller.
- `materialize_dc_feedback_filter` for the isolated DC error-feedback branch.
- `instrument_fault_channels` for channels and readback contracts.
- `finalize_fault_instrumentation` for one verified vendor root remap and
  freezing the saved project identity.
- `verify_fault_instrumentation`, `snapshot_output_dataset`,
  `verify_output_dataset`, and `read_fault_output_dataset`.
- `evaluate_template_native_dc_fault` with explicit channel/check contracts.

The fault worker is still diagnosing the model. Its headroom, filter, carrier
and possible later damping variants are recipes for declared cases, not proof
of physical stability. Record the selected recipe in the immutable plan; do
not silently change it or the physical criteria using observed samples.

## Execution Checklist

- [x] Create isolated integration worktree and merge committed foundations.
- [x] Verify cross-module baseline without licensed runs.
- [x] Review current public request, planning, execution and publication flow.
- [x] Bind source XML, Master, all compiler support files, settings, actual fault
  window, check contract and selected model recipe before mutation.
- [x] Reject requests that cannot cover required windows before building.
- [x] Connect production instrumentation and contract evaluation to the actual
  `BlankMmcBuilderService` flow, with focused failing regressions first.
- [x] Preserve original sources and use exclusive derived files. Keep file
  paths separate from loaded PSCAD names and verify save/readback identity.
- [x] Freeze output and channel-contract identities before reading; preserve
  failures and all relevant OUT/INF/INFX evidence without publication on FAIL
  or incomplete analysis.
- [x] On success publish the actual tested model and fault scenario, companion
  and required compiler/line dependencies. Do not copy a fault-free base and
  label it the tested fault scenario.
- [x] Implement reload verification in an independent owned worker when the vendor has no
  unload API. Public builder operations must not quit unrelated sessions.
- [x] Run public-service tests and commit a fault-branch-compatible integration.
- [ ] Prepare one joint case using the timing adapter on the instrumented model.
  Control-command events and physical `fault_active` remain distinct roles.
- [ ] Bind the original sources, each derived stage, joint schedule/check
  hashes, runtime identities and complete output set in the joint report.
- [ ] Once the fault model is physically ready, run the joint gate on its final
  code/model. Use appropriate predeclared sampling and timing tolerance; do not
  reuse a 10 us timing contract for a 250 us output dataset without a new plan.
- [ ] Obtain independent review, rerun affected checks after fixes, and report
  exact accepted scope and any pending work. Do not merge into main here.

## Runtime Isolation

Use `D:/PSCAD-Workspace/mmc-timing-fault-integration` with a unique directory
per attempt, existing licensed opt-ins and process-local concurrent mode.
Every worker owns its Python process, PSCAD connection and managed PID.
Cleanup must retain pending-owned handles after attach failures, must not
create a session to discover ownership, and must never stop another task's
instance. Follow the acceptance criteria when a run is unsuccessful.

## Public Planning Batch

Focused baseline: 83 passed, 1 skipped in 11.73 s. The first new planning
regressions failed in 9 cases, demonstrating the old 1.3 s/50 us defaults,
unbounded recipe/threshold fields, missing checks contracts and trusted stale
audit hashes. After the planning change, blank-service/tool tests report
26 passed, 1 skipped in 1.10 s.

The existing request `parameterization` carries only `master_path` and a named
`model_recipe`. Supported initial recipes are `raw`, `headroom_1p1`, and
`headroom_1p1_dc_filter_5ms`; every recipe is explicitly physically unverified.
Default raw does not apply diagnostic tuning. Production checks are copied
from `fault_channels.default_fault_checks()` and hashed independently.

The plan pins Master/project/library identities, audited compiler-support
files, and public TLine generator/input hashes when DCTL lines are present.
An explicit longer run retains its duration without changing the fixed
physical check windows; an explicit run shorter than 5 s is rejected before
mutation. Runtime Master verification and the complete execution/publication
flow are the next batch, so this batch alone is not physical acceptance.

## Public Execution Software Gate

The public flow now materializes the fixed fault, applies only the selected
recipe, instruments the derived case, verifies runtime namespaces and settings,
freezes the saved channel contract, and evaluates the complete frozen output
set against the production checks. It retains failure history and output
evidence. The runtime Master identity API (`1e79aed`) reads the connected
installation without changing LCC binding registries.

Publication requires a completed independent worker report, matching project,
dependency and contract lineage, and verified owned cleanup. The fresh worker
copies only frozen compiler dependencies, excluding prior compiler caches. Its
first save permits only the verified virtual document-root rebind; other XML
changes fail before compilation. A separate publication candidate contains the
tested project bytes, complete original and replay evidence, compiler inputs,
relative output index, and a manifest covering every bundle file. The first
tested project and bundle remain unchanged.

Validation requires frozen publication evidence before reading output and
reevaluates with the fixed checks. Half-bridge structural compatibility remains
separate from physical acceptance: intrinsic DC blocking is explicitly
`NOT_APPLICABLE`. Missing output contracts remain `INCOMPLETE_ANALYSIS`, and
structural results without output remain physically unevaluated. Unsettled
owned vendor operations and unconfirmed project containment retain the lease.

Software verification for this batch: 180 passed, 1 skipped across public
service/tools, replay protocol, Master/service/LCC inventory and production MMC
fault-channel/template-native tests. Ruff reports no remaining findings. These
are software and synthetic protocol checks, not licensed electrical acceptance.
No licensed integration run has occurred. B's current model remains physically
unaccepted; joint execution must wait for its accepted final inputs.

B's stable `c5ed2e2` was merged after the public execution checkpoint. The
public plan now declares the verified Main/606940312 charging-delay correction
from `Tcharging1` to `Tcharging2` in `model_corrections`; every recipe records
that exact derived stage before instrumentation. `raw` still applies no
headroom, filter, carrier or damping tuning and remains physically unverified.
The affected public service/tool/replay software gate reports 64 passed,
1 skipped after this integration.

Independent review of `71014e3` identified three software defects: replay did
not rehash its copied dependencies after execution, pipe/finalization errors
could escape before recording unresolved ownership, and direct
`Path.is_junction()` calls required Python 3.12 despite the declared 3.10 floor.
Fresh failing regressions reproduced each defect. Replay now records actual
dependency hashes at save/build/run/cleanup checkpoints and the supervisor
independently hashes the copied compiler inputs. Public execution persists
pending replay ownership before awaiting the worker. Communication, process
termination, log and report-write errors retain their cleanup state and block
publication. Reparse rejection uses the repository's compatible `lstat`
pattern. The focused public/replay/tool/Master gate reports 77 passed,
1 skipped, with Ruff clean after these fixes. Licensed acceptance remains
pending and is not inferred from these software results.
