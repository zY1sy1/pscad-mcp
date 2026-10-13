# General parameter sweeps and constrained selection

User authorized this feature on 2026-10-13. Start from main `94c305c` in
`codex/parameter-sweep-workflow`. Existing source-checkout work is preserved.

Reuse SweepSpec and the established source-copy, evidence and cleanup contracts.
Unlike the earlier caller-driven proposal, campaigns run as background asyncio
tasks with durable checkpoints and an explicit cancellation request. Each attempt
gets its own PscadService, backend, COM executor and PSCAD instance. Ordinary
interactive tools retain their own service. Campaigns sharing a workspace use an
OS-held exclusive lease; live orphaned owned processes prevent resumption.

Add plan/create/run/status/cancel/resume/analyze tools in a `sweep` profile.
Planning and creation are offline; execution requires reviewed source hashes and
explicit confirmation. Source projects and libraries remain immutable. No
automatic retry, external-process termination or unverified legacy reattachment.
Resume retains successful results and creates append-only retry attempts.

Analysis compares bounded channel statistics and ranks evaluated scenarios under
explicit numerical constraints. It never claims a global optimum or physical
model acceptance. Missing channels and changed evidence fail explicitly.

Verify isolation, continuation after failure, cancel/resume, orphan handling,
cross-process leasing, read-back/restoration, source and evidence integrity,
output freshness and numerical calculations. Run the full offline suite, lint,
package checks and an opt-in licensed 4.6.2 campaign. Licensed acceptance remains
pending until the existing opt-in and an approved source are available.
