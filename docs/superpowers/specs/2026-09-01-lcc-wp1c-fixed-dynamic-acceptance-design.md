# LCC WP1C Fixed Dynamic Acceptance Design

**Date:** 2026-09-01

**Scope:** `lcc.fixed_autonomous` dynamic acceptance only

**Goal:** Extend the fixed LCC acceptance path with a durable licensed disturbance and recovery report while preserving the rule that missing independent golden evidence yields `INCOMPLETE_ANALYSIS`, never `accepted`.

## Context

WP1B currently proves the fixed companion library, full topology, final reload/compile, and a short no-fault smoke. The shared LCC acceptance module already evaluates explicit commutation-fault evidence and physical channel contracts, but `fixed_acceptance.py` only models the WP1B smoke report. WP1C needs a separate report contract so the existing WP1B evidence remains immutable and its schema remains stable.

## Design

1. Add `dynamic_acceptance.py` beside `fixed_acceptance.py`.
   - Define a strict report schema for the same repository/source/preflight identity fields as WP1B plus a `dynamic` record.
   - Require disturbance timing, required channel descriptors, physical evidence, recovery evidence, and a golden declaration.
   - Reuse `evaluate_commutation_fault()` and `evaluate_acceptance()` from `acceptance.py` for waveform/physical evaluation.
   - Compute the final status as `PASS` only when physical checks and an independently reviewed golden both pass. With valid physical evidence and an absent or placeholder golden, return `INCOMPLETE_ANALYSIS` and retain the report; missing required channels or failed physical checks return `FAIL`.
   - Verify report files and commit identity before any baseline promotion. Promotion is limited to the existing scope and uses `INCOMPLETE_ANALYSIS` until WP6 supplies the golden.

2. Add `dynamic_acceptance_cli.py` and `run_fixed_lcc_dynamic_acceptance.ps1`.
   - Reuse the fixed builder's isolated workspace, Legacy PSCAD session, component gate, topology build, and cleanup behavior.
   - Use a long enough schedule to cover steady state, an inverter AC disturbance, commutation-failure indication, and recovery; record exact time-domain/channel metadata.
   - Persist setup, build, simulation, and cleanup failures as durable reports. Never terminate unrelated PSCAD processes.

3. Keep the existing asset contract as the source of channel names and physical thresholds, adding only the dynamic event/recovery declarations needed by WP1C. Do not modify the packaged golden placeholder or mark it reviewed.

4. Update the roadmap and Chinese/English status docs to state that WP1C is implemented as a dynamic evidence gate but remains `INCOMPLETE_ANALYSIS` until an independent golden is reviewed. Record the current-commit baseline transition only when a licensed run actually succeeds.

## Testing

- First add unit tests for strict dynamic report validation, status gating, missing-channel handling, recovery evidence, and baseline promotion refusal for placeholder golden data.
- Add CLI/runner tests for argument construction, current commit/branch binding, durable failure reports, and cleanup evidence.
- Run focused tests, then the complete repository suite and fatal Ruff checks.
- Run the licensed PowerShell runner only when PSCAD 4.6.2, the compiler, and a clean named worktree are available; preserve the resulting report and hashes for review.

## Explicit Exclusions

- No final `accepted` promotion.
- No independent golden generation or review (WP6).
- No parametric LCC or MMC work.
- No changes to the official PSCAD template, installed Master, or existing WP1B evidence.
