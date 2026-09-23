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
- [x] Prepare one joint case using the timing adapter on the instrumented model.
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

## Joint Software Harness

`tests/mmc_timing_fault_case.py` prepares a derived-only offline case using the
production public plan, compiler dependencies and line generation, actual
fault binding, explicit T2 charging repair, production fault instrumentation,
then A's embedded control adapter. It consumes the formal A
`docs/acceptance/emt-timed-control/schedule-handoff.json`, freezes the file hash
and canonical parent schedule hash, and requires the original Master, project,
library and compiler-support identities to agree. The parent's target, values
and units are preserved. Its old timing tolerance is not inherited.

The joint schedule declares a T2 active-power command at 1.0-1.2 s, separate
from the physical 2.5-2.7 s fault. It fixes 25 us integration, 250 us output,
5 s duration and 500 us maximum timing error. The combined fault contract is
derived from A's deterministic expected rendering and B's original contract;
it cannot authorize extra physical changes or relabel a fault channel as a
control command. Both adapters require the identical complete OUT/INF/INFX
dataset, and static analysis failures retain a unique JSON report.

Run the offline preparation with a new absolute directory:

```powershell
D:/pscad-mcp/.venv/Scripts/python.exe -m tests.mmc_timing_fault_case --workspace D:/PSCAD-Workspace/mmc-timing-fault-integration/joint-software-<revision>
```

The output scope is `offline_joint_contract`, with
`physical_acceptance_verified: false`. The harness has no licensed-run entry
point. B's accepted `channels-handoff.json`, exact passing model recipe and
fresh original/replay evidence remain mandatory inputs to the future licensed
joint gate. Its current raw offline model does not stand in for B's full
charging/headroom/filter/carrier/virtual-resistance diagnostic chain.

Joint regression coverage reports 16 passed after formal handoff binding.
The preceding affected A/B/public software gate reported 257 passed, 1 skipped;
that gate also has no licensed meaning. Ruff is clean for the joint harness
and tests. Independent review closed all three public replay findings at
`80e9f8706ad0219dc7199b5a44cd653789f0d0ee` with Spec/Quality PASS.

## Durable Offline Case

The joint harness was committed as
`61fd11b0810a3aeb7455dcfaa38a7d7a04c67be2`. Running its preparation CLI produced
`D:/PSCAD-Workspace/mmc-timing-fault-integration/joint-software-61fd11b/preparation.json`.
The scope is `offline_joint_contract`, the static status is `PASS`, and
`physical_acceptance_verified` remains `false`. No PSCAD instance or simulation
was launched. The exact identities are:

- Preparation canonical hash:
  `1bc47f9bfc59e439a8a00717bbbf348b79baeed458fd28bcb5682114bfe87c5d`.
- Derived `JointFaultCase.pscx`:
  `2f71fbc231c1fbb370aa79ab6c802a07335c7130ef69a59a682c7ef5d9e65b8d`.
- Formal A handoff file:
  `e91b009b2a8224e23d4043d0802011d55769436f6d4218bbfa50083bcb1380bb`.
- Formal A canonical schedule:
  `5f799315640b6760c86f345b3ce791d77301ab2b6cc832a96ca25ad036f5e917`.
- New joint canonical schedule:
  `b6b5841a2668e5465ce254cc6de7274bededbd49d91bc0999fcba9abba341d8e`.
- Production fault checks:
  `b7bfa3900a410af5c98f65501e5d3f6e5bad4ff809277156d04e3276c25e0ce1`.

The case has 56 physical/recovery channels, 94 diagnostic channels, one separate
scheduled command channel, and 16 frozen dependency/evidence copies. B's
accepted handoff is explicitly pending. The final affected software command
(joint, timing, public service/tools, replay and production fault contracts)
reports 262 passed, 1 skipped in 51.34 s; Ruff is clean.

For B's public-service intake, the cherry-pick order is `b38a40f`, `64ac799`,
`daee2b1`, `03b5406`, `1e79aed`, `71014e3`, `6e965ef`, `80e9f87`.
The first commit supplies the documentation file edited by later commits.
`6e965ef` requires B's `c5ed2e2` charging helper. Do not cherry-pick integration
merge commits or the joint harness when taking only the public fault service.
B confirmed intake will occur at a safe boundary of its sorting-repair run.

