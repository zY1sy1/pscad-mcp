# Fixed LCC WP1C Native Engineering Completion Record

Recorded on 2026-09-08. This record covers WP1C engineering closure and its
same-revision WP1B regression. Independent reviewed golden comparison and final
`accepted` remain WP6 work.

## Revision and Isolation

- Evidence-bearing implementation commit:
  `a2959fe47bfea0dfd38c75ea694e4c3e28e09ea5`.
- Branch: `codex/lcc-wp1c-native-closure`.
- Worktree: `D:/pscad-mcp/.worktrees/lcc-wp1c-native-closure`.
- Main-repository concurrency fix `db65d74` was integrated as `f805c05`, with
  this task's existing changes preserved and conflicts resolved.
- Both licensed runners started from the same clean named checkout with
  process-local `PSCAD_MCP_ACCEPTANCE=1` and
  `PSCAD_MCP_ACCEPTANCE_CONCURRENT=1`.
- Each attempt used a distinct project/output workspace and a minimized,
  vendor-identified managed PSCAD 4.6.2 x64 instance.
- This later completion-record commit changes documentation only. Report
  identities continue to refer to the implementation revision above.

## Implementation Closure

The engineering corrections establish native commutation reference and angle
feedback, correct bridge and fault-control polarity, grid-aligned companion
ports, rated transformer parameters, and 200 mH DC smoothing reactors. Actual
three-phase converter AC power is measured independently of DC voltage/current;
the separate grid terminal power balance remains required.

Final publication uses a distinct `_PUBLISHED.pscx` identity and undergoes
reload, topology validation and compilation. The runner now resolves the real
published project and companion library, verifies the publication's own hash,
rediscovers the simulated staging project's outputs, and applies the same
blueprint-defined native-to-logical selector mapping as the executor. Name
mapping leaves time, samples and units unchanged and rejects duplicate logical
selectors. No physical numerical threshold was reduced or required check
removed. The declared WP1C physical window remains `0.7 <= t < 0.8 s`.

## Verification

- Full offline suite, with all acceptance opt-ins cleared:
  `2634 passed, 49 skipped` in `79.27 s`.
- Final focused runner/executor/dynamic/CLI regression:
  `176 passed, 1 skipped`.
- Fatal Ruff (`E9,F63,F7,F82`), `compileall`, `pip check` and
  `git diff --check`: passed.
- Regression failures were observed before repairs for native artifact
  locations, publication hash drift, path/hash pairing, actual staging output
  discovery, native output names and duplicate canonical names.
- Strict report schemas, current source and artifact hashes, publication
  history, raw-output reread and all engineering metrics passed the external
  audit. Normalized samples match a fresh parse of the recorded OUT/INF after
  selector-only mapping; all non-selector fields are unchanged.

Audit script:
`D:/PSCAD-Workspace/lcc-wp1c-native-closure/concurrent-model-20260908/verify_a2959fe.py`.
It was executed against the clean implementation commit before this
documentation-only record was added.

## Licensed Reports

The common run root is
`D:/PSCAD-Workspace/lcc-wp1c-native-closure/concurrent-model-20260908`.

| Evidence | Run ID | Verdict | Report SHA-256 |
| --- | --- | --- | --- |
| WP1B no-fault smoke | `fixed-lcc-20260908-094404-450` | `PASS` | `82f16827bc9e2a731e5606c7b4614a06f76ad0724bee21a5dbb1efaafa2ae0fd` |
| WP1C engineering | `run-20260908-175551-346` | Engineering `PASS`; total `INCOMPLETE_ANALYSIS` | `226cdd1120d113f7d79c0769df960bc97194d14d1af245f166052a79cedac165` |

Report paths:

- `D:/PSCAD-Workspace/lcc-wp1c-native-closure/concurrent-model-20260908/fixed-lcc-20260908-094404-450/fixed-lcc-acceptance-report.json`.
- `D:/PSCAD-Workspace/lcc-wp1c-native-closure/concurrent-model-20260908/run-20260908-175551-346/fixed-lcc-dynamic-report.json`.

WP1B includes six independently reloaded/compiled companion fixtures, final
project reload/recompile, and 2,001 samples over `0.0-0.1 s` at `50 us`.
Its managed PID `30716` exited, with no quit error or owned residual process.

