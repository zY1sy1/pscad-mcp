# PSCAD MCP Silent Learning And Improvement Design

## Context

The PSCAD MCP server already has a shared `register_tool` wrapper, stable
structured errors, executor health diagnostics, and broad unit, contract,
packaging, and licensed acceptance coverage. Those are sufficient foundations
for a local evidence loop, but the server currently does not retain invocation
outcomes across sessions, aggregate recurring failures, or provide Codex with a
reviewable improvement backlog.

The desired experience is unobtrusive. Normal PSCAD work must not display
learning messages, request ratings, or add foreground steps. When the server or
Codex cannot complete a requirement, the failure must be retained in a local
Markdown backlog and reviewed later as a group. A scheduled review runs every
Monday at 09:00 in `Asia/Shanghai` and asks for attention only when actionable,
high-priority evidence exists. A narrow immediate-reminder exception applies
when continuing without attention could conceal an incorrect result, leave a
partial mutation, or make recovery unsafe.

This is repository and workflow improvement, not model-weight training. The
durable learning products are structured evidence, regression tests, source
patches, project guidance, and reusable Codex skills.

## Decisions Already Made

- Use an in-server, local-only learning layer.
- Enable metadata collection by default and allow it to be disabled.
- Never persist tool arguments, successful result bodies, project content,
  simulation output, user prompts, exception messages, backend details, or
  tracebacks.
- Keep successful foreground workflows completely silent.
- Record explicit goal failures in a generated local Markdown backlog.
- Review the backlog every Monday at 09:00 in `Asia/Shanghai`.
- Make the scheduled review notify the user only when it finds a new or
  reopened high-priority candidate.
- Allow one concise immediate reminder for a defined critical failure; never
  suppress the existing operational or safety error that caused it.
- Never merge, push, publish, deploy, or weaken safety controls automatically.
- Perform remediation only after user approval, in an isolated branch or
  worktree, with test-first verification.

## Goals

1. Capture bounded, non-sensitive metadata for every non-learning MCP tool
   invocation without changing the tool's behavior or result.
2. Retain explicit evidence when Codex determines that a requested PSCAD goal
   was not achieved even though individual MCP calls may have returned
   successfully.
3. Deduplicate technical and semantic failures into stable improvement
   candidates.
4. Maintain a local Markdown backlog that is readable by the user and Codex
   but is not committed to the repository.
5. Run a quiet weekly review that reports only actionable findings.
6. Surface defined critical correctness, partial-mutation, and recovery risks
   immediately without making routine failures noisy.
7. Turn approved candidates into reproducible tests and minimal patches while
   preserving all existing PSCAD safety and service boundaries.
8. Allow collection and backlog data to be inspected, disabled, relocated,
   and cleared.

## Non-Goals

- Training, fine-tuning, or changing an OpenAI model.
- Uploading telemetry or sharing evidence between machines.
- Persisting full prompts, tool inputs, tool outputs, PSCAD files, waveforms,
  component values, or project paths.
- Inferring electrical correctness from a successful Python or MCP return.
- Editing source code during normal PSCAD operation.
- Automatically accepting a proposed fix because tests compile or pass.
- Automatically running licensed PSCAD acceptance without its existing opt-in
  environment variables.
- Automatically merging, pushing, releasing, or deploying a remediation.
- Replacing deterministic tests with statistical confidence scores.

## Considered Architectures

### A. In-Server Local Learning Layer

The shared MCP wrapper records metadata in a local SQLite database. The server
materializes a Markdown backlog, exposes bounded review and maintenance tools,
and supplies instructions for explicit goal-failure recording. A Codex skill
uses approved backlog candidates to drive test-first remediation.

This is the selected architecture. It sees every MCP client invocation, keeps
data local, requires no new runtime dependency, and can be contract-tested.

### B. Codex-Only Skill Logging

A Codex skill could append notes without changing the MCP server. This is
simpler, but it misses calls made by other clients, cannot reliably measure
duration or classify returned error envelopes, and depends on the agent
remembering to log every outcome. It is rejected as the primary evidence
source.

### C. External Telemetry And Evaluation Service