## September 12 Resume

The interrupted work resumed at `f13346b` without reverting its pending edits.
Review found that supplemental replay callbacks could share mutable native
evidence. `598e166` isolates callback inputs, preserves independent native
acceptance/readback/contract copies, and binds both worker and supervisor to
the child worker's actual `evidence/output-index.json` and its original hash.
Post-callback checks revalidate the original model and complete dataset.
Thirty-six replay tests pass, including in-place identity replacement and
contract/context/sample/model/output mutation. Independent Spec/Quality review
closed the finding; no licensed acceptance was inferred.

The explicit `native_full_sort_v1` recipe fixes T2 charging, current headroom
1.1 with freeze tracking, 5 ms DC feedback, T2 carrier ratio 23, 30 ohm common
arm virtual resistance, complete `Dim` sorting under the existing `Enab`, and
instrumentation. Its ordered steps, fixed parameters and model-producer file
hashes are part of the public plan. Public and joint preparation now share one
materialization routine. The default remains `raw`; every recipe still has
`physical_acceptance_verified: false` and fault/recovery pending.

This recipe retains the original T1 Ti=.08. B's subsequent Ti=.04 candidate
must receive a separate explicit recipe after its stable implementation is
provided; it cannot silently change `native_full_sort_v1`. Public/joint
licensed execution remains gated on B's accepted full handoff and exact
recipe. The affected public/joint preparation software gate reports 62 passed,
1 skipped, with Ruff clean.

## Gated Licensed Lifecycle

`tests/mmc_joint_acceptance.py` now provides the separate opt-in lifecycle:
validated B handoff, public builder execution and independent native replay,
public instance cleanup, joint execution in a fresh owned instance, and an
independent joint worker. The fixed joint worker rechecks B's handoff before
launch and evaluates A timing and B fault evidence from the same child
OUT/INF/INFX dataset. B producer provenance and the current public execution
producer are verified separately; B PASS never substitutes for a fresh public
or joint physical result.

The joint context preserves both virtual-root transitions: raw preparation to
the first saved model, then first saved model to the child saved model. Hooks
remain read-only and compare the complete child contract. The first-save
comparison permits only equivalent numeric serialization of the five explicit
simulation settings; different numeric values and controller changes remain
rejected. Native replay still uses the strict saved-model comparison.

Failures before B admission or without `PSCAD_MCP_MMC_ACCEPTANCE=1` construct no
PSCAD service. Public failure prevents joint startup. Unknown replay ownership
or incomplete owned cleanup retains the lease. After closing each owned
instance, the lifecycle revalidates published public evidence and the first
joint model/output identities; quit-time changes cannot produce PASS. An
immutable copy of the first saved joint model is retained as evidence.

The software gate on September 15 reports 174 passed, 1 skipped across the
new lifecycle, joint preparation, native replay, public builder and root-owned
B handoff validation tests. No licensed public/joint run has occurred yet.
The existing B native evidence at
`D:/PSCAD-Workspace/mmc-fault-evidence/fault-evidence-20260912T052440515065Z/acceptance-report.json`
and its final handoff remain distinct from this pending integration acceptance.
The parent task owns `tests/mmc_b_handoff.py` and has independently re-read the
B evidence; this lifecycle consumes that validator's verified context.

Independent review of the first lifecycle revision found cleanup propagation
and finalizer ordering defects. The runner now captures builder status before
and after shutdown even when its task raises or is cancelled, and combines
builder, replay and owned-service cleanup without allowing one to clear the
others. Attach attempts without a returned ownership handle remain uncertain;
unsettled executor calls are retained in both primary and replay workers.
The finalizer first persists a non-PASS checkpoint, releases its lease, restores
the process-local environment, and only then permits a final PASS. Release or
journal I/O failures report FAIL while retaining the actual process-cleanup
facts and any original failure. The focused combined gate reports 203 passed,
1 skipped after these review fixes; actual integration execution is still
pending review closure and licensed opt-in.