WP1C contains 17 channels, each with 30,001 samples over `0.0-1.5 s` at
`50 us`. Build ID is `ae531f78c2fb41cf95ad11f48120d900`; plan SHA-256 is
`af0b1eab77d75f99591ebf96568e957b317ad392fc08aea5e984a61f1ee0dfd0`.
Its history ends `compiled -> simulated -> dynamic_engineering_passed ->
published`. The final publication records `final_compile_smoke=true`.
Its managed PID `21192` exited, with no quit error or owned residual process.
No foreign PSCAD process was stopped or attached to for these gates.

## Physical Checks

All nine checks passed in the declared prefault window. Values below are
rounded for readability; the report and audit retain full precision.

| Check | Observed | Unchanged limit |
| --- | --- | --- |
| Rectifier DC voltage | Mean `575.772544 kV`, positive | Magnitude `0-1000 kV`, positive |
| Inverter DC voltage | Mean `-566.985314 kV`, negative | Magnitude `0-1000 kV`, negative |
| DC power product | Mean DC product `575.809932 MW`; independently measured converter power `577.007387 MW`; max error `6.089230 MW` | `5%` |
| Grid terminal power balance | Max imbalance `13.450681 MW` | `100 MW` |
| Rectifier alpha | `14.536724-14.543453 deg` | `0-90 deg` |
| Inverter gamma | `17.998050-17.999408 deg` | `10-40 deg` |
| Commutation overlap | `14.861831-14.874798 deg` | `0-30 deg` |
| Raw converter DC voltage ripple | `51.226583 kV` peak-to-peak, `8.897017%` | `10%` |
| Alpha control error | Max absolute error `0.463276 deg` from `15 deg` | `5 deg` |

## Dynamic Checks

All four checks were independently rederived from the current run's raw data.
The EMTDC event is configured to apply at `0.8 s` and clear at `0.9 s`.

| Check | Window / samples | Numerical evidence |
| --- | --- | --- |
| Disturbance | `0.7-1.0 s`, 6,000 samples | Rise `0.799995 s`, fall `0.899955 s`; errors `5 us` and `45 us`, within `100 us`; fault state `0/1/0` |
| Failure indication | `0.7-0.9 s`, 3,999 samples | Gamma falls from prefault median `0.314129749 rad` to `0 rad`; required drop `0.017453293 rad` |
| Bounded DC response | `0.7-1.4 s`, 14,000 samples | Peak `2.727099609 kA`; prefault median `1.002443236 kA`; ratio `2.720452900`, below `3.0` |
| Recovery | `1.3-1.4 s`, 2,001 samples per channel | All four channels hold within their required bands for the final `0.1 s` of the `0.5 s` recovery window |

Recovery maximum deviation / allowed band:

- IDC: `0.022721120 / 0.200488647 kA`.
- Rectifier VDC: `36.013541084 / 115.571229536 kV`.
- Inverter VDC: `38.989073978 / 113.948525192 kV`.
- Gamma: `0.002595102 / 0.062825950 rad`.

## Artifact Identity

The WP1C project is `WP1C_FIXED_LCC_PUBLISHED.pscx` in the WP1C run directory.
The companion is `.pscad-mcp/libraries/cigre_lcc_v1.pslx`. Raw outputs remain
under `.pscad-mcp/lcc-builds/WP1C_FIXED_LCC.staging/WP1C_FIXED_LCC.gf42`.

| Artifact | SHA-256 |
| --- | --- |
| Published project | `d86478768641b22dd104c5d8d1a3cb6444a5391dc89c25e2aed1fa0810ef8fb3` |
| Companion library | `1b685a99200898dd733b72e44c04d12af96650dffa64ef1dae04f64434491c3c` |
| `WP1C_FIXED_LCC_01.out` | `5828758d6368ec4a3d7910a9c03fee65d3ef2719cfcfc59754cdbd35fde04f24` |
| `WP1C_FIXED_LCC_02.out` | `d87a70e4d8073879b21e10551b6176ac1088f67cb409dcd1dedf7dc4b828be2f` |
| `WP1C_FIXED_LCC.inf` | `1bdceccaec3e7cc983ba39db95d99e20a52ee7cf67591cac3ae2b5c74fd1f886` |
| `WP1C_FIXED_LCC.infx` | `73608de943c91622702fa501b0426299a30dcf5038565718a787673ce055a734` |
| `normalized-samples.json` | `5c43dd4a0ea99b6dd48e681a80e552db6a0c3387df57b737515d8b03422d3580` |
| Build `journal.json` | `387d5cf1e81726a6367b7a88cc972ccdfc32f05a9f202ecfe91678c5cc6e695e` |
| `evidence-audit.json` | `f871f472e82724307552530cb0b9f909bc0d3712694fc28ecac35d46c2483c11` |