A separate service could aggregate multiple machines and support richer
analysis. It introduces deployment, authentication, availability, and data
governance requirements that are unnecessary for the current single-machine
workflow. It is out of scope.

## Architecture

```text
non-learning MCP tool call
    -> shared register_tool guard
       -> execute the original tool unchanged
       -> classify only metadata from the result or error envelope
       -> append a bounded invocation event
       -> refresh the backlog only when projected candidate state changes

Codex determines the requested goal was not achieved
    -> record_goal_failure with enum-only metadata
       -> correlate with the latest session invocation when available
       -> append a goal-failure event
       -> refresh the Markdown backlog
       -> critical class: return one immediate-attention signal
       -> ordinary class: remain silent until scheduled review

Monday 09:00 Asia/Shanghai scheduled review
    -> review_improvement_backlog
       -> return only new or reopened high-priority candidates
       -> no candidate: no attention request and no repository change
       -> candidate: concise reminder and approval request

approved remediation
    -> pscad-mcp-improver skill
       -> isolated branch or worktree
       -> reproduce with a failing test
       -> minimal implementation
       -> targeted and full verification
       -> reviewable commits
       -> user-controlled integration
```

The SQLite database is the source of truth. The Markdown file is a generated
projection and is replaced atomically. It is never parsed as authoritative
state, so manual edits cannot corrupt candidate aggregation.

## Package Structure

The implementation adds focused modules under `pscad_mcp/learning`:

- `config.py`: environment parsing, default paths, retention limits, and safe
  disablement when learning configuration is invalid.
- `models.py`: enums and immutable invocation, goal-failure, and candidate
  records.
- `store.py`: SQLite schema, transactions, retention, review watermarks, and
  clear operations.
- `recorder.py`: fail-open invocation classification, session correlation, and
  rate-limited logging of recorder faults.
- `candidates.py`: deterministic grouping, priority calculation, suppression,
  and reopen rules.
- `markdown.py`: complete, atomic rendering of the local improvement backlog.
- `service.py`: public learning operations independent of FastMCP registration.

`pscad_mcp/tools/learning_tools.py` defines the three MCP-facing functions.
`pscad_mcp/tools/registration.py` supplies invocation metadata to the recorder
after the original function completes. `pscad_mcp/main.py` registers the tools
and provides short server instructions for goal-failure reporting.

The implementation also adds
`.agents/skills/pscad-mcp-improver/SKILL.md`. The skill applies only to
reviewing and remediating accumulated PSCAD MCP evidence; it is not invoked
during normal successful operation.

## Configuration

The local learning configuration uses environment variables consistent with
the existing server configuration:

```text
PSCAD_MCP_LEARNING_ENABLED=true
PSCAD_MCP_LEARNING_DB=<optional absolute SQLite path>
PSCAD_MCP_LEARNING_BACKLOG=<optional absolute Markdown path>
PSCAD_MCP_LEARNING_RETENTION_DAYS=90
PSCAD_MCP_LEARNING_MAX_EVENTS=20000
```

On Windows, the default state directory is
`%LOCALAPPDATA%\pscad-mcp`. The default files are `learning.sqlite3` and
`improvement-backlog.md` inside that directory. On other platforms, the
implementation uses the platform state directory when available and otherwise
falls back to `~/.pscad-mcp`. Parent directories are created lazily on the
first event.

`PSCAD_MCP_LEARNING_ENABLED` accepts the same true and false spellings as the
existing boolean configuration. Retention must be 1 through 3650 days and the
event limit must be 100 through 1,000,000. Override paths must be absolute.

Learning is ancillary to PSCAD automation. An invalid learning setting or an
unavailable state directory disables the recorder for the current process and
emits one bounded warning. It must not stop server startup, alter a PSCAD tool
response, or trigger repeated warning output. The explicit review tool reports
that learning is unavailable and gives the configuration variable that needs
attention without returning raw filesystem or exception text.

## Event Schema

SQLite uses schema version 1 with four tables.

### `tool_invocations`