## Licensed Public Attempts and Publication Recovery

B's final native handoff was admitted at `f79c265`. Its immutable native
producer is `86adfe0227e5914d01ff07fcad3f742c2aba8e21`, and the accepted
recipe is `native_full_sort_dc_integral_004_v1`. Both original steady windows,
the fault case and electrical recovery passed. The final handoff SHA-256 is
`36c78d3c660a22ebfb05daaba2e4d4d587b64051bf69df3b2e1722f1dc024ccf`.

The subsequent real public attempts remain separate diagnostic evidence:

| Attempt under `D:/PSCAD-Workspace/mmc-timing-fault-integration/` | Result and repair |
| --- | --- |
| `public-joint-20260915-f79c265` | Public physics passed; replay identity rejected a Windows venv child interpreter and vendor save metadata. `198420a` repairs launcher binding and permits only verified nonphysical metadata normalization. |
| `public-joint-20260917-198420a` | Public physics passed; the legacy TLine solver truncated a 217-character input path. `b172f6d` moves replay to a short owned directory and rejects paths over 199 characters before execution. |
| `public-joint-20260917-b172f6d` | Interrupted during preflight, before PSCAD startup; preserved as an unfinished attempt. |
| `public-joint-20260917-b172f6d-r2` | Both public and independent replay physics passed; publication alone failed with WinError 206 while copying into the deeply nested candidate directory. All owned processes closed and leases were released. Joint execution had not started. |

In r2, both datasets contain 312 channels and 51 OUT/INF/INFX files. Each
passed all 122 physical checks. The coordinator journal is
`.pscad-mcp/mmc-builds/c269d4cc96aa40728b996500ee8ad1bd/journal.json`, with
SHA-256 `648c946f3c0f8cfc972161f49778129d277a352a7e637486233edfb339e0be33`.
The public journal is
`public/.pscad-mcp/mmc-builds/2c6e30d4bb404b8aa6a9aa29d16ed6ca/journal.json`,
with SHA-256 `7a0055227da79ed7df55f00bdb86be1047d2de59ec95e83acbf9c766f4a3572f`.

`7cd7cb42217408c45ecc2980cb7a3fde97ee5850` replaces the publication candidate
with a short owned `.pscad-mcp/mmc-publications/<build_id>` directory and
preflights all candidate and final destinations before copying. For r2 the
maximum candidate file/directory lengths fall from 279/262 to 248/231; final
destination lengths are 187/170. The focused software gate passed 195 tests
with 1 skip, and independent review passed the 22 boundary/rejection cases.

Publication-only recovery is being validated separately. It must preserve
the old FAIL journals, old partial candidate, original plan and producer
identities, then revalidate the unchanged datasets and published copy. It may
supersede only the failed publication stage. A new licensed joint run and an
independent joint replay remain required before overall integration PASS.

The original r2 `blank_service.py` raw hash is
`35e78ec157d7af2fe5ecb29bd61caafa7ba69494c361c4e222b0843aeddcc70d`.
Its exact mixed-line-ending bytes were recovered at
`D:/PSCAD-Workspace/mmc-timing-fault-integration/recovered-producer-b172f6d/blank_service.py`.
This is a recovered historical snapshot, not an artifact archived during
the original run. Its raw hash matches the frozen plan, and normalization
to LF matches the `b172f6d` Git blob exactly. Independent review confirmed
the independent file identity, absence of reparse points, and unchanged
original journal hashes.

The recovery/continuation entry points are committed at
`6a2fe24f29ffbaa02cf681a6ad767f3f67b4ca38`. `7838f8a` additionally prevents
joint acceptance PASS when lease release returns `False` without raising.
The combined recovery, continuation and lifecycle software gate passed
99 tests in 19.74 s, with targeted Ruff and diff checks clean. Independent
review accepted the publication-only recovery entry point after a read-only
audit of 282 frozen files, including all 27 files in the failed candidate.