The audit and both reports retain all absolute paths. Every output part and
metadata hash also matches the executor journal's pre-publication record.

## Source Preservation

All nine WP1C source records have equal before/after/current hashes:

| Source | SHA-256 before = after |
| --- | --- |
| Installed Master | `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939` |
| Compiler configuration | `bd6183220badfa7a32f5419e8563d9b5c598fc370d50970d9e0bfaba092f6ca1` |
| Compiler executable | `fd179ba3ddb0df54ddc59911042947d97a20f039297279eb6cbf9554b32c8665` |
| Blueprint | `d0f17d250e94001fe9fe991d4e9d8ff805cd5aa658c8fd6f8f4712a61be514a4` |
| Catalog | `b2e4aec21e6332c26c42380f4fad2aa7fb0ecf46f40214b12f619331f98314ca` |
| Companion | `1b685a99200898dd733b72e44c04d12af96650dffa64ef1dae04f64434491c3c` |
| Dynamic contract | `890d0680e034b6cee7e79c30a0ba894c66dd487480be135d87a5e645bdbcc3f6` |
| Manifest | `bc2f29479f142cbc8c34fb9adca6b4ba32ab4c252ed60629614cb2d75fbdc697` |
| Master binding registry | `20d7801711cb164197163492ea84a12bb90db4464f553f8e175f49b3c8b0cc06` |

The audit additionally verifies every plan-bound asset hash, including
`acceptance.json`, `golden.json`, `smoke.json` and `PROVENANCE.md`.

## Preserved Failed Attempt

The preceding same-commit WP1C attempt
`run-20260908-174849-070/fixed-lcc-dynamic-report.json` remains intact, SHA-256
`397bb20587591b84080617f39d28d52115f24543b0c70f8a58446d3daf5d0cba`.
It stopped while connecting the inverter enable net with Windows `WinError 5`
during atomic journal replacement, before physical evaluation. Its source
hashes stayed unchanged and owned PID `43108` exited cleanly.

A separate `AtomicJournal` experiment reproduced the same error with an open
reader and successful replacement after closing it. Its evidence is
`D:/PSCAD-Workspace/lcc-wp1c-native-closure/concurrent-model-20260908/journal-sharing-jyjpnf8t/sharing-probe.json`,
SHA-256 `c971c00eccafeb1695d530fcfa3727154568384479bb8a456e724f8bfde762a8`.
The successful retry removed live journal reads; no code, model, threshold or
required check changed between these attempts. Earlier diagnostic and failed
publication artifacts also remain in their original task directories.

## Review and Handoff

Independent code and evidence review passed with no unresolved
Critical/Important findings. The reviewer independently rederived the WP1B
smoke and all nine physical/four dynamic WP1C checks from the completed raw
outputs, with exact agreement to the reports and journal. Source, artifact,
normalized-sample, audit and contention-probe hashes matched. Final reload and
compile evidence and owned-process cleanup were confirmed. The reviewer found
no factual error in this completion record.

Documentation checks: `74 passed, 4 skipped`; staged whitespace checks passed.

WP1D can reuse the proven shared backend, output parsing, event evidence and
owned-instance cleanup, but still requires its own rating-specific scenarios
and runs. WP6 requires licensed reference output from an independently assembled,
reviewed model with immutable source/version/compiler/parameter identities.
The packaged placeholder is not sufficient for final comparison.

The program baseline, `accepted` state and release state were not promoted.
No merge or push was performed.

fixed LCC WP1C current-commit dynamic engineering evidence completed; final status remains `INCOMPLETE_ANALYSIS` pending independent reviewed golden.
