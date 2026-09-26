# 2026-09-26 licensed completion work

The user explicitly authorized process-local PSCAD 4.6.2 licensed acceptance.
No further license opt-in confirmation is needed for continuing this task.
Runs use independent managed instances, Python processes and output workspaces;
no foreign PSCAD process was stopped or attached.

MMC implementation verified: `9cfe1d41dd2113cb4e72e3a285b1da00397a2b6b`.
Legacy implementation verified: `d7805e77045407a3f7f9ce8999e7d13a4cd34a7c`.
Development checkout: `codex/complete-acceptance`; licensed runs used frozen
named verification checkouts. All three MMC suites passed, as did all 15 Legacy
core/reliability cases. Each report retains its own exact revision. Later Legacy
changes affect paused run control and binary PSOUT reading, not the native MMC
generator or the numbered OUT evidence used by those physical suites.

The `9cfe1d4` complete offline regression passed **3832 tests, 52 skipped** in
291.85 s. After the Legacy and evidence-index updates, the final full repository
regression passed **3841 tests, 52 skipped** in **238.47 s**. Relevant Ruff fatal
checks and Git whitespace checks passed. Production source was committed before
this final run; the remaining changes are evidence records and their assertions.
Skipped licensed tests are not counted as physical acceptance.

## Reproduced defects and corrections

| Commit | Reproduction | Correction and verification |
| --- | --- | --- |
| `4f6b4f0` | The real bipolar LCC template uses `$(Freq)`; unit audit returned an empty unit and rejected it | Resolve only exact references to one global parameter with a consistent declared unit. Missing, duplicate, conflicting or expression-based references remain rejected. 57 binding/audit tests passed and all seven real-template unit bindings were resolved. This does not establish complete physical parameter mappings. |
| `78e2b78` | MMC normal operation passed, but the longer fault directory caused vendor file-write errors and missing output; generated paths reached 258–259 characters | Check the longest generated suite path before creating a workspace or starting PSCAD. Short-root reruns succeeded past the same build/output stage. Previous failing reports remain untouched. |
| `dfaa0b0` | LCC staging retained the source project identity, used a conflicting filename, ignored numbered OUT files below `.gf42`, and could read output before terminal completion | Rewrite project/self-namespace identity, keep staging filename and project name consistent, wait for the real run state, discover one fresh numbered dataset and reject stopped runs. 79 executor/service/lifecycle tests passed, followed by a real execution probe. |
| `85f9d84` | The 500 kV / 750 MW / 50 Hz / -75 MVAr request retripped on DC undervoltage during recovery from an AC three-phase fault | Retain the cable-energy and incremental-loss model and 0.85 damping, increase the default DC-loop design frequency from 2 Hz to 4 Hz so its nominal settling time fits the existing 0.2 s power-restoration ramp. No physical threshold or recovery window changed. The same fault passed in a diagnostic run; 61 related tests passed before the complete matrix rerun. |
| `9cfe1d4` | The 500 kV pole-ground case passed fault protection/recovery but recorded -2.683 mV equivalent capacitor voltage at 0.5 ms, outside the unchanged 1 mV tolerance. Generated Fortran reproduced a negative storage-current demand from an empty stack | Bound the complete delayed storage-current sink by available capacitor charge, retaining the existing eight-step reserve used by the nonohmic sink. Actual measured voltage and energy remain untouched. 54 arm/bundle/dq/identity tests, an isolated licensed average-arm gate and the previously failing pole-ground case passed. |
| `3993c3d` | The installed PSOUT sample returned zero channels because its virtual root has no `Name` variable | Traverse the unnamed file root; malformed non-root identities retain their diagnostics. The genuine sample now yields 66 channels with bounded sampling. |
| `d700df7`, `ca6bbb6` | The licensed runner omitted the service workspace, removed pre-existing environment values, and matched outdated repair-response wording | Scope and restore the process workspace; verify connected ownership and the actual managed PID instead of English wording. Windows PowerShell and PowerShell 7 regression coverage passed. |
| `d7805e7` | A Stop command on a paused solver never reached a terminal state; issuing a fresh project Run rebuilt the project instead of resuming it | Resume through the verified native Pause toggle, require a sole active target, and revalidate scope before each bounded Stop retry. A real long-running probe reached `idle` with clean shutdown; all 15 licensed cases then passed. The run-control fixtures now remain active long enough to exercise the commands. |