Actual recovery started at 20:23:42 Asia/Shanghai on September 22 in
`D:/PSCAD-Workspace/mmc-publication-recovery-20260922-r1`, from the exact old
coordinator/public journal hashes above. The independent launcher PID was
42848; stdout, stderr and launch provenance are under
`D:/PSCAD-Workspace/mmc-integration-logs/publication-r1.*`.
This entry records startup only; fresh recovery and joint verdicts remain
pending until their durable reports and cleanup are verified.

## Publication Recovery PASS

Recovery completed with a final PASS at
`D:/PSCAD-Workspace/mmc-publication-recovery-20260922-r1/.pscad-mcp/mmc-builds/59d8d98b1fec42a5aa0b870ba1c682a7/journal.json`.
Receipt SHA-256:
`268605847ec6d2b257de39e0b133bc889bdfd55d3800fa1e7359bcde7fe32ede`.
Both old datasets were reread completely; each reproduced 312 channels and
all 122 passing physical checks. The delivered copy passed the actual
publication loader and `validate_model` physical re-evaluation with
`accepted: true`. No PSCAD instance was launched for this recovery.
Both owned workspace leases were released, and there were no finalization
errors. All 282 frozen inputs, including the old journals and 27 partial
publication files, retained their identities.

The delivered project is the original public workspace's
`PublicFault_c269d4cc.pscx`, SHA-256
`907ca7b02153b1a59587aa6234a1375b87432f3ca1924a69e1ed060c78cf21cc`.
The final bundle manifest SHA-256 is
`752ec59e49dbd7a20a1dfb23606e8c0c9b77c2f674cf52295525326b23dc5f2f`.
Only the publication failure is superseded; the original attempts stay FAIL.

The reviewed continuation started a fresh acceptance process at 20:44:39
Asia/Shanghai in `D:/PSCAD-Workspace/mmc-joint-20260922-r1` (launcher PID 47532,
Python PID 52916). Its journal is
`.pscad-mcp/mmc-builds/9d05449d39ac48ada2844f48de0954a0/journal.json`.
It consumes the exact recovery receipt and unchanged B handoff, builds a new
joint preparation with current producer hashes, and reuses the reviewed owned
joint/independent-replay lifecycle. Joint physical acceptance remains pending.

## Joint r1 First-Save Failure and Accepted-Model Derivation

The r1 continuation ended at 21:03:54 with a first-save XML comparison failure,
before build or simulation. The final journal SHA-256 is
`d8f801692ec61175e0279f99dc69b82a310fd5ef30c980ff34a21d60397f8797`.
The owned PSCAD PID 33972 was cleaned; cleanup was not pending and the lease
was released. Parent publication/B evidence validation had completed.

The raw preparation retained an old startup snapshot filename and older
vendor component metadata/defaults. The first save migrated these fields.
The fix does not expand the physical model ignore list. Commit
`330017cf71b5619b9b961d183ef7ee3b54ad9fdb` instead derives the joint case from
the byte-verified published saved model, copying its 15 frozen runtime
dependencies and changing only the two declared local TLine paths before
applying the deterministic A schedule. Parent publication plan/producer
identities, receipt, channel contract, checks, B handoff and source identities
remain explicit and immutable. Current joint derivation code is frozen
separately, and parent physical PASS is not inherited by the new run.

The two planned A components receive verified vendor display metadata on
first save: control owner 450184592 changes width/height and parameter CRC;
PGB owner 2000000000 changes width and gains q=4 and a parameter CRC.
The old Slider panel Control linked to owner 450184592 changes only its Name
from Pref2 to empty. These checks are limited to the declared A nodes;
parameters, scripts, ports, positions, wires and all remaining XML stay under
the full canonical comparison. A read-only comparison of the new seed-derived
model against r1's actual saved model passed after these bounded rules.

The affected joint-seed, continuation, lifecycle and preparation suite passed
88 tests in 43.75 s. Targeted Ruff and diff checks passed. New licensed joint
execution and independent replay are still required; r1 remains failed.

Independent Spec/Quality review of fixed `330017c` passed, including a
write-free real-model comparison and nine rejected mutation cases: command,
position, display quality, malformed CRC, panel label, physical fault setting,
unrelated component size, line-path escape and duplicate event owner.

