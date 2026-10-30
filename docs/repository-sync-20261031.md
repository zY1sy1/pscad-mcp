# Repository synchronization — 2026-10-31

The October implementation integrated through `ea0aa2d37c4217bac714fd1225200c799c0df5a1` is the source for this synchronization. It adds 91 local commits beyond the previously published main. The synchronization changes documentation and archival metadata only; runtime code and model acceptance criteria are unchanged.

The integrated work includes durable parameter sweeps and recovery, Legacy and Blueprint fixes, overhead AVM, and the qualified full-bridge detailed PWM reference. Current capabilities and request-specific limits remain documented in [the October 15 integration record](acceptance/current-status-20261015.md).

## Verification records

The existing integration record retains 4180 offline tests passed and 55 skipped at its tested runtime revision. On October 31, `scripts/audit_acceptance_inventory.py` verified 24 recorded evidence scopes with zero invalid scopes. The two existing missing durable reports, `mmc_stage_a` and `modern_core_5`, remain missing. See the [static audit snapshot](archive/acceptance-integrity-20261031.json). No new PSCAD simulation or physical acceptance is claimed by this upload.

The current source also passes `python -m ruff check --select E9,F63,F7,F82 pscad_mcp tests`. New public history and current source files were checked for credential material and GitHub's per-file size limit before synchronization.

## Preserved work outside main

The historical branches `codex/lcc-acceptance-hardening`, `codex/mmc-autonomous-builder`, `codex/mmc-fault-evidence` and `codex/mmc-pwm-closure` retain alternatives reviewed by the existing integration records. They are preserved independently; older interfaces, measurement drafts and the unqualified PWM protection alternative are not reapplied over accepted implementations.

Previously uncommitted LCC/MMC test drafts and planning documents are copied into [the draft archive](archive/local-worktree-drafts-20261031/manifest.json). Patches record their original base commits. Standalone test drafts use `.py.txt` so that they cannot enter normal test discovery. Their source worktrees remain unchanged, and these copies do not constitute a passing test result.

Private arrester simulation projects and bulky licensed evidence are backed up in the owner's private research repository, `zY1sy1/PSCAD-Arrester-power-balance`, under the October 31 supplemental archives. Generated SDKs, virtual environments, authoring caches and unrelated local outputs are excluded from this source repository.
