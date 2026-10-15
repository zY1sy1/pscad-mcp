# Routed detailed PWM acceptance (2026-10-15)

Status: **PASS for the exact reference request below**. All eleven scenarios,
the untimed delivery and independent saved-model reload pass **5698 physical
checks**. The final published file passes another **404 checks** in a separate
owned instance. Public validation confirms the entire frozen matrix; source,
published-model and compiler-input hashes match and all owned instances exit.

The user authorized this work after choosing detailed PWM alongside a separate
overhead-line AVM chat. This implementation is on `codex/mmc-detailed-pwm` and
is not merged or pushed. Electrical producer revision: `d0e547d`; publication
repair revision: `95655d1`.

## Exact request and physical reference

| Item | Bound value |
| --- | --- |
| Converter | Two-terminal full bridge, symmetrical monopole |
| DC voltage / active power / reactive power | 640 kV / 1000 MW / 0 MVAr |
| AC grids | 230 kV, 60 Hz, SCR 5, X/R 10 at both ends |
| DC link | Two audited 100 km overhead-line segments, fresh public LCP constants |
| Reversal | 0.5 s; terminal-two order slew 4000 MW/s |
| Cells | Actual Main instance `NoCells1=76`, twelve reachable arms, 912 cells |
| Arm parameters | 50 mH, 2800 microfarad per cell, 0.005 ohm switch on resistance |
| Stored energy | 90.5431579 MJ across both converters |
| Carrier / integration / output steps | 1380 Hz / 10 microseconds / 50 microseconds |

The installed filename `H_MMC_Mono_DC.pscx` does not identify its actual
reachable cell topology. The audited instantiated circuit is full bridge. Its
arm capacitor-voltage sums use the 640 kV convention, not a guessed cell count
or the uninstantiated form default of 38.

Original project and library remain immutable:

- `C:/Users/Public/Documents/PSCAD/4.6/Examples/ModelsInProgress/H_MMC_Mono_DC.pscx`
  — `1900be93877400fba228b1808a5310980d801b0260d7df998df6c5a2f6a035dd`.
- Sibling `intermediate.pslx`
  — `08466778704e547d7d9d80af99a48c09292dd3a51056ac26216c3913d5cc3a1b`.
- Installed Master 4.6.2
  — `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939`.

The public route rejects other ratings, frequencies, grid strengths, link
lengths, converter types and engineering overrides whose physical binding has
not been qualified. It also rejects partial fallback candidates.

## Implemented behavior

Eight real Main command sources drive P/Q orders, PI reset, firing block,
AC/DC isolation and physical AC/DC faults. Default guessed OnOff/Dblk/fault
option mappings remain disabled. Each scenario has a separate immutable
initialization and exact EMTDC event schedule.

Measurement mappings expose all 337 concrete channels with their actual
descriptions, scopes, units and compiled owner identities. The physical checks
cover both stations, twelve arms, signed insertion during DC faults, actual
fault branches, actual isolation switch states and electrical recovery.

The preparation recipe repairs terminal-two charging/carrier frequency,
sorting, measured DC feedback, current headroom and P/Q/DC outer-loop response.
Measured remote active power feeds the DC-controller current before its
existing limiter. Nominal overcurrent hysteresis releases after cold-start
inrush clears. Physical fault/protection inputs and acceptance bounds are
retained. Trial DC reactors were removed after their voltage-ringing evidence
was preserved.

The lifecycle requires the final output time in every INF-declared OUT part
before it freezes evidence. The public builder runs all eleven scenarios,
then the untimed editable delivery, then an independent Python/owned PSCAD
reload. Final publication copies the audited compiler trees and loads,
compiles and runs the actual final target in another owned process. It verifies
the saved file against the frozen measured-file hash. Public validation requires
that manifest and independently evaluates its frozen traces; a reader's finite
data PASS cannot certify a PWM model.

## Single-line-ground diagnosis

Public-v3 preserved a 39.82051 kA fault-branch crest, above the 35.49985 kA
grid-only envelope. The grounded-Y/delta transformer supplies a passive
zero-sequence path. At the crest the new direct grid probe reads 29.67017 kA;
the transformer terminal current is -10.13255 kA. Their branch balance differs
by 0.01778 kA across the recorded sampled outputs.