Fresh joint r2 started at 22:11:58 Asia/Shanghai in
`D:/PSCAD-Workspace/mmc-joint-20260922-r2`, launcher PID 51172 and actual Python
PID 43124. The report is
`.pscad-mcp/mmc-builds/8107d3b43a1c494fa9c20a3925964942/journal.json`.
`D:/PSCAD-Workspace/mmc-integration-logs/joint-r2.launcher.json` binds this
execution to fixed source revision `330017c` and the exact superseded r1
journal SHA. Separate stdout/stderr logs retain startup and final outcomes.
This entry records launch, not physical acceptance completion.

r2 passed the actual first-save and compilation gates, then completed the
first owned joint simulation (PSCAD PID 25872). The shared-dataset analysis
at `joint/joint-analysis/bc916f4809fb45448a7722560dba8df1.json` has SHA-256
`b03bc0115812a1394c063175678f0e7bcca0e8003fab59f5095038c36f6f27db` and verdict
PASS. All 122 physical checks passed, including fault application, all required
negative insertion/blocking evidence, bounded fault current and recovery.
Fault-current peak was 8.2468144896141 kA against the unchanged 20 kA maximum.
The A command edges were exactly 1.0/1.2 s with zero measured error, 800 active
samples and 20001 samples over [0, 5] s.

The first saved joint model SHA-256 is
`dc3f5b8dd35267a19c625b8fde234606bebff04f04bdcce54d820f7428c80e07`.
The fixed independent worker was then launched with request SHA-256
`5c9b523ef1aef995414412885914065df745449f77c7324dfae16ffaa9540d02`
(launcher PID 28972, actual interpreter PID 43220). Its new run and final
owned cleanup remain pending; the first dataset PASS is not the outer final
acceptance verdict.

r2's first joint dataset remains PASS, but the independent worker failed its
saved-model comparison before build/run. Only the two sibling DCTL calls in
`hierarchy/Station/Main` changed order: links 1533195475 and 2005307872 were
swapped as complete entries. No schematic, parameter, connection or other XML
content changed after the existing verified save normalization. The final
r2 journal SHA-256 is
`09081033de02474a322435e3dbffb0e6814f7c2f2552f12aa5422d36b03b55b3`;
the failed child report SHA-256 is
`54a776e7587d187b4eaae85d1c0f7330990aa2c12b4c3e64a2028a62b39ffc5e`.
Both owned PSCAD PIDs 25872 and 32816 exited, no cleanup was pending, and the
outer lease was released. Both failed reports and child saved bytes remain.

The affected repair is hierarchy comparison by unique call identity, retaining
full subtree equality and rejecting missing, added, duplicate or altered calls.
The original integration worktree will remain frozen so its recorded producer
code paths and the completed first-run preparation stay valid; the next fix
will execute from a separate checkout. Only the unfinished independent replay
requires a fresh simulation. Its closure must bind the unchanged first saved
model, full output/index/sample/analysis identities, original failed attempt,
new comparison code and new worker evidence. No old verdict will be rewritten.

Link-aligned inspection refined the diagnosis: swapping the two DCTL calls
also changes their definition-wide `instance` ordinals 0/1. Commit
`4c2a9ae9b9def6624382cf84f078cee4ff4b0ea4` validates complete original DFS
ordinal sequences before sorting unique sibling links and assigning canonical
ordinals. The final whole-XML comparison remains mandatory. An already equal
hierarchy remains untouched. Real r2 saved models now compare equal; illegal
ordinal changes, replaced/duplicated/deleted/added calls, nested changes and
schematic ordering changes are rejected. The affected core/joint gate passed
140 tests in 44.65 s, and independent review passed ten mutation cases.

The old integration checkout is frozen at detached `b7473eb`; its actual raw
native source SHA remains `2e1cd94b2588127520b2d3be167940aa398275c9927f45ff8ac62beb576091bb`.
The integration branch now executes in
`D:/pscad-mcp/.worktrees/mmc-timing-fault-final`. This preserves all recorded
old code paths while allowing a separately identified replay comparator fix.

