# Five-Arrester Concurrent Acceptance

## Final Delivery Revision

The final user-facing models are in
`C:/Users/335/Documents/PSCAD-MCP/five_arresters_20260908/delivery-v2`.
They include expanded native graphs, instance-level axis persistence, branch
labels, and a relative-path workspace that was loaded in a relocated directory.

Final tested code revision: `bd7770ed882e3777944060f4892256a8d8667d97`.
Final runner SHA-256: `901e749d69f022bf6a8dd96127906a3b36642296e78ef2772c70964a8b9dd2e0`.
Final report: `delivery-v2/acceptance/20260908-111611/acceptance.json` under the
source directory above. Its SHA-256 is
`fbb6060a6774942b3af51172d52712c2abbca1f0c64efcabc721874a8d3d0d9c`.
Both cases passed all physical checks, immutable inputs remained unchanged,
owned PSCAD PID 6536 exited and no owned EMTDC process remained.

Independent review identified optimized-Python assertion bypass and cleanup
failure handling gaps. These were reproduced and fixed. Tests also verify
Python 3.10-compatible cleanup and that `0.010` and `0.01` are equivalent while
`0.02` is still a physical setting change. All 25 focused regression tests and
static checks passed. The failed numeric-format attempt is retained at
`delivery-v2/acceptance/20260908-110450/acceptance.json`.

Native circuit and graph rendering was verified at
`delivery-v2/native_preview/20260908-110450/preview_report.json`, including
correct axis ranges on reloading without runtime zoom adjustments.

The following sections retain the earlier acceptance record; the final report
above supersedes it.

The user requested five parallel arrester branches, each with a series switch,
with only one branch working at a time. Both forward and reverse schedules
passed licensed PSCAD 4.6.2 x64 / GFortran 4.2.1 simulation using illustrative
nonlinear I-V curves and ideal commanded switching.

## Revision and Isolation

- Worktree: `D:/pscad-mcp/.worktrees/five-arrester-validation`.
- Branch: `codex/five-arrester-validation`.
- Tested repository revision: `a759a468933109af2169bcc2d67ad4e977a3deb2`.
- Required concurrent fix `db65d74` is an ancestor of that revision.
- Runner: `scripts/accept_five_arresters.py`.
- Tested runner SHA-256: `74f2273611ca8ad880c8ce8601fc309da60735c10df5b0d551f70f303ff91f71`.
- Process-local flags: `PSCAD_MCP_ACCEPTANCE=1`, `PSCAD_MCP_ACCEPTANCE_CONCURRENT=1`.
- Source: `C:/Users/335/Documents/PSCAD-MCP/five_arresters_20260908`.
- Fresh output: `C:/Users/335/Documents/PSCAD-MCP/five_arresters_20260908/acceptance/20260908-103455`.

The source models, Master library, compiler and analysis script were hashed
before the run and unchanged afterward. Copies were compiled in the unique
output directory. Only GUI channel streaming was disabled in the copies;
electrical component, wire and integration-setting signatures matched the
delivered models before and after PSCAD save. All disk channels were retained.

## Evidence

Final report: `C:/Users/335/Documents/PSCAD-MCP/five_arresters_20260908/acceptance/20260908-103455/acceptance.json`.

Report SHA-256: `5680d02e25c35513e9026036f02cf13abdffe3c012dab6aea0888cd9322a2203`.

| Check | Result |
| --- | --- |
| Both cases compile and run | PASS |
| Samples per case, 0-10 ms at 1 us | 10,001 |
| Closed switches at each sample | Exactly one |
| Concurrent arrester currents above 1 A | At most one |
| Active steady current | 1.000-2.830 kA |
| Largest inactive steady current | 0.000097091 A |
| Maximum KCL mismatch | 2.704e-9 A |
| Immutable input hashes | Unchanged |
| Owned PSCAD PID 33816 after cleanup | Exited |
| Owned EMTDC executables after cleanup | None remain |

The initial source ramp contains a few samples below the 1 A working-current
threshold. Inactive branches have finite leakage; they are not identically zero.

Regression command: `python -m pytest tests/test_concurrent_acceptance.py tests/test_acceptance_powershell.py -q --tb=short`.
Result: 17 passed. Runner Ruff check also passed.

## Failure Resolution

The first concurrent attempt failed because the connection manager was
imported before the process-specific workspace environment was set. It could
launch an owned instance but rejected file loading. The report and ownership
cleanup are retained at `acceptance/20260908-103159/acceptance.json` under the
source directory. The import was moved after environment initialization.
The final fresh report supersedes that failed attempt; no electrical threshold
was changed, and no failed check was skipped.

This acceptance establishes exclusive switching in the illustrative model.
It does not establish physical DC interruption, commutation hardware,
stray-inductance overvoltage, manufacturer ratings, thermal capacity or
standard lightning-impulse performance.
