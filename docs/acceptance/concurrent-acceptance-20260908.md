# Concurrent Acceptance Verification, 2026-09-08

Code revision: `db65d740cf3e6f530e861a34b34c8d7c2506d035` (integrated into main).
The subsequent documentation-only commit records these results without changing
the code exercised by the tests.

## Results

- Main-workspace regression: **2418 passed, 48 skipped**, 48.86 seconds.
- Ruff fatal-error checks: passed. Seven PowerShell files parsed successfully.
- Native stdout/stderr and exit-code tests passed in Windows PowerShell 5.1
  and PowerShell 7, for both successful and failing native commands.
- Licensed concurrent lifecycle: **1 passed**, 8.47 seconds, PSCAD 4.6.2 x64.
- Worker 1 owned PID 32596. Worker 2 owned PID 40200.
- Worker 2 started after worker 1 published readiness; its initial process
  inventory recorded worker 1. Both independently reported a valid license.
- Both workers observed overlapping live instances. Worker 2 remained alive
  and responsive after worker 1's successful shutdown.
- Both reports contain empty remaining-process lists. Both supervisor reports
  record `forced_cleanup: false` and no cleanup errors. Follow-up PID checks
  found neither owned process running.

## Evidence

Run directory:
`D:/PSCAD-Workspace/acceptance/concurrent-validation/concurrent-f24f112e62264d46a87619d4d1f809aa`

| Report, relative to run directory | SHA-256 |
| --- | --- |
| `worker-1/report.json` | `a3faab0aaa565f5d29c3ea56a5b5c0e8ef3ae321ff80cd9ff9fa09cd8ddf7748` |
| `worker-2/report.json` | `ed705b1cf2538598ef264b3fd671b17f9b8b281550a56cee97b77444ea4f07c1` |

Each worker also retained readiness, overlap, and supervisor-cleanup records.

## Limits

This evidence establishes independent concurrent session startup, licensing,
responsiveness and cleanup. It does not certify a particular circuit's build,
simulation outputs, physical behavior, all licensed gates, or PSCAD 5.x.
Existing older worktrees must synchronize the code before enabling concurrent
acceptance. Original license and model-specific opt-ins remain required.

Independent review identified native stderr handling, truncated process
inventory, setup-failure cleanup, live overlap coverage, and supervisor cleanup
issues. These were addressed with focused regressions and the licensed test.
