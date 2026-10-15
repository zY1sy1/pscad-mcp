# Main integration status (2026-10-14)

Historical snapshot. The [October 15 integration](current-status-20261015.md)
adds qualified detailed PWM and overhead AVM and records the already-merged
sweep cancellation/recovery evidence. The pending statements below describe
this earlier snapshot only.

The current useful changes from `codex/acceptance-oct09` (`045968b`) and
`codex/parameter-sweep-workflow` (`3114e10`) are integrated. The merge is clean;
both histories and their precise acceptance revisions remain intact. The local
skill description and previously untracked energy optimizer are also committed.

## Included behavior

- Seven durable sweep tools, independent owned instances, cancel/resume,
  verified output statistics, baseline comparison and constrained ranking.
- Legacy controller discovery after SDK module imports, direct verified
  component queries, owned workspace reload, saved-source inventory and safe
  repeated project loads.
- Blueprint project identity, immutable rule windows, fresh OUT datasets,
  preserved failures and licensed voltage-divider runner.
- Corpus v2 definition identities, conditional ports, signal dimensions and
  label evidence; deterministic topology endpoint geometry.
- Optional-null ESCR round-trip for LCC requests.
- Physical full-bridge AVM branches, auxiliary precharge and measured-current
  KCL accounting with the original tolerance; fail-closed PWM control bindings.
- The existing static arrester energy optimizer used by the three-arrester
  delivery. Its LP and observed-energy calibration passed independent checks.
  It remains a pre-solver requiring separate model simulation.

## Integration verification

The frozen runtime revision is `b4e6953cb1f9d9548d7a30a9ff85e4b20fe96456`.
The later merge retaining the local main commit changes ancestry only; its
runtime, tests and scripts are byte-identical to that tested revision.

- Focused combined checks: 87 passed.
- Complete offline suite: **4086 passed, 54 skipped**, 288.73 s. Opt-in skips
  are not physical acceptance.
- Fresh licensed sweep: baseline R=1 succeeds, the deliberate invalid parameter
  fails, and R=2 succeeds afterward; all 42 checks pass. Two normal cases each
  retain 801 samples for two channels. The constrained voltage-RMS selection
  chooses R=2. Source, prepared model and Master hashes are unchanged; recorded
  owned instances exited.
- Acceptance inventory: 19 declared report scopes are VERIFIED, no INVALID
  evidence; `mmc_stage_a` and `modern_core_5` lack a single durable report.
  The overall inventory remains INCOMPLETE.
- Package build, installed tool/asset probing, dependency and compilation checks
  pass. Full inventory is 112 tools; the sweep profile includes 8 with capability
  discovery.

Fresh sweep evidence is
`D:/PSCAD-Workspace/integration-20261014/sweep/.pscad-mcp/sweeps/sweep-4672f9c44f8c4ba5ab62b39172c6ad41/licensed-acceptance.json`.
The independent integration logs and artifact hashes are under
`D:/PSCAD-Workspace/integration-20261014/verification.json`.

## Scope boundaries

[October acceptance](current-status-20261013.md) retains the tested Blueprint,
Legacy, three full-bridge AVM ratings and partial Corpus scopes. Their reports
are not relabeled as new main model acceptance. [Sweep acceptance](parameter-sweep-20261013.md)
and the fresh integration report cover the serial OUT workflow; licensed
cancellation, restart recovery and PSOUT coverage remain unverified.

Parametric LCC still needs its 13 physical mappings and rating matrix; fixed
LCC still needs a qualified independent reference. Detailed PWM requires real
control wiring and mappings. The fourth Corpus source needs original Master
4.6.3. Existing electrical thresholds, source immutability and license opt-ins
remain unchanged.

The old LCC hardening, MMC Stage A and fault-evidence branch differences remain
recoverable. Their applicable inventory/output/planner/replay behavior already
has current implementations; the remaining older interfaces and unverified
measurement drafts are not reapplied over the accepted code. Generated output,
temporary and spreadsheet directories retain their local contents.

## Later detailed-PWM branch qualification

The isolated `codex/mmc-detailed-pwm` branch completes the explicit full-bridge
640 kV/1000 MW/60 Hz/200 km overhead reference. Its eleven scenes, untimed
delivery and independent reload pass 5698 physical checks; the actual published
file passes another 404 checks. Electrical waveforms belong to `d0e547d` and
the independently verified publication repair to `95655d1`. Source/model/library
identities and all owned cleanup pass. This branch is not merged into the
historical main integration described above. See the
[scoped evidence and limitations](mmc-detailed-pwm-20261015.md).
