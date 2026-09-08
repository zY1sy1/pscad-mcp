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
- [ ] Run regression checks and independent code review; resolve findings.
- [ ] Run a two-process licensed preflight if local runtime permits it.
- [ ] Document activation and verification limits; integrate the reviewed fix.