- integer event ID;
- UTC timestamp;
- random per-server-process session ID;
- registered tool name;
- integer duration in milliseconds;
- outcome: `success` or `error`;
- stable error code or null;
- retryable boolean or null;
- active backend name or null; and
- selected PSCAD version or null.

The backend snapshot is non-I/O. It reads already selected backend metadata and
must not call heartbeat, attach to PSCAD, create a backend, or access a vendor
proxy.

### `goal_failures`

- integer event ID;
- UTC timestamp;
- session ID;
- failure kind;
- validated primary registered tool name or null; and
- correlated invocation event ID or null.

Allowed failure kinds are:

- `unsupported_operation`;
- `incorrect_result`;
- `incomplete_result`;
- `environment_blocked`;
- `recovery_failed`; and
- `unknown`.

No free-text field exists. The primary tool name must match a non-learning tool
registered in the current server. When no primary tool is supplied, the
recorder may correlate the failure with the most recent non-learning invocation
in the same process session. It never guesses a project, component, parameter,
or user goal.

### `candidate_reviews`

This table stores candidate fingerprint, first and most recent notification
times, notification source (`foreground` or `scheduled`), and the evidence
watermark included in the last reminder. It prevents unchanged evidence from
requesting attention every week. A new event after the watermark reopens the
candidate.

### `schema_metadata`

This table stores schema version, created time, and the last completed
retention pass. Schema creation and supported migrations are transactional.
An unknown future schema version disables learning rather than modifying data.

## Privacy Enforcement

Privacy is enforced structurally rather than through redaction after capture:

- recorder methods accept typed scalar metadata only;
- no method accepts `args`, `kwargs`, result bodies, exceptions, messages,
  details, tracebacks, paths, or arbitrary mappings;
- SQLite has no general event JSON or text-payload column;
- the explicit failure tool accepts enums and a registered tool name only;
- Markdown is rendered exclusively from candidate records;
- warning logs contain a fixed category and exception class name, not the
  exception string; and
- tests inject unique secret, path, parameter, result, message, detail, and
  traceback sentinels and prove none appear in either persisted file.

The random session ID is regenerated on every server process start and is not
a user or machine identifier. No network client exists in the learning
package.

## Invocation Recording

`register_tool` takes a non-I/O backend snapshot, measures elapsed time with a
monotonic clock, and calls the original async function exactly once. Taking the
snapshot before execution retains useful context for disconnect and quit
operations. The wrapper then classifies the outcome:

- an ordinary return is `success`;
- a returned mapping with the stable top-level `error` envelope is `error`;
- an exception is converted with the existing `error_payload` behavior and is
  recorded from that stable envelope; and
- functions that already catch and return stable errors are classified the
  same as wrapper-generated errors.

Only `error.code`, `error.retryable`, and `error.backend` are eligible for the
event. `message`, `operation`, `details`, and `suggested_action` are never
passed to the recorder. Recorder or Markdown rendering failures are caught
after the original result has been determined and never replace that result.

The three learning tools are explicitly excluded from automatic invocation
recording. This prevents review and maintenance activity from affecting its
own evidence.

## Explicit Goal-Failure Hook

MCP cannot infer whether a technically successful result fulfilled the user's
engineering intent. `record_goal_failure` supplies this missing signal:

```python
record_goal_failure(
    failure_kind: Literal[
        "unsupported_operation",
        "incorrect_result",
        "incomplete_result",
        "environment_blocked",
        "recovery_failed",
        "unknown",
    ],
    primary_tool: str | None = None,
) -> dict[str, object]
```

FastMCP server instructions ask Codex to call this tool once, and only once,
when it has concluded that the requested PSCAD goal cannot be completed or was
not achieved. The instructions also require Codex not to mention learning,
telemetry, or backlog maintenance in normal user-facing narration.

Successful workflows do not call this tool. Depending on the host UI, a failed
workflow may still show a collapsed MCP tool call. The server cannot guarantee
that host-rendered tool activity is invisible, so the design promises no
routine user-facing prose or interaction, not removal of host audit UI. The
tool result includes `immediate_attention` only when the failure meets the
critical reminder rules below.

## Candidate Aggregation

