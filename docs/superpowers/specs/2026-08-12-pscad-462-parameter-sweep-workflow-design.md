# PSCAD 4.6.2 Parameter Sweep Workflow Design

**Date:** 2026-08-12

**Status:** Approved for implementation

## Goal

Add a durable parameter-sweep workflow for PSCAD 4.6.2 that runs an explicit
list of scenarios against isolated project copies, continues after recoverable
scenario failures, resumes across Codex, MCP, and PSCAD restarts, and compares
bounded output statistics against an optional baseline scenario.

The workflow builds on the existing component-parameter, project build/run,
project-message, run-status, and PSOUT APIs. It does not expand or bypass the
legacy Automation Library's native control surface.

## Scope

The first release supports:

- an explicit ordered scenario list rather than generated Cartesian products;
- one or more component parameter updates per scenario;
- an immutable baseline copy and a fresh attempt copy for every run;
- serial scenario execution through a persistent, caller-driven state machine;
- failure evidence and continuation when baseline restoration is verified;
- explicit PSOUT or OUT files and channel selectors;
- `count`, `min`, `max`, `mean`, `first`, and `last` statistics;
- absolute and relative differences from one optional baseline scenario; and
- durable recovery after Codex, MCP, or an owned PSCAD process restarts,
  subject to the legacy active-run boundary described below.

The existing 60 MCP tools keep their names, inputs, outputs, and behavior. Four
new workflow tools are added.

## Architecture

The existing layering remains intact:

`FastMCP tools -> PscadService -> PscadBackend -> vendor API`

A separate workflow layer composes those service capabilities:

`parameter-sweep tools -> SweepService -> SweepStore / SweepRunner /
SweepResultAggregator -> PscadService`

The workflow layer never receives or exposes a raw vendor proxy.

### Components

`SweepSpec` parses and normalizes the request. It validates source paths,
project identity, unique scenario names, parameter targets, output selectors,
and the optional baseline scenario before any mutation.

`SweepStore` owns the manifest, checkpoint, attempt evidence, and report. It
writes JSON to a sibling temporary file, flushes it, and atomically replaces the
destination. Manifest and baseline hashes make external drift detectable.

`SweepRunner` advances one bounded state transition at a time. It shares the
service mutation lock with other state-changing PSCAD operations and permits
only one active sweep campaign for a configured workspace, including across
multiple MCP processes. The service acquires its mutation lock once around a
workflow advancement; internal workflow operations use non-locking primitives
so service methods never recursively acquire that lock. While a campaign owns
the workspace-wide lease, unrelated state-changing MCP tools return
`SWEEP_BUSY`; read-only status and campaign-status tools remain available.

`SweepResultAggregator` consumes only verified output artifacts. It produces
per-channel statistics and recomputes baseline comparisons whenever either the
baseline or another successful scenario changes.

## Persistent Layout

Every campaign is stored below the configured workspace:

```text
PSCAD_MCP_WORKSPACE/.pscad-mcp/sweeps/<campaign-id>/
|-- manifest.json
|-- checkpoint.json
|-- baseline/
|-- attempts/
|   `-- <scenario>/attempt-<n>/
|       |-- work/
|       |-- evidence/
|       |-- outputs/
|       `-- result.json
`-- report.json
```

`manifest.json` is immutable after creation and contains the normalized request,
schema version, source hash, baseline hash, and campaign ID. `checkpoint.json`
contains current workflow state and attempt metadata. Attempt directories and
evidence are append-only. `report.json` is a reproducible aggregate that may be
rewritten atomically from attempt results.

Campaign IDs are server-generated, filesystem-safe identifiers. User-provided
scenario names remain display labels; a deterministic encoded directory key is
stored separately so names cannot escape the campaign directory or collide by
case on Windows.

## Manifest Contract

`create_parameter_sweep` accepts:

- `source_root`: a directory inside `PSCAD_MCP_WORKSPACE`;
- `entry_file`: a project or workspace path relative to `source_root`;
- `project_name`: the case project to modify and run;
- `scenarios`: a non-empty ordered list;
- `outputs`: a non-empty list of relative output paths and channel selectors;
- `baseline_scenario`: an optional scenario name;
- `run_timeout_seconds`: an optional per-attempt wall-clock deadline, defaulting
  to 3600 seconds and constrained to 60 through 604800 seconds; and
- bounded polling and output-reading options with server-defined defaults.

Each scenario contains a unique name and a non-empty list of updates. An update
identifies `component_id` plus a non-empty parameter mapping. Duplicate updates
to the same component parameter within a scenario are rejected.

Each output declaration identifies one `.psout` or `.out` file relative to the
attempt work directory and one or more exact normalized channel-path selectors.
Wildcards are not supported. Absolute output paths, parent traversal, links
escaping the attempt directory, empty selectors, and unsupported suffixes are
rejected.

Both suffixes retain compatibility with the existing `read_output_file` tool.
Acceptance is based on successful parsing and channel matching, not the suffix
alone; an `.out` file that the configured output reader cannot parse fails
collection explicitly.

The normalized manifest preserves JSON scalar parameter values. Arbitrary code,
expressions, callbacks, environment interpolation, and custom formulas are not
accepted.

## Creation And Read-Only Preflight

`create_parameter_sweep` performs no PSCAD mutation, build, or simulation. It:

1. resolves every source path through the existing workspace policy;
2. rejects a source inside `.pscad-mcp/sweeps` to prevent recursive copies;
3. snapshots the source root into immutable `baseline/`, excluding the managed
   `PSCAD_MCP_WORKSPACE/.pscad-mcp` state tree when it is nested below the
   source root;
4. records deterministic relative-path and content hashes for every regular
   file in the source snapshot, using the same managed-tree exclusion for the
   source hash;
5. verifies a second source hash after copying and fails creation if the source
   changed during the snapshot; directory reparse points are not followed and
   any file link or reparse point is rejected rather than copied;
6. creates a disposable preflight work copy from the hashed baseline;
7. establishes a temporary MCP-owned PSCAD session, loads only the disposable
   preflight copy, and never loads the baseline or supplied source path;
8. verifies the target project, component IDs, parameter names, and proposed
   parameter ranges without writing them, and verifies that every loaded
   project path used by the target resolves inside the disposable copy;
9. closes and verifies shutdown of the temporary owned session;
10. deletes only the verified server-created preflight copy; and
11. atomically writes the manifest, ready checkpoint, and initial report.

A failed preflight removes only the incomplete server-generated campaign
directory. It never changes or deletes the supplied source.

Preflight acquires the workspace-wide sweep lease. It starts a temporary session
only when no PSCAD process or previously attached MCP session is active. It does
not close, reuse, or take over a pre-existing session because the workflow
cannot prove that session has no unsaved user state. A workspace whose absolute
references resolve to source or any location outside the disposable copy fails
with `SWEEP_INVALID_SPEC` rather than building against those external files.

## Execution Model

The workflow is persistent and caller-driven. It does not create a background
worker. `run_parameter_sweep(campaign_id, max_wait_seconds=20)` advances safe
steps until it reaches the time budget or a durable waiting state, then returns
the latest status. `max_wait_seconds` is bounded by the server. An individual
vendor operation remains subject to the existing executor timeout and may
outlive the polling budget.

Scenario states are:

```text
pending -> preparing -> building -> running -> collecting -> restoring
                 |          |          |             |           |
                 +----------+----------+-------------+           +-> succeeded
                 |                                                `-> failed
                 `--------------------------------------------------> needs_review
