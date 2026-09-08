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
- [ ] Review current public request, planning, execution and publication flow.
- [ ] Bind source XML, Master, all compiler support files, settings, actual fault
  window, check contract and selected model recipe before mutation.
- [ ] Reject requests that cannot cover required windows before building.
- [ ] Connect production instrumentation and contract evaluation to the actual
  `BlankMmcBuilderService` flow, with focused failing regressions first.
- [ ] Preserve original sources and use exclusive derived files. Keep file
  paths separate from loaded PSCAD names and verify save/readback identity.
- [ ] Freeze output and channel-contract identities before reading; preserve
  failures and all relevant OUT/INF/INFX evidence without publication on FAIL
  or incomplete analysis.
- [ ] On success publish the actual tested model and fault scenario, companion
  and required compiler/line dependencies. Do not copy a fault-free base and
  label it the tested fault scenario.
- [ ] Verify reload in an independent owned worker when the vendor has no
  unload API. Public builder operations must not quit unrelated sessions.
- [ ] Run public-service tests and commit a fault-branch-compatible integration.
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