Candidates use stable fingerprints derived only from candidate kind, tool
name, and stable error or goal-failure code. They never hash or retain user
content.

Candidate kinds are:

- `reliability`: timeouts, executor failures, internal errors, or failed
  recovery;
- `correctness`: explicit incorrect or incomplete result evidence;
- `capability`: explicit unsupported-operation evidence;
- `guidance`: repeated invalid argument, not-found, configuration, or recovery
  guidance failures; and
- `efficiency`: repeated retryable failures followed by recovery and success.

Within a rolling 30-day analysis window, ordinary invocation error groups need
at least three occurrences. An explicit goal failure, `incorrect_result`, or
`recovery_failed` is immediately actionable. The deterministic priority score
is:

```text
invocation evidence count
+ explicit goal-failure count * 3
+ incorrect-result count * 5
+ recovery-failed count * 5
```

Candidates sort by descending score, then most recent evidence, then stable
fingerprint. A candidate is suppressed when there are at least three relevant
successes after its last failure and no newer explicit goal failure. New
failure evidence after suppression or notification reopens it.

The candidate engine does not propose source edits. It reports candidate ID,
kind, primary tool, stable code, evidence counts, first and last observation,
priority, and state.

## Markdown Backlog

The generated file is named `improvement-backlog.md`. It begins with a local,
generated-file warning and contains `Open`, `Reopened`, `Notified`, and
`Resolved by later evidence` sections. Each candidate entry contains only:

- stable candidate ID;
- candidate kind and state;
- primary MCP tool;
- stable error or failure code;
- priority score;
- invocation and goal-failure counts;
- first and latest UTC observation;
- retryability when known; and
- a fixed next-action category such as reproduce, inspect guidance, add a
  capability, or verify recovery.

The renderer writes a sibling temporary file, flushes it, and atomically
replaces the backlog. A rendering failure leaves the previous complete file in
place. Clearing history regenerates a header-only backlog.

The file is local state, not a repository artifact. Documentation must warn
against committing it. If a configured backlog path is inside the repository,
`.gitignore` covers `.pscad-mcp/learning/` as the recommended local location.

## Public MCP Tools

Three tools are added, increasing the current inventory from 70 to 73.

### `record_goal_failure`

Records enum-only semantic failure evidence as defined above. When learning is
disabled it returns `{recorded: false, learning_enabled: false}` without
turning the original failed workflow into a second failure.

### `review_improvement_backlog`

Inputs are `limit: int = 10`, `min_evidence: int = 3`, and
`mark_notified: bool = False`. Bounds are 1 through 100 for both numeric
inputs. The result contains learning availability, aggregate counts,
`attention_required`, and bounded candidates.

With `mark_notified=false`, it is a read-only inspection. A scheduled review
calls once with `mark_notified=true`, reports exactly the candidates returned
by that call, and leaves all unreturned candidates unchanged. Notification
watermarks change only for returned actionable candidates.

### `clear_learning_history`

Input is `confirm: bool = False`. Without exact confirmation it returns the
existing stable confirmation-required error. With confirmation it
transactionally clears event and review tables, performs SQLite maintenance,
and atomically regenerates the header-only Markdown backlog. It never deletes
an arbitrary user-supplied path.

## Silent Foreground Behavior

No successful PSCAD tool response gains a learning field. No status call gains
a learning panel. No progress message, reminder, candidate count, or feedback
request is emitted during normal use. Learning writes happen after the tool
result has been determined and are bounded local operations.

The only foreground learning call is the explicit semantic failure hook after
Codex has already concluded that the requested goal failed. Technical errors
are captured entirely inside the wrapper. Ordinary failure candidates remain
silent until the scheduled review.

## Immediate Reminder Exception

Operational and safety errors returned by existing PSCAD tools are never
hidden. In addition, Codex may give one concise backlog reminder in the current
task when any of these conditions is present:

- the stable error is `PARTIAL_COMPLETION` or otherwise proves a requested
  mutation only partly completed;
- connection repair or owned-process cleanup failed, including
  `REPAIR_CLEANUP_FAILED`;
- Codex records `incorrect_result` after checking the result against the
  requested engineering outcome;