Commit `6410b5e1b76b38ecec8557554ddedf5b09a8b633` adds the bounded replay-only
recovery runner. It validates 323 retained/current file identities, including
191 current production/worker code files, and permits only the reviewed
native hierarchy helper/call difference against the first-run source revision.
It re-evaluates the hash-bound archived first samples with unchanged checks,
independently rereads timing on the same complete output dataset, then runs
the existing fixed independent replay. It never materializes a new first case
or writes into an old evidence/source tree. The final affected gate passed
187 tests; independent Spec/Quality review passed, including 13 failure and
cleanup protocol cases. A pre-invocation journal failure releases the lease;
unknown post-invocation ownership retains it, and release=False cannot yield PASS.

Actual replay recovery started at 23:45:14 Asia/Shanghai on September 22,
launcher PID 11428 and actual Python PID 51324, at
`D:/PSCAD-Workspace/mmc-joint-replay-20260922-r1`.
Journal: `.pscad-mcp/mmc-builds/99f5b751febe446ab35182a8156b4692/journal.json`.
Separate logs/provenance are under
`D:/PSCAD-Workspace/mmc-integration-logs/joint-replay-r1.*`.
The new replay's final physical/timing verdict and cleanup remain pending.

## Final Joint and Independent Replay Acceptance — September 23

The recovery closed at 00:05:25 Asia/Shanghai with final status PASS and
physical_acceptance_verified=true. Both retained first-run and fresh
independent replay datasets pass all 122 physical checks, and both measure
the A command edges at 1.0/1.2 s with zero error and 800 active samples.
Both fault-current peaks are 8.2468144896141 kA under the unchanged 20 kA
bound. The new dataset contains 51 OUT/INF/INFX files and all 312 physical/
diagnostic channels plus the separately checked command channel.

Final report:
`D:/PSCAD-Workspace/mmc-joint-replay-20260922-r1/.pscad-mcp/mmc-builds/99f5b751febe446ab35182a8156b4692/journal.json`
SHA-256 `285a9af72060b26d9051c609948bcc260bba6f1bd4519fb4302966a3d22c132b`.
The worker report SHA-256 is
`817011332c68a530630b5ec0c5af411ceb26befb22835f330289ace03813926a`;
the supervisor report SHA-256 is
`be54a8bae0808c3c6fddabf20ab60a32cd15927dfa5993301cae9864961eb57a`.
The independent worker copied the exact first saved model (dc3f5b…80e07)
and all 16 declared dependencies, then saved the verified equivalent model
`d4e7e95a0db66bc187fa9205d5b9aaff937ecd3ce7f4bc8b0a94e940f0e1790f`.
Its new request SHA-256 is
`638053f4104a847a854de9e31b50ca3cb80e8c87ce211996a2e7fc043a3f73e0`.

Worker, supervisor and outer report all pass. Worker exit code is 0;
owned_process_cleaned=true, cleanup_pending=false and lease_retained=false,
with no finalization errors. The lock does not exist. Independent process
queries confirmed that PSCAD 41476, worker 47140, worker launcher 50340,
coordinator 51324 and launcher 11428 have exited. The earlier r2 instances
25872 and 32816 had already exited and remain separate failed-attempt history.

Final independent evidence review passed 582 hash references / 469 unique
files, including 323 retained inputs, 145 fresh artifacts and 191 current
code files at execution revision 6410b5e. It rechecked both complete datasets'
identities, sizes, mtimes and run freshness, native saved-model equivalence,
same-dataset timing and all request/context/model/dependency/report bindings.
The old public, joint r1 and joint r2 failure reports retain their hashes and
FAIL verdicts. The old preparation code remains in the frozen detached
integration checkout. This is affected-gate replay recovery, with no stale
plan rewriting or inherited physical PASS for the new worker.

The shared comparator fix was synchronized to B at
`effe98385923ad1c8aed538b00e6494e99cf0e21`, with 77 replay regressions passing
in B's worktree and lint/diff checks clean. A remains at 16c7bf9 with its
accepted independent timing evidence. The two independent tasks, public
publication and combined timing/fault/recovery plus independent replay are
now accepted. Main has not been merged or pushed.

The concise delivery index is [delivery.md](delivery.md) in this final worktree.