The recovery diagnostic reduced recovered-power error from approximately 100%
to 0.1653%. Its maximum measured DC-current peaks were 1.1309 pu and 1.1469 pu,
below the unchanged AC-fault limit of 1.25 pu. Maximum capacitor deviations were
6.925% and 7.998%, below the unchanged 10% limit. A diagnostic case is not a
complete model-acceptance suite.

Preserved physical failure:
`D:/PA/c26b/suite-20260926-113127-d249b623/ac_three_phase/attempt-20260926-113342-98651928/report.json`.
Successful controlled diagnostic:
`D:/PA/c26b4/attempt-20260926-114104-2aef632c/report.json`.
The diagnostic request explicitly overrides the gains; the final matrix uses
the original engineering requests with empty overrides and the repaired default
derivation.

The subsequent pole-ground failure is preserved at
`D:/PA/c26v2b/suite-20260926-114724-53ebb43f/dc_pole_to_ground/attempt-20260926-120017-a5fae20d/report.json`.
A 5 us diagnostic did not solve the problem and failed precharge; its report is
`D:/PA/c26b5u/attempt-20260926-120616-68e81a20/report.json`.
The corrected coupling passed the same fault at the original planned 10 us:
`D:/PA/c26bcap/attempt-20260926-121407-bb418f85/report.json`.
Its minimum measured equivalent capacitor voltage is 0, with the original
`voltage_residual_kv=1e-6` and `energy_relative_error=1e-9` gates retained.
The isolated native component also passed at `9cfe1d4`:
`D:/PA/c26arm/attempt-20260926-121454-0c1f8eb6/report.json`.
That report declares `component_accepted=true`, `model_accepted=false`.

## LCC evidence

The executor probe at `dfaa0b0` completed real load, save, run, fresh numbered
output read and owned-process cleanup. It preserved the original template and
Master hashes and read five OUT parts. Its scope is
`lcc.parametric_executor_lifecycle_probe`, with `model_accepted=false`:
`D:/PA/l26/probe-114428/report.json`.

This probe uses the source template's nominal frequency. It does not bypass
the public builder's unresolved-binding gate or count as a rated design,
operating-mode, fault or golden acceptance.

Both fixed-LCC reports below belong to `85f9d84`:

| Gate | Result | Report |
| --- | --- | --- |
| WP1B six companion fixtures, full topology and smoke | PASS | `D:/PA/l26fixed/fixed-lcc-20260926-035029-237/fixed-lcc-acceptance-report.json` |
| WP1C dynamic/physical engineering | Engineering PASS; final INCOMPLETE_ANALYSIS | `D:/PA/l26fixed/run-20260926-115423-402/fixed-lcc-dynamic-report.json` |

WP1B SHA-256: `63003bafc9ab105d091bbc3836cacdd916b66cf7c12a79a18baf1fab674bb939`.
WP1C SHA-256: `1f3da7f5245e06130b8f49200414487dd69dbd1afd4a21fbc2407ef44a17404b`.
The vendor rejected native save/save-as calls on these cases; the existing
verified persistence fallback completed publication and reload/recompile.
Those diagnostic messages did not prevent the final engineering gates passing.
Independent reviewed golden remains absent; no final LCC accepted claim is made.

## MMC matrix

Each request requires normal operation, AC three-phase, AC single-line-ground,
DC pole-pole, DC pole-ground and an independent portable reload. All child
reports must share the same request, physical parameters, producers and revision.

| Request | Workspace | Final verdict |
| --- | --- | --- |
| 640 kV / 1000 MW / 60 Hz / Q=0 / 100 km cable | `D:/PA/c26v3a/suite-20260926-121407-e4d0b384/report.json` | PASS; model_accepted=true |
| 500 kV / 750 MW / 50 Hz / Q=-75 MVAr / 100 km cable; AC grids 180/190 kV | `D:/PA/c26v3b/suite-20260926-121823-bfb0895a/report.json` | PASS; model_accepted=true |
| 640 kV / 1000 MW / 60 Hz / Q=+100 MVAr / 100 km cable | `D:/PA/c26v3c/suite-20260926-121823-af3bb399/report.json` | PASS; model_accepted=true |

