# Concurrent PSCAD Acceptance

Two independent acceptance workers may run on the same Windows machine when
`PSCAD_MCP_ACCEPTANCE_CONCURRENT=1` is set in each worker's environment. This
implements the instance-isolation approach agreed in the conversation.

Each worker launches its own Legacy PSCAD instance, uses its own executor and
unique workspace, and records the PID returned by that instance. Global process
inventory remains visible as evidence, but another worker's process does not
invalidate startup or cleanup in concurrent mode. Unknown ownership cannot
produce a PASS. No process is killed to make acceptance pass. Normal mode keeps
the current exclusive checks and all existing license and physical checks.

Scope: legacy and topology acceptance, LCC native/fixed acceptance, LCC/MMC
preflight, and offline dynamic-evidence evaluation. Existing active worktrees
must receive the change before their runners support the new mode. This does
not make multiple callers safe on one PSCAD instance or add modern acceptance.

Validation includes two overlapping lifecycle tests, owned-process leak and
missing-PID failures, launch ownership races, PowerShell parsing, regression
tests, and an opt-in two-process licensed preflight against independent paths.
Real-machine results are reported separately from mocked contract tests.