```

An attempt records its intended terminal outcome before entering `restoring`.
Only verified parameter restoration and owned-session shutdown convert it to
`succeeded` or recoverable `failed`. An interrupted or unverified restoration
leaves the campaign blocked in `restoring`; it is never inferred complete from
the absence of an exception.

Campaign states are `ready`, `running`, `completed`,
`completed_with_failures`, and `blocked`.

For every attempt, the runner:

1. creates a new append-only attempt directory from the immutable baseline;
2. verifies baseline and attempt hashes before loading anything;
3. removes only the exact declared output artifacts from the new attempt copy;
4. establishes a clean owned PSCAD session and loads the copied entry file;
5. reads and records current values for every target parameter;
6. validates every proposed value before the first write;
7. writes all values and verifies each by read-back;
8. builds the target project and captures structured project messages;
9. records output non-existence, run start time, backend identity, session
   identity, and checkpoint state before dispatching the non-blocking run;
10. returns while the run is active and polls it on later calls;
11. stops the owned run after `run_timeout_seconds`; if verified stop cannot be
    established, marks the campaign blocked rather than starting another case;
12. verifies terminal state and output ownership before collection;
13. copies verified outputs into the attempt evidence area and reads only the
    declared channels;
14. restores all recorded parameters and verifies each value in a `finally`
    path; and
15. closes the owned PSCAD session before another attempt is loaded.

PSCAD 4.6.2 does not expose a sufficiently verified attach or project-unload
path through the current legacy backend. Therefore a sweep requires an MCP-owned
session and rotates that session between attempts. An externally owned or
ordinary manually opened PSCAD process is rejected for sweep execution. The
workflow does not terminate external processes.

Scenarios run strictly serially. The workflow does not use PSCAD parallel
simulation or simulation-set concurrency.

## Output Ownership And Collection

An output is accepted only when all of the following are true:

- its resolved path remains inside the attempt work directory;
- no artifact with that identity existed at dispatch time;
- its modification time is not earlier than the recorded run dispatch time,
  allowing only a small documented filesystem timestamp tolerance;
- its size is positive and stable across two bounded observations after the run
  reaches a terminal state; and
- the existing output reader can parse it and find every required channel.

The original attempt output is copied to `outputs/` before analysis. A missing,
stale, unstable, unparseable, or channel-incomplete artifact fails collection;
it is never presented as a successful new result.

For each selected channel, the report stores `count`, `min`, `max`, `mean`,
`first`, and `last`, plus bounded reader warnings. These are explicitly labeled
`statistics_scope: bounded_sample`: `count` is the returned sample count and
the other values describe that deterministic bounded sample, not necessarily
the entire trace. The report records the configured sample limit. This
preserves the current output reader's memory bound and avoids presenting sample
statistics as exact full-trace extrema or endpoints.

Comparisons apply to `min`, `max`, `mean`, `first`, and `last` using:

- `absolute_delta = scenario_value - baseline_value`; and
- `relative_delta = absolute_delta / abs(baseline_value)`.

If the baseline value is zero, missing, or non-numeric, `relative_delta` is
`null` with a warning. `count` is diagnostic only and receives no delta. If the
baseline scenario does not succeed, successful scenario statistics remain
available and comparison fields report that the baseline is unavailable.

## Checkpointing, Resume, And Leases

Every externally observable transition is checkpointed before the next side
effect. Checkpoints include manifest hash, attempt number, last completed step,
timestamps, backend/version, owned session PID when available, parameter
snapshots, run dispatch identity, artifact observations, and bounded errors.

An in-process lock, an exclusive campaign-directory lease, and a workspace-wide
`active-sweep.lease` below `.pscad-mcp/sweeps` prevent concurrent advancement of
the same or different campaigns. The global lease records the campaign ID. Both
leases store a bounded owner nonce, PID, process creation time, and heartbeat so
Windows PID reuse is not mistaken for the original owner. A live lease is never
stolen. A stale lease may be reclaimed only after verifying that its exact MCP
process is gone and no recorded owned PSCAD process remains active; otherwise
the campaign becomes `needs_review`. Read-only status does not acquire the
global lease.

The workspace-wide lease persists across caller-driven polling gaps and while
an owned run is active. It is released after a terminal campaign, or after a
blocked campaign has verified that no owned PSCAD process remains. Ordinary
state-changing service operations consult the lease and may proceed only when
there is no active campaign or when the runner supplies the matching unforgeable
in-process owner token.

After restart, non-running durable steps resume from the last completed
checkpoint. For a checkpoint in `running`, the runner compares the recorded
owner identity, process inventory, backend capabilities, and output evidence:

- the same still-connected MCP process resumes polling its matching active run;
- a backend with a separately verified reattach contract may resume polling a
  matching active run after process restart;
- a verified stable owned output after the recorded process exits proceeds to
  collection;
- a confirmed absent run with no owned output becomes failed; and
- ambiguous state becomes `needs_review` and is never automatically rerun.

The PSCAD 4.6.2 legacy backend has no verified reattach contract. If its
recorded PSCAD process remains active after the owning MCP process restarts, the
new process records `SWEEP_RESUME_UNCERTAIN`, performs no command against that
process, and blocks the campaign for review. Once that old process is confirmed
absent, the user can explicitly retry the interrupted scenario from a new
attempt copy. This is durable recovery without falsely claiming seamless
reattachment.

A `needs_review` scenario makes the campaign `blocked` until an explicit retry
can prove that the recorded run and owned process are no longer active. It is
not counted as an ordinary recoverable failure that permits later scenarios to
start.

`get_parameter_sweep_status` reads only campaign files and never calls PSCAD, so
it remains available while PSCAD is disconnected or unhealthy.

## Failure, Restoration, And Retry

A scenario failure captures the structured error, project messages, attempt
state, and all safe evidence. The runner continues with later pending scenarios
only after parameter restoration and owned-session shutdown are both verified.

If restoration or session cleanup cannot be verified, the campaign becomes
`blocked`; no later scenario starts. This prevents a contaminated state from
propagating.

There is no automatic retry. `retry_parameter_sweep` requires an explicit list
of scenarios currently in `failed` or `needs_review`. It first verifies that no
campaign attempt or PSCAD run is active, then returns the selected scenarios to
`pending`. Each retry creates `attempt-N` and preserves all earlier evidence.

External modification of the manifest, baseline, checkpoint ownership fields,
or current attempt work tree is treated as drift. The runner either rejects the
campaign as invalid or enters `needs_review`; it does not silently repair or
overwrite user-visible evidence.

## Tool Contract

Four tools are added:

- `create_parameter_sweep(spec)` returns the campaign ID, normalized manifest
  summary, and preflight result;
- `run_parameter_sweep(campaign_id, max_wait_seconds=20)` advances the campaign
  and returns its current bounded status;
- `get_parameter_sweep_status(campaign_id, include_report=false)` returns
  checkpoint state and optionally the aggregate report without contacting
  PSCAD; and
- `retry_parameter_sweep(campaign_id, scenario_names)` schedules explicit
  failed or review-required scenarios for new attempts.

All tools use the existing FastMCP error envelope. New stable error codes include
`SWEEP_INVALID_SPEC`, `SWEEP_BUSY`, `SWEEP_DRIFT_DETECTED`,
`SWEEP_OUTPUT_MISSING`, `SWEEP_RESTORE_FAILED`, and
`SWEEP_RESUME_UNCERTAIN`. Each receives an explicit `retryable` value and
`suggested_action` through the service error-guidance table.

Status and error payloads are bounded. Full project messages, reader warnings,
and attempt details remain in campaign evidence files and are referenced by
workspace-relative paths.

## Safety And Compatibility

- All campaign and source paths use the existing fail-closed workspace policy.
- Symlinks and junctions are resolved and rejected when they escape an allowed
  root.
- The source tree is never written, saved, or deleted by the workflow.
- A copied workspace or project may not redirect the target build to a source
  tree or other path outside its attempt copy.
- Baseline and attempt copies never include another campaign tree.
- Destructive cleanup is limited to server-created attempt paths whose resolved
  campaign ancestry and recorded identity are verified first.
- The workflow never kills an external PSCAD or EMTDC process.
- Legacy and modern backends retain their existing protocol and behavior. The
  first real acceptance target is PSCAD 4.6.2 x64; modern behavior remains
  contract-tested until a licensed 5.x environment is available.

## Testing And Acceptance

Development follows test-first slices.

Unit tests cover manifest normalization, directory-key collisions, path escape,
atomic JSON replacement, hashes, state transitions, leases, stale lease rules,
statistics, baseline deltas, zero baselines, and bounded payloads.

Fake-backend workflow tests cover:

- successful multi-scenario execution;
- invalid parameters with no writes;
- partial parameter-write failure and verified restoration;
- build failure followed by continuation;
- run failure and terminal-state handling;
- missing, stale, unstable, malformed, and channel-incomplete outputs;
- restoration or shutdown failure causing a blocked campaign;
- restart during each durable state;
- ambiguous running-state recovery becoming `needs_review`;
- explicit retry producing a new append-only attempt; and
- concurrent calls being rejected without duplicate mutation.

Repository verification requires the complete test suite, `pip check`,
`compileall`, built-wheel installation probing, the updated unique tool count,
and `git diff --check`.

Real PSCAD 4.6.2 x64 acceptance uses a copied public example and at least three
scenarios, including one deliberate failure. It must demonstrate:

- later scenarios continue after the recoverable failure;
- a campaign resumes across a deliberately restarted MCP at a non-running
  durable checkpoint without duplicating a completed attempt;
- an MCP restart during an active legacy run becomes `needs_review`, sends no
  command to the old PSCAD process, and permits an explicit new attempt only
  after that process is confirmed absent;
- every requested channel statistic and baseline delta matches an independent
  calculation;
- source-tree hashes are unchanged;
- attempt outputs belong to their recorded runs; and
- no owned PSCAD or EMTDC process remains after completion.

Real acceptance evidence is stored in the workspace campaign directory and is
not committed to the repository.

## Non-Goals

- Cartesian-product scenario generation.
- Automatic retries or retry policies.
- Background or daemon execution after an MCP call returns.
- Custom expressions, formulas, assertions, or threshold pass/fail rules.
- Automatic discovery or collection of every output channel.
- Parallel scenarios or simulation-set concurrency.
- Editing or saving results back into the source project.
- GUI coordinate automation, raw XML mutation to bypass vendor commands, or
  attach/control claims unsupported by the vendor API.
- PSCAD 4.6.3 or 5.x real acceptance in this milestone.
