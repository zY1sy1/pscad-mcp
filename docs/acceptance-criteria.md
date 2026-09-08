# Acceptance Criteria and Failure Resolution

## Scope

These rules apply to PSCAD model delivery and MCP implementation. They govern
the task lifecycle; they do not replace electrical/model-specific contracts,
licensed-run opt-ins, or existing machine-readable report schemas.

## Completion

Declare acceptance complete only when the requested behavior has fresh evidence
from the delivered revision and model, the required physical checks pass, source
inputs retain their hashes, artifacts can be loaded and traced, and all owned
runtime processes have exited. Mocked tests do not establish licensed PSCAD
acceptance. A build alone does not establish simulation or physical correctness.

If code or model inputs change after a run, rerun the affected acceptance. Scope
the rerun to the changed behavior and shared contracts; unrelated costly gates
need not be repeated without a dependency or evidence reason.

## After an Unsuccessful Attempt

1. Preserve the failing report, error code, revision, model/input hashes,
   process ownership, and relevant outputs before changing anything.
2. Identify the cause and classify it using the table below.
3. Reproduce a software defect with a focused regression test where feasible;
   for physical/model failures, use channel traces and the governing contract.
4. Repair the cause within the user's authorized scope, then rerun the failed
   check and relevant regressions. Continue while useful local work is possible.
5. Keep the failure evidence and link the fresh result that supersedes it.

| Cause | Required response | Task outcome |
| --- | --- | --- |
| Another task owns a PSCAD instance | Use verified independent instances, or wait for resource release with visible status | Pending, not a model failure |
| Transient owned-session timeout or startup error | Inspect ownership/state; repair or restart only the owned instance and retry after the cause changes | Continue diagnosis |
| Reproducible script, MCP, report-validator or model defect | Correct the defect and repeat affected acceptance | Continue until accepted or a real blocker is demonstrated |
| Electrical criteria fail | Diagnose the operating point, topology, controls, units and waveforms; repair and rerun | Never relax a threshold just to pass |
| Missing license, unavailable vendor capability, missing immutable source or required user decision | Complete independent work and report the exact missing prerequisite and evidence | Blocked; never PASS |

Do not repeatedly run the same failing command without changing a hypothesis,
input or environment. A blocked report must distinguish observed facts from an
unverified hypothesis (for example, a second launch failure alone does not prove
the license prohibits a second instance). State what would permit resumption.

An existing JSON report may record `status: FAIL` for any failed attempt. This
is an attempt verdict, not an instruction to abandon the task. Explain pending
or externally blocked work separately rather than inventing unsupported JSON
status values. Do not fabricate a passing result when acceptance is unavailable.

## Independent Concurrent Runs

Supported updated runners opt in with `PSCAD_MCP_ACCEPTANCE_CONCURRENT=1` in
each worker's process environment. Do not set a machine-wide variable. Each
worker must have its own Python process, PSCAD connection, executor, and
non-overlapping output/project directory. Keep automation calls serialized
inside each instance. The vendor-returned managed PID identifies ownership;
unknown ownership is an error. Foreign PSCAD processes are not leftover
processes of this run. Never stop or attach to them to make a gate pass.

The setting changes process isolation checks only. It grants no license and
does not waive physical, compiler, source-hash, revision, or cleanup checks.
Older worktrees must receive the runner changes before using this mode.
Exclusive mode remains available for troubleshooting and unsupported runners.

The opt-in concurrent lifecycle test uses two Python processes and two licensed
PSCAD instances. It requires `PSCAD_MCP_ACCEPTANCE=1`,
`PSCAD_MCP_CONCURRENT_ACCEPTANCE_TEST=1`, and an absolute `PSCAD_MCP_WORKSPACE`
for durable per-worker reports, then runs
`python -m pytest tests/test_concurrent_acceptance_real.py -q -s`.
It proves overlapping connections and independent cleanup, not acceptance of
any particular electrical model.

Static evaluation of already-produced evidence must not require the machine to
be free of PSCAD processes. The sampled inputs must be finalized and immutable;
never evaluate another task's output while it is being written.

## Handoff

Report what was accepted, the exact revision and evidence location, checks run,
and any remaining unverified scope. If blocked, give the cause, attempts and
their outcomes, and the minimal next prerequisite. "Tests passed" cannot stand
in for missing model acceptance, and "acceptance failed" cannot stand in for
the required diagnosis and repair work.