For the actual connected circuit, `Zgrid=1.052749+j10.527493 ohm` and
`Ztransformer=j5.29 ohm`. Its sequence network is
`Z1=Z2=Zgrid; Z0=Zgrid || Ztransformer`. Therefore
`3*Vphase/abs(Z1+Z2+Z0)=16.13894 kA RMS`, with a maximum DC-offset crest of
45.64781 kA. The grid-source current remains independently constrained by
35.49985 kA. The original DC fault-switch 20 kA limit, arm 3 kA limit, station
DC current bounds, capacitor/power/voltage/modulation criteria and 0.5 s
recovery deadlines remain intact.

Fresh isolated SLG evidence passes **489 physical checks**:

- `D:/PA/pwm14/suite-v11/ac_single_line_ground_fault/report.json`
- `D:/PA/pwm14/analysis-v9/ac_single_line_ground_fault/physical-checks.json`
- `D:/PA/pwm14/slg-sequence-diagnosis-20261015.json`

These isolated probes support diagnosis; the complete model evidence is below.

The isolated pole-to-ground DC scenario also passes **494 physical checks**:
`D:/PA/pwm14/analysis-v10/dc_pole_to_ground_fault/physical-checks.json`. Its
run report records unchanged input hashes and no remaining owned processes.
The isolated post-fault-recovery scenario passes another **494 physical
checks**, including a real fault and reset/deblock sequence:
`D:/PA/pwm14/analysis-v10/post_fault_recovery/physical-checks.json`.

## Complete public evidence

Final report: `D:/PA/pwm14/public-v6/report.json`, SHA-256
`bf099c66d2c7b6ec2a074f6b3a9f0b117ddddf05b54269fb1dac18c604724136`.

Delivered project: `D:/PA/pwm14/public-v6/MMC_PWM_pwm.pscx`, SHA-256
`17aca95cd1e3934a1ffb94d254872fb7a7bb031c64eebdca0bcb5c468c895f47`.
The acceptance manifest is `MMC_PWM_pwm_acceptance.json` in that folder,
SHA-256 `018bc4e66d16f49f2974028ffcafcf45ab201e884c8ff3b7f316d34f186f89a4`.
The independent closure audit is
`D:/PA/pwm14/final-evidence-20261015.json`.

The delivered file uses the audited line constants under the preserved
`public-v5` delivery directory. Keep both `D:/PA/pwm14/public-v5` and
`D:/PA/pwm14/public-v6`; the six required compiler libraries are copied under
`public-v6/lib`.

| Run | Physical checks |
| --- | ---: |
| Startup | 404 |
| Forward steady | 404 |
| Active-power step | 406 |
| Reactive-power step | 406 |
| Power reversal | 405 |
| Reverse steady | 405 |
| Three-phase AC fault | 489 |
| Single-line-ground AC fault | 489 |
| Pole-to-pole DC fault | 494 |
| Pole-to-ground DC fault | 494 |
| Post-fault recovery | 494 |
| Untimed editable delivery | 404 |
| Independent saved-model reload | 404 |
| Final published-file normal run | 404 |

`public-v5` completed all thirteen electrical runs with **5698 physical
checks**, then safely refused final reload because an earlier runtime project
had unsaved state. Its eleven required scenes alone total **4890 checks**.
All thirteen saved models retain their hashes after that owned session quit.
The original FAIL report remains unchanged.

Two publication issues were corrected: companion `lib/<compiler>` files were
not copied, and publication attempted to reset the waveform session. A failing
filesystem regression reproduced the missing binary; publication now verifies
and copies every planned compiler input and uses a separate owned subprocess.
The 39 focused service/recovery/physical/routed tests pass after this change.

The explicit `--resume-report` mode accepts only a finished, immutable,
cleaned-up eleven-scenario matrix with successful delivery and independent
reload. It checks unchanged requests, sources, compiler identities and
electrical producer hashes, re-evaluates every frozen trace, and repeats the
affected publication and final-file normal run. This retains the failing
attempt and avoids re-simulating electrically unchanged models.

Required scenes are startup, forward steady, P step, Q step, reversal, reverse
steady, three-phase AC fault, single-line-ground AC fault, pole-to-pole DC fault,
pole-to-ground DC fault and post-fault recovery. Delivery and isolated reload
also pass, original inputs retain their hashes and all owned runtime processes
exit. The final publication parent PID was 44824; the separate publication
worker PID was 34228. Both record complete cleanup.

