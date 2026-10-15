# Completed-work main integration (2026-10-15)

The completed detailed-PWM and overhead-AVM histories are integrated into local
`main`, starting from `a8fce2dd0ec2a4060e4234f5fa721199ab69d0cc`. The tested
runtime merge is `301c5c9fbb34ddfbe84322528ab77137415d3fe9`; subsequent changes
update documentation, implementation-status metadata and its assertions only.
No remote push is included.

## Integrated scope

| Source | Preserved tip | Included behavior |
| --- | --- | --- |
| `codex/mmc-detailed-pwm` | `ae4543eef41559ec520681e85a7f6864a9a87687` | Audited full-bridge reference, real controls and faults, 337 channels, frozen physical validation, independent reload and publication with compiler libraries |
| `codex/mmc-overhead-avm` | `31c222bf808d35365592d081480ecfe29a681d9b` | Request-specific native source discovery, audited overhead geometry, native line constants, physical RC damping and three full-bridge ratings |

Both histories remain reachable. Four conflicts retain both sets of accepted
behavior: actual PWM cell-count/loading derivation, medium-specific AVM line
parameters, isolated PWM publication and all ten accepted MMC request records.
The parent parametric MMC scope remains `PARTIAL`.

The October Legacy, Blueprint, cable AVM, Corpus and sweep histories were already
integrated. The inventory now also marks their implementation as `MERGED`,
while retaining every request, report hash, evidence commit, physical check and
licensed verdict. Earlier main snapshots remain historical records.

## Verification and behavior comparison

- Complete offline suite: **4180 passed, 55 skipped**, 335.63 seconds. The skips
  retain their existing license/environment conditions. All 99 affected
  documentation/inventory checks pass again after the final metadata update.
- Fresh wheel build and installation in a separate virtual environment pass:
  **112 tools, 9 LCC assets, 8 MMC assets**. All **235 installed Python modules**
  match the tested source bytes. Dependency checking and compilation pass.
- All ten accepted requests retain identical candidate parameters, settings,
  physical constraints, scenario lists, bindings and dependencies when planned
  in separate Python processes against their source and integrated checkouts.
- Seventeen PWM runtime files and sixteen AVM runtime files match their source
  branches after newline normalization. Shared planner/derivation changes are
  covered by the request comparisons and regression suite.
- The shared TLI renderer removes a second ground-wire position when `NG=1`.
  The initial text comparison correctly detected this difference. Both old and
  merged inputs were regenerated with the installed `tline` utility: `TL12a`
  and `TL12b` produce byte-identical constants and numerical output. The log
  difference removes only the previously ignored `P2` warning; installed
  source hashes remain unchanged. This affected contract was rerun, with no
  resulting electrical-input change requiring unrelated scene reruns.
- Final evidence inventory: **24 VERIFIED, 2 NO_DURABLE_REPORT, 0 INVALID**.
  `mmc_stage_a` and `modern_core_5` retain their missing-report boundaries;
  the complete inventory remains `INCOMPLETE`.

Logs, independent comparison scripts and artifacts are preserved under
`D:/PA/integration-main-20261015`. The committed
[verification record](main-integration-20261015.json) indexes their hashes,
including the full JUnit report and the initially detected TLI difference.
The main checkout's pre-existing untracked files are recorded separately in
`main-before.json`; the post-fast-forward audit is `final-state.json` in that
evidence directory. The original main is retained as
`backup/main-before-completed-20261015`.

## Physical evidence boundaries

The [detailed-PWM reference](mmc-detailed-pwm-20261015.md) passes eleven scenes,
untimed delivery and independent reload: **5698 physical checks**. A separate
published-file run passes another **404**. Electrical producer `d0e547d` and
publication repair `95655d1` retain their exact evidence identities. Other PWM
ratings, half-bridge topology and both-fidelity requests are not qualified by
this reference.

The [three overhead AVM requests](mmc-overhead-avm-20261014.md) retain their
eighteen normal/fault/reload stages at `7432030`. Together with the six cable
AVM requests, these form nine AVM scopes distinct from the one PWM reference.
Neither topology claims intrinsic fault blocking without external isolation.

[Sweep cancellation, cross-process recovery, crash/orphan guards and metrics](sweep-recovery-and-metrics-20261014.md)
already have scoped evidence at `144ba5f`; the previous main snapshot's pending
cancellation/restart wording is superseded. PSOUT coverage remains existing-file
replay, with fresh PSOUT-producing simulation and the full sweep still pending.
LCC physical mappings, the independent fixed-LCC reference, wider MMC/Blueprint
coverage and the missing original Corpus Master 4.6.3 remain separate work.
PSCAD 5.x retains its existing exclusion and lack of live evidence.

This integration runs offline verification and the affected native constants
generation. It does not relabel old reports as new-main electrical acceptance.

## Preserved alternatives

`codex/mmc-pwm-closure` remains recoverable. Its overlapping output, measurement,
publication and validation repairs already have accepted implementations in
the PWM history. Its alternative 7.5 kA protection has only isolated SLG
diagnostic evidence and an interrupted complete suite; it is **not adopted**.
The [supplemental handoff](mmc-pwm-closure-handoff-20261015.md) is retained.

The remaining historical differences on `codex/lcc-acceptance-hardening`,
`codex/mmc-autonomous-builder` and `codex/mmc-fault-evidence` were already
reviewed in the [earlier integration](branch-integration-20260926.md) and
[October 14 snapshot](current-status-20261014.md). Applicable behavior is present;
older interfaces and unverified measurement drafts are not reapplied over it.