- Codex records `recovery_failed`; or
- a previously notified high-priority candidate has new evidence and is again
  blocking the current goal.

The reminder contains only the candidate ID, fixed category, and a choice to
inspect now or leave it for the consolidated review. It does not include stored
tool arguments or results and does not start remediation automatically. The
foreground notification watermark permits at most one reminder per candidate
and evidence watermark; unchanged failures cannot repeat the reminder in the
same or later task.

Routine invalid arguments, missing names, isolated timeouts, learning-storage
faults, and failures followed by successful recovery do not generate an
immediate learning reminder. Their original tool error remains visible and
their improvement evidence waits for the weekly review.

## Scheduled Review

The desktop scheduled task uses this cadence:

```text
Timezone: Asia/Shanghai
RRULE:FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0
```

The task invokes the `pscad-mcp-improver` skill in review-only mode and calls
`review_improvement_backlog`. When `attention_required=false`, it performs no
repository write and produces no attention request. The completed run may
still be visible in the product's Scheduled history; the server cannot hide
host task history.

When findings exist, the task returns a concise reminder containing candidate
IDs, categories, affected tools, evidence counts, and priority. It asks the
user whether to start a consolidated remediation batch. It does not edit code
before that approval.

If review is unavailable because learning is intentionally disabled, the task
does not notify. If an enabled review cannot access its state for two
consecutive scheduled runs, the second run reports that monitoring is
unavailable without exposing a filesystem path or raw error.

Official OpenAI documentation states that desktop scheduled tasks can run in
local projects or isolated worktrees, combine with skills, and use a durable
prompt to decide whether anything important should be reported:
<https://learn.chatgpt.com/docs/automations>.

The machine must be powered on, the desktop app must be running, the repository
must remain available, and the configured MCP server must be usable at the
scheduled time. The first few runs must be reviewed before relying on the
cadence unattended.

## Consolidated Remediation

After explicit user approval, the skill performs one remediation batch for the
approved candidates:

1. Create or use an isolated `codex/` branch or worktree.
2. Re-read current evidence and group candidates by root cause.
3. Ignore candidates that cannot be tied to a reproducible behavior.
4. For each root-cause group, write the smallest failing regression test and
   run it to verify the expected failure.
5. Implement the minimum source or documentation change that passes the test.
6. Run targeted tests after each group and keep each group in a separate
   reviewable commit.
7. Run the complete default suite, package verification, compilation, and
   dependency checks after the batch.
8. Run licensed PSCAD acceptance only when the existing acceptance opt-in and
   approved isolated paths are configured.
9. Present the evidence, commits, verification output, and remaining backlog
   without merging or pushing.

A failure in one group stops dependent work but does not erase completed,
verified commits for independent groups. Unreproduced items remain in the
backlog with a fixed `needs_evidence` action and no speculative patch.

The skill may improve `AGENTS.md` or its own instructions only when a repeated
workflow mistake is demonstrated. It may not use a backlog candidate alone to
weaken confirmations, path containment, process ownership, timeout handling,
or real-acceptance requirements.

## Error And Concurrency Behavior

SQLite uses short transactions, a busy timeout, and WAL mode where supported.
Retention and Markdown refresh are serialized by the learning service, while
PSCAD calls retain their existing concurrency and mutation locks. Learning
does not acquire a PSCAD lock and PSCAD does not wait for a retry loop on the
learning database.

Automatic recording is fail-open. Explicit review and clear operations return
bounded stable errors when local state cannot be accessed. They never include
the raw database path or exception text in MCP output.

Retention runs at lazy initialization and at most once per UTC day. It deletes
events older than the configured age, then oldest remaining events above the
configured maximum. Orphaned goal-failure correlations become null rather
than blocking retention. Candidate review watermarks with no remaining
evidence are removed.

## Testing Strategy

### Configuration Tests

- Verify metadata collection is enabled by default.
- Verify explicit disablement performs no file creation.
- Verify default and absolute override paths.
- Verify retention and event-limit bounds.
- Verify invalid ancillary configuration disables only learning.

### Store And Retention Tests