The three report SHA-256 identities, in the same order, are:

- `2c3d7d158f5069e3358ad1427500cb2882844bfabcacb43a80a4732821db98c3`
- `1f39ad43cc0a186d45762a226974e80fd6fbef2a60091b0751bdf965ac36ccf1`
- `a72d96d6d040aaafd207c3f6c79c1c92b4469832275fbf8a4c7be3a1dafc274c`

Each suite passed all six stages with empty engineering overrides, immutable
inputs/code and independent owned cleanup. All **84** declared suite/child/
accepted-file identities passed a fresh hash audit:
`D:/PA/c26-final-mmc-integrity.json`. The accepted projects and companion files
are located by each suite's `accepted_project`, `accepted_library` and
`accepted_hashes`; no previously compiled executable was copied into the reload.

The earlier short-path default suite passed at `46efa12`:
`D:/PA/c26a/suite-20260926-113127-418e1a8d/report.json`.
It is historical after the voltage-loop change, not a substitute for the matrix
above. The original long-path attempts are preserved under
`D:/PSCAD-Workspace/completion-licensed-20260926-r1`.
At `85f9d84`, the default and +100 MVAr full suites also passed, while the
500 kV suite failed its final pole-ground network-identity gate. These attempts
remain under `D:/PA/c26v2a`, `D:/PA/c26v2b` and `D:/PA/c26v2c`; the full matrix
above repeats the shared coupling behavior on one final implementation.

## Legacy closure and evidence integrity

The original 15-case attempt is preserved at
`D:/PSCAD-Workspace/acceptance/completion-20260926/legacy-123458.json` and its
adjacent log. It contained two failures and three errors. The repaired suite
passed all 15 tests in 80.837 s, with source/Master hashes unchanged and no
remaining owned process:
`D:/PSCAD-Workspace/acceptance/completion-20260926/legacy-130327.json`.
The successful direct stop probe is `D:/PA/stop-125501/report.json`.
Disabled-layer membership remains a verified vendor capability limit, not a
successful state mutation; that negative contract is explicitly tested.

The acceptance inventory now contains 15 scopes. Twelve have verified declared
report evidence; three still lack a durable report. The offline audit remains
`INCOMPLETE` with exit code 2, not a whole-release PASS. Historical failures are
retained and no old report has been overwritten or promoted to a later revision.

Diagnostic trace comparison (not independent golden evidence):

![Measured regression traces](/D:/PA/c26-regression-traces.png)

Source identities and plotting transforms:
`D:/PA/c26-regression-traces-sources.json`. The recovery panel includes the full
displayed transient voltage range; its acceptance band applies from 0.5 s after
fault clearing.

## Work still outside a complete acceptance claim

- The public parametric LCC plan still has 13 unresolved logical parameters.
  Units and execution are now repaired, but physical mappings must not be
  guessed. The original contract incorrectly used `P=Vdc*Idc` for bipolar
  requests. The user has resolved the basis using engineering convention:
  total system power, pole-to-ground voltage, and per-pole current. The repaired
  contract uses `P=2UI` for bipolar and `P=UI` for monopolar requests; see
  [rating convention](lcc-rating-convention.md). The physical mappings and
  licensed rating matrix remain unfinished. The historical plan and inventory are in
  `D:/PSCAD-Workspace/completion-licensed-20260926-r1/lcc-diagnosis`.
- Fixed/native LCC final WP6 needs independently reviewed reference output;
  engineering PASS does not supply it.
- Full-bridge AVM and detailed-device/switching/thermal coverage are separate
  model scopes. Half-bridge average-value acceptance does not extend to them.
- The generic Blueprint Builder still needs its own approved blueprint/source
  fixture and licensed end-to-end evidence. Legacy core and MMC results cannot
  be substituted for that scope.
- The installed Modern automation package enumerates only PSCAD 4.6.2 x86/x64.
  PSCAD 5.x real acceptance needs a 5.x installation and usable licensed runtime.
  Read-only vendor inventory: `D:/PA/c26-environment.json`.

Repository changes are on the isolated completion branch and have not been
merged, pushed or deployed. Reports retain their tested commits and original
source/output hashes; later documentation commits do not change their scope.