The report and final acceptance manifest retain the exact request, revision,
producer hashes, saved-project/output/metadata identities, timing evidence,
physical checks and independent reload identities. The original failed reports
remain at public-v1, public-v2, public-v3 and public-v4; public-v4 also preserves
the profile rename defect and successful owned cleanup.

## Verification

- Focused implementation checks: 81 passed before the final profile fix;
  affected profile/physical/routed checks: 16 passed afterward.
- Complete offline suite: **4169 passed, 55 skipped** in 342.04 s;
  `D:/PA/pwm14/offline-publication-20261015.log` and
  `offline-publication-20261015.xml`. The later independent-publication
  change passed the 39 affected checks and the final licensed run. Earlier
  full suite: 4163 passed, 55 skipped in 377.05 s;
  `D:/PA/pwm14/offline-20261015.log` and `offline-20261015.xml`. The profile
  rename regression was separately reproduced and its affected checks rerun.
- Installed wheel verification: **PASS**, version 0.2.0, 112 tools, 9 LCC
  assets and 8 MMC assets. New PWM modules import from the installed wheel;
  `D:/PA/pwm14/package-v3/verification.json`. Installed publication module
  hashes match revision `95655d1`. The initial attempt without a
  build backend and the missing-dependency probe remain recorded; isolated
  wheel build and dependency installation resolved those environment issues.
- Scoped acceptance inventory integrity: **VERIFIED**, seven linked files,
  no errors; `D:/PA/pwm14/acceptance-integrity-20261015.json`. This is an
  integrity check of the named licensed evidence, not a new simulation claim.

This reference-point scope does not certify intrinsic DC blocking without
external isolation, other parameter requests, the separate AVM chat's work,
or physical acceptance of a later changed runtime/model.
The generic inspector identifies both native stations and twelve arms; its
native TLine conductor graph still reports unknown. Dynamic acceptance uses
the audited source identity and complete frozen component/wiring readback.

## Supplemental handoff received (2026-10-15)

The user designated this chat as the continuing owner. The supplemental branch
`codex/mmc-pwm-closure` handed off implementation `8bf57ea` and documentation
`e2e8b0d`, sharing baseline `2287d93`. Its original handoff is preserved
[verbatim](mmc-pwm-closure-handoff-20261015.md); the
[recipient index](mmc-pwm-supplemental-handoff-20261015.json) records source
paths, revisions, hashes and dispositions. A receipt is also saved at
`D:/PA/pwm14/supplemental-handoff-received-20261015.json`.

| Supplemental work | Corresponding accepted implementation | Disposition |
| --- | --- | --- |
| Frozen physical re-evaluation, `227efa8` / `79dbb62` | `4d9f486` / `95655d1` | Existing implementation retained |
| Compiler-library delivery, `ddf42de` | `95655d1` | Existing implementation retained |
| Actual measurements and project renaming, `45dae67` / `8bf57ea` | `738d91a` / `d0e547d` | Existing implementation retained |
| Complete OUT end domains, `5a3738d` | `3475c27` | Existing implementation retained |
| Measured 7.5 kA AC overcurrent isolation, `903c243` | Separate protection behavior | Archived as an unadopted alternative |

The protection alternative reads actual `I_AC1/I_AC2` phase currents, opens the
existing physical AC breakers, inhibits firing and clears its latch through an
explicit AC-open command. Its SLG diagnostic at `903c243` passes 484 checks,
with physical opening at 2.3032 s and a 30.2738 kA fault crest. That evidence
belongs to its diagnostic revision. It does not qualify implementation
`8bf57ea` or a full eleven-scene model, and it does not inherit this branch's
PASS. Adoption would change protection behavior and require a new frozen
revision and affected physical/shared-contract acceptance; the eleven-scene
and independent-reload requirements continue to apply.

The supplemental full-suite attempt `D:/PA/p15/s1` was interrupted. Its source
scope remains `INCOMPLETE_ANALYSIS` with `model_accepted=false`. The recorded
cleanup covers its own PIDs 18828 and 4444; no process was newly controlled for
this receipt. Nine cited evidence-file hashes and the diagnostic's recorded
484-check verdict were verified. The report and delivered model hashes listed
above still match; no electrical code, model, acceptance claim, merge or push
is part of this documentation-only handoff.