- Create and migrate schema version 1 transactionally.
- Record invocation and goal-failure events.
- Exercise concurrent short writes and busy handling.
- Delete by age and maximum event count deterministically.
- Preserve referential behavior when old invocations are removed.
- Clear all history only after confirmation.
- Reject an unsupported future schema without altering it.

### Privacy Tests

- Inject unique sentinels into tool arguments, project paths, result bodies,
  error messages, error details, suggested actions, and tracebacks.
- Verify none of those sentinels appear in SQLite bytes, queried rows, the
  Markdown backlog, warnings, or MCP learning-tool results.
- Verify goal failures reject unknown tool names and arbitrary failure kinds.
- Verify there is no general JSON or free-text event column.

### Registration Tests

- Record ordinary success, returned stable error, and raised exception.
- Preserve each original tool result exactly.
- Call each original tool exactly once.
- Prove recorder and renderer failures cannot replace tool results.
- Read backend/version without heartbeat or backend creation.
- Exclude all learning tools from automatic recording.

### Candidate And Markdown Tests

- Enforce the three-event ordinary threshold.
- Promote explicit goal, incorrect-result, and recovery-failed evidence
  immediately.
- Verify scoring, deterministic ordering, notification watermarks, reopening,
  success suppression, and retention.
- Verify each foreground evidence watermark can trigger at most one immediate
  reminder and that routine failures never do.
- Verify scheduled review returns and marks one identical bounded candidate
  set, and reports an enabled-but-unavailable monitor only on the second
  consecutive run.
- Verify exact bounded Markdown fields and atomic replacement.
- Verify clearing produces only the generated header.

### MCP And Packaging Tests

- Validate tool signatures, bounds, confirmation, and disabled behavior.
- Update the exact tool inventory contract from 70 to 73.
- Include the learning package and project skill in source and wheel checks as
  appropriate.
- Document configuration and privacy behavior in English and Chinese READMEs,
  `config.example.toml`, and the changelog.
- Keep install smoke tests independent of PSCAD and optional Windows packages.

### Full Verification

- Run targeted learning tests first.
- Run `python -m pytest -q`.
- Run `scripts/verify_package.ps1`.
- Run `python -m compileall -q pscad_mcp tests`.
- Run `python -m pip check`.
- Run `git diff --check`.

The learning feature does not itself justify launching PSCAD in the default
suite. Existing opt-in licensed acceptance remains the only evidence for real
PSCAD behavior.

## Rollout

Stage 1 implements configuration, storage, privacy enforcement, silent
instrumentation, the three MCP tools, Markdown projection, tests, and
documentation. It is complete only when normal tool results are byte-for-byte
equivalent at the Python object boundary with learning enabled, disabled, and
faulted.

Stage 2 adds and manually tests the project remediation skill against synthetic
candidate fixtures. The skill remains dormant during ordinary usage.

Stage 3 creates the Monday 09:00 scheduled review only after Stages 1 and 2
pass. The first scheduled run is invoked manually, and the first few automatic
runs are reviewed as recommended by the official OpenAI documentation. The
schedule is paused if it creates empty attention notifications or touches the
repository without approval.

## Completion Criteria

The design is implemented when all of the following are true:

- every non-learning tool emits bounded metadata without changing its result;
- successful operation has no learning-related user-facing text or extra MCP
  call;
- explicit failed goals create enum-only evidence and refresh the Markdown
  backlog;
- neither persisted file can contain tool parameters, results, paths, prompts,
  exception text, details, or tracebacks;
- recurring failures produce deterministic, deduplicated candidates;
- unchanged notified candidates do not request attention every week;
- the Monday 09:00 `Asia/Shanghai` review reports only actionable findings;
- defined critical failures may produce one immediate reminder while routine
  failures remain silent;
- no scheduled review edits source code before explicit user approval;
- approved remediation uses an isolated branch or worktree and failing tests
  before production changes;
- no automated step merges, pushes, publishes, deploys, or weakens safety;
- history can be disabled, relocated, inspected, and cleared;
- the exact MCP tool inventory is 73; and
- all targeted, full, packaging, compilation, dependency, and diff checks
  pass.
