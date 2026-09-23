# MMC Native Evidence Closure Implementation Plan

**Goal:** Complete the remaining independent MMC signal audit and acceptance
preparation, repair reproducible native scenario/evidence defects, and verify
the changed behavior with fresh evidence without interfering with LCC WP1C.

**Architecture:** Keep changes inside the MMC native path. Reuse the existing
XML/OUT parsers, immutable derived projects, Master metadata and managed-PID
acceptance lifecycle. Static records and real runs retain separate identities.
No physical thresholds or independent-reference requirements are relaxed.

**Tech Stack:** Python, pytest, ElementTree, PSCAD 4.6.2 Legacy Automation.

The user authorized continuation and supplied the current AGENTS.md acceptance
rules. Read `docs/acceptance-criteria.md` and the LCC/MMC roadmap before execution.
Use subagent-driven-development for the independent audit and reviews; execute
the coupled native corrections in order in this worktree.

- [x] Read acceptance criteria and retain the prior pre-audit at baseline
  `d226c2d`; fast-forward this branch to `a759a46` for concurrent ownership support.
- [x] Verify affected baseline: 43 passed, 1 skipped across native MMC,
  blank MMC, acceptance and concurrent lifecycle tests.
- [x] Audit all 177 finalized historical channels against INF/INFX and the
  corresponding source project/library. Record units, dimensions, instance
  identity, PGB owner, signal source, output part, samples, domain and hashes.
  Complete the required/missing channel table and the feasible/infeasible
  request matrix in `docs/audits/2026-09-08-mmc-native-followup/`.
- [x] Reproduce the ignored duration with a focused regression in
  `tests/test_mmc_template_native.py`: actual `Main/master:tfaultn.DF` must change
  to the requested duration; an unused `Station` definition must not determine
  the runtime schedule. Observe RED before changing implementation.
- [x] Correct timing binding in `mmc/template_native.py`, preserving the
  source, recording the actual owner and parameter, and rejecting missing or
  ambiguous active timers. Reject non-finite/negative timing requests.
- [x] Reproduce and repair evidence selection/polarity/unit defects with
  focused native-evaluator tests. Preserve incomplete evidence and selected
  channel identities; station ambiguity must not silently choose a convenient
  waveform. Do not replace missing measurements with reference/command values.
- [x] Prepare physical output channels in an isolated native project only
  where their source, polarity and units are established by the native model.
  Verify the generated XML before loading it; do not infer voltage from PWM
  orders or capacitor sums alone.
- [x] Run a managed independent PSCAD instance in its own workspace using
  process-local acceptance opt-ins and the vendor-returned managed PID. Verify
  the corrected schedule and measurement output; diagnose any unsuccessful
  result before deciding the next attempt. Preserve all failed reports.
- [x] Run focused regression and independent spec/code review, then the
  affected broader suite. Record the delivered revision, artifact hashes,
  source immutability and owned-process cleanup. List any remaining external
  prerequisite precisely; do not claim model acceptance without its checks.

## Commands

Use `D:/pscad-mcp/.venv/Scripts/python.exe` with this worktree as cwd.

```powershell
& 'D:\pscad-mcp\.venv\Scripts\python.exe' -m pytest -q --tb=short tests/test_mmc_template_native.py
& 'D:\pscad-mcp\.venv\Scripts\python.exe' -m pytest -q --tb=short tests/test_blank_mmc_service.py tests/test_mmc_acceptance.py tests/test_mmc_template_audit.py tests/test_concurrent_acceptance.py
```

New licensed runner code must require `PSCAD_MCP_ACCEPTANCE=1`, use
`PSCAD_MCP_ACCEPTANCE_CONCURRENT=1` only in its own process environment, verify
ownership before model work, and shut down only its managed instance. The
current generic parametric MMC acceptance test has not been upgraded for
concurrent ownership and must not be assumed to support that mode.

## Outcome

Code revision `2876c48` passed the scoped licensed native fault/probe run.
The first metadata-reading failure was preserved, fixed through a regression,
and superseded by a fresh complete run. Final offline suite: 2482 passed,
48 skipped. Independent audit reproduced the physical probe observations and
verified 377 hash paths plus owned-process cleanup.

See [the scoped delivery record](../../acceptance/mmc-native-probes-20260908.md).
Overall MMC physical/release acceptance and independent golden remain outside
this completed parallel preparation and diagnostic scope; no program baseline
or accepted flag was promoted.
