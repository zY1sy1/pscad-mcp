# Embedded EMTDC Control Implementation

The adapter supports bounded intervals on Main-page scalar `master:const` and
`master:var` Value signals with orientation 0 and an audited unconditional Real
OUT port at `(36, 0)`. Repeated non-overlapping intervals on one target are
supported. A copied const definition evaluates EMTDC TIME; the original owner,
location, output net, and a colocated `master:pgb` Signl input bind the measured
command. The channel role is `control_command`, never fault-active evidence.

`prepare_timed_scenario` resolves canonical profile commands against the saved
scenario source. Public `run_scenario` verifies their identities and values
against the prehashed plan, creates an exclusive derived PSCX, and performs
load/save/readback/build before running it. It preserves the absolute project
path for evidence and output discovery, and uses the unique loaded case name
for vendor operations. Real OUT/INF samples must cover both edges and the
complete interval at the planned output step. Registration does not substitute
for waveform evidence.

Embedded runs reject explicit `output_files`. Only the current derived
project's newly discovered complete OUT part set is eligible. OUT, INF, INFX
and the saved project are snapshotted as bytes, hashed before interpretation,
then rehashed afterward. The INFX Main instance, owner, part, index, dimension
and unit must match the planned PGB; the INF channel must match that same
index. Every OUT part must be fresh for the run and have the same full time
domain. INFX sampling and the numeric output domain are both checked.
The complete part set is enumerated again after reading to detect added files.

Source and derived native names are compared after PSCAD name normalization.
The destination namespace must be absent before load, and exactly one new
case must appear afterward. A returned filename is checked when available;
Legacy 4.6 exposes no filename getter, so evidence explicitly records the
verified namespace admission instead of claiming a filename readback.
Polling uses the Main-only component API and rejects other instance paths
before any event writes. Native providers must explicitly enumerate any
supported instance paths beyond Main.

PWM candidate staging accepts explicit `timed_control_options` with
`master_path` and `max_timing_error_s`. It binds the schedule to the candidate's
saved scenario source and uses a separate derived name per event scenario.
The existing requirement for every planned scenario's full analysis to PASS is
preserved. Unsupported converter/fault control sequences remain errors.
Scenario and timing failure artifacts retain the original exception.

The original compiler libraries are included in PWM `asset_hashes` at planning
time. Staging checks these before copying, then checks source and copies again.
Copying consumes the shared template audit's `compiler_support.files`; it does
not infer absent vendor libraries. Old plans missing required compiler input
hashes must be recreated.

## Shared Files And Review

Root authorized the additional minimal ownership needed in
`hvdc/preflight.py`, `hvdc/service.py`, and MMC `parametric_planner.py`.
Preflight keeps the source/target file protection while allowing a separate
runtime project name. Status uses that same runtime identity. The planner uses
the existing PWM `asset_hashes` field for compiler source paths and hashes.
Related shared scenario/LCC test providers declare the new verified timing
contract; their coarse synthetic clocks are not licensed timing evidence.

B's isolated compiler-audit change `f517945` was imported as `9506586`.
Its subsequent path-boundary fix `26b242c` was imported as `f6db91e`.
The remaining template/fault instrumentation modules remain owned by B.

## Fresh Evidence Protocol

The dedicated licensed test requires `PSCAD_MCP_ACCEPTANCE=1`; the official
template case additionally requires `PSCAD_MCP_MMC_ACCEPTANCE=1`. Concurrent
ownership is process-local through `PSCAD_MCP_ACCEPTANCE_CONCURRENT=1` and the
shared `acceptance/process_scope.py`. Every run creates a new output directory.
After the first owned instance quits, a second Python process and owned PSCAD
instance load a byte-identical copy of the frozen saved project, with hashed
companion libraries, compile and run it. No second source regeneration occurs.
Both run reports and their OUT/INF indexes remain distinct.
Runner cleanup reads the already established backend's cached managed identity,
so failed status acquisition cannot hide ownership or launch a replacement.
Scenario shutdown and owned quit have independent error handling; a failed
shutdown does not skip quitting the owned instance.
Failed owned attaches are quarantined by `PscadService` in a separate pending
cleanup reference. They do not grant business access or permit another attach.
The runner consumes this reference when normal `_backend` was never established;
quit, shutdown and repair retain it until cleanup succeeds. The shared service
change has an independent test file suitable for both acceptance workers.

The dedicated numerical contract is `[0.02, 0.03)` s, final time 0.05 s,
integration/output steps 10 us, and a maximum absolute error of 20 us per
edge. These are timing-test values, not MMC electrical acceptance thresholds.
The official `Pref2` command changes -900 to -800 to -900 MW; the VSCConverter
Pref parameter explicitly declares MW and receives the Pref2 signal. This
does not claim power reversal, DC-fault blocking, or post-fault recovery.

## Diagnosed Attempts

- `minimal-457ae34ba7c14c9a94eef4b580f01afd`: absolute PSCX passed as vendor
  project name. Fixed with separate file/runtime identities.
- `minimal-34906dfe42b84f548c02a1f7801da41d` and
  `minimal-87ce1f091a7842d0b4ff8dd069de6e7e`: vendor project kind is `Case`.
  Fixed case-insensitive inventory matching after recording live inventory.
- `pwm-5b919b93c193473c8e0dfd574129ce32`: vendor lacks per-project unload.
  Reload proof moved to a new owned process and frozen saved-project copy.
- `pwm-db042f78098945b5b5b117d0102ec5be`: missing staged `lib/$(Compiler)`
  companion files caused unresolved Fortran routines. Fixed declared support
  copying and added a compile-error check before simulation dispatch.

All attempt directories are under `D:/PSCAD-Workspace/emt-timed-control` and
retain failed reports and owned-cleanup evidence. Intermediate successful
minimum and PWM runs precede final frozen-revision evidence; only the final
handoff identifies delivery evidence.
