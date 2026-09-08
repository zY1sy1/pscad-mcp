# Concurrent Acceptance Implementation Plan

**Goal:** Permit independently owned PSCAD acceptance instances to overlap.
**Architecture:** One process-local opt-in controls acceptance startup policy;
cleanup filters by the vendor-returned managed PID, never a global PID delta.
**Tech Stack:** Python, asyncio, pytest, PowerShell, PSCAD Automation Library.

- [x] Inspect backend ownership, acceptance scripts and report contracts.
- [x] Verify baseline: 70 focused tests passed.
- [x] Add failing tests for foreign-process tolerance and owned-process leaks.
- [x] Implement shared acceptance process policy and wire lifecycle factories.
- [x] Update PowerShell guards and legacy acceptance PID attribution.
- [x] Run regression checks and independent code review; resolve findings.
- [x] Run a two-process licensed preflight if local runtime permits it.
- [x] Document activation and verification limits; integrate the reviewed fix.

Final main-workspace verification: 2418 passed, 48 skipped. Licensed concurrent
lifecycle test: 1 passed on PSCAD 4.6.2 x64. See
`docs/acceptance/concurrent-acceptance-20260908.md` for scope and evidence.
