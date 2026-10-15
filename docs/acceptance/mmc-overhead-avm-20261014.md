# Native full-bridge overhead AVM acceptance — 2026-10-14

The three exact 200 km overhead-line requests below passed licensed PSCAD 4.6.2 acceptance. Each suite contains a normal cold start, forward/reverse steady operation and reversal, four physical faults, and a fresh independent portable reload: 18 completed stages in total. Each suite has 38 passing consistency/acceptance checks and returns `model_accepted=true`.

Runtime evidence belongs to **`743203006a60333c02dfdd13216cd13756f68f84`** on **`codex/mmc-overhead-avm`**, starting from `a8fce2d`. Its implementation is included in the [October 15 local main integration](current-status-20261015.md), without a remote push. The closeout and integration commits do not acquire a new simulation verdict. The broader `parametric_mmc` inventory remains `PARTIAL`.

## Accepted requests

All requests use `average_value`, `full_bridge`, `two_terminal_symmetrical_monopole`, `dc_link={kind: overhead_line, length_km: 200}`, a one-second reversal and no engineering overrides. Both stations use SCR 5 and X/R 10. Udc is the pole-to-pole voltage.

| Udc (kV) | P (MW) | Q (MVAr) | f (Hz) | Station AC (kV) | Full suite |
| --- | --- | --- | --- | --- | --- |
| 640 | 1000 | +0 | 60 | 230 | [PASS](D:/PA/h14h/suite-20261014-124252-a37f249c/report.json) |
| 500 | 750 | +100 | 60 | 180 | [PASS](D:/PA/h14i/suite-20261014-131029-e4d46cf3/report.json) |
| 800 | 1200 | -120 | 50 | 320 | [PASS](D:/PA/h14j/suite-20261014-194627-3562fe19/report.json) |

All six children per suite report unchanged source inputs and source code, successful cleanup of the vendor-returned managed PID, no remaining owned processes and no cleanup errors. Each independent reload copies declared model/constants files without an executable or previous solver output, relocates constants references and repeats precharge, steady, network, controls and dynamics gates after a fresh build.

## Implementation and physical resolution

The public planner now discovers native inputs by requested medium. It audits the installed two-conductor flat-tower DCTL geometry and Master interfaces, generates fresh native frequency-dependent phase constants, validates both metallic/ground delay groups and fitting limits, and binds the input, producer and artifact hashes. The cable coefficient parser keeps its existing single-delay default; overhead verification explicitly permits and checks its two groups.

The four-terminal `MMCOverheadLink` uses separate `master:tline_interface` endpoints (`Mode=0`), positive pole A and negative pole C. Canonical interface metadata (`q=4`, empty parameter-list name, `link=-1`, `crc=0`) survives the unchanged strict PSCAD semantic finalization comparison. Mode describes endpoint arrangement, not electrical fidelity.

Low overhead capacitance exposed a startup common-mode oscillation. Four real series R–C pole-to-ground branches, one per pole at each station on the line side of isolation, provide damping. Each branch has measured current and capacitor voltage, uses the native capacitor primitive and starts empty (`StartType=0`). There is no imposed initial capacitor energy. The resistor limits its nominal initial fault discharge to nameplate DC current: `R = Udc² / (2P)`. `C = 2 / (2π f R)` places the corner at half the grid frequency. The earlier larger capacitor passed startup but delayed recovery past the existing reset window; reducing physical storage corrected it without changing thresholds, reset deadlines, contact timing or protection logic. Controls account for filter storage and measured native line capacitance.

The DC loop resistance follows geometry, `2 × 0.03182 / 3 × 200 = 4.242666666666667 Ω`, and is identical at all ratings. It is not scaled to a rating. The native fit reports 0.1591% maximum admittance error and 0.0628% maximum propagation error against the existing 0.2% limits. The geometry/constants source is read from the installed licensed assets; vendor XML is not added to the repository or wheel.

| Udc (kV) | Branch R (Ω) | Branch C (µF) | Power-ready time (s) | Forward power NRMSE (%) | Reverse power NRMSE (%) |
| --- | --- | --- | --- | --- | --- |
| 640 | 204.8 | 25.9041 | 0.92869 | 0.0133 | 0.0215 |
| 500 | 166.667 | 31.831 | 0.94235 | 0.0531 | 0.0190 |
| 800 | 266.667 | 23.8732 | 1.02460 | 0.0341 | 0.0197 |

Faults retain the original 2 pu DC/arm current bounds, 10% capacitor/voltage bounds, 5% recovered-power bound, 5 ms trip/isolation limits and 0.5 s recovery window. Every-step extrema support the bounds. External AC/DC isolation and measured physical faults remain part of the accepted design; `intrinsic_dc_fault_blocking=false` is unchanged.

| Udc (kV) | Largest DC current across four faults (pu) | Largest recovered-power error across four faults (%) |
| --- | --- | --- |
| 640 | 1.06807 | 0.1905 |
| 500 | 1.07438 | 0.2421 |
| 800 | 1.06461 | 0.2113 |

## Evidence identity and handoff

The generated `.gf42` build/run batches select **GFortran 4.2.1**. The acceptance source baseline also hashes a separate installed GFortran 4.6 probe; that probe hash is not the identity of the compiler used to build the licensed models.

### 640 kV

- Suite: `D:\PA\h14h\suite-20261014-124252-a37f249c\report.json`.
- Suite SHA-256: `daedb281c77e95db723911893de77501a202ffa9d4586b5ecdfaf40820bd585d`.
- [Accepted project](D:/PA/h14h/suite-20261014-124252-a37f249c/reload/attempt-20261014-130627-394e7d81/model/AVM_1cbcfc73a0d6_avm_0.pscx).
- [Companion library](D:/PA/h14h/suite-20261014-124252-a37f249c/reload/attempt-20261014-130627-394e7d81/model/cigre_mmc_avm_v1.pslx).

### 500 kV

- Suite: `D:\PA\h14i\suite-20261014-131029-e4d46cf3\report.json`.
- Suite SHA-256: `020b3b895b9b49cba0c504c81bbfaff78a25c917f1281af7483430b4bb12c7a3`.
- [Accepted project](D:/PA/h14i/suite-20261014-131029-e4d46cf3/reload/attempt-20261014-133304-a4d8eb38/model/AVM_411b845510c9_avm_0.pscx).
- [Companion library](D:/PA/h14i/suite-20261014-131029-e4d46cf3/reload/attempt-20261014-133304-a4d8eb38/model/cigre_mmc_avm_v1.pslx).

### 800 kV

- Suite: `D:\PA\h14j\suite-20261014-194627-3562fe19\report.json`.
- Suite SHA-256: `bbf6726f6771676ec96e875225c27cd7847189c5e0d709479bf1cb9e80ec5b3e`.
- [Accepted project](D:/PA/h14j/suite-20261014-194627-3562fe19/reload/attempt-20261014-200417-995d9ffc/model/AVM_56adab039172_avm_0.pscx).
- [Companion library](D:/PA/h14j/suite-20261014-194627-3562fe19/reload/attempt-20261014-200417-995d9ffc/model/cigre_mmc_avm_v1.pslx).

Load the companion PSLX before the PSCX and retain its validated `constants` directory and path bindings. The suite's `accepted_hashes` binds the finalized project, library, TLI, TLO, LOG, phase output and constants receipt. A relocation to another directory requires verified dependency rebinding as performed by the independent reload runner.

Read-only matrix integrity audit: `D:\PA\o14ohl-matrix-integrity.json` (SHA-256 `1b1d6ba310b0a9854272b3e0973bcdbddc6cb1a13df358266129e2396996b47a`). It rehashes the child reports, finalized model/constants, complete traces and native outputs, checks the frozen code/source baselines and owned cleanup, and recomputes the suite verdict from the saved children. It independently compares each saved pre-run executable with the executed binary using the existing strict policy allowing changes only to the PE timestamp/checksum. This is evidence integrity verification, not an additional simulation.

The audit verified 557 distinct files and 1898 checks for each suite, with no failed checks.

## Preserved attempts

| Evidence root | Classification and resolution |
| --- | --- |
| `D:/PA/h14a` | Interface finalization defect; canonical authored metadata fixed in `5f33b7d`. |
| `D:/PA/h14b`, `D:/PA/oh14mode` | Incorrect inline endpoint mode prevented a valid executable; separate native interfaces fixed in `22150e9`. |
| `D:/PA/h14c` | Startup common-mode physical failure; real passive RC damping added in `047b609`. |
| `D:/PA/h14d`, `D:/PA/h14e` | Oversized RC storage delayed DC fault reset/recovery; physical storage reduced in `7432030`. |
| `D:/PA/h14f`, `D:/PA/h14g` | Independent simultaneous EMTDC runs collided on a communication port (WinSock 10048), with interrupted output in the companion run; fresh suites were serialized in `h14h`, `h14i`, `h14j`. |

The immutable report/hash index is `D:/PA/o14ohl-historical-attempts.json`. Every failed child in that index records owned-process cleanup. Diagnostic roots `D:/PA/oh14scope` and `D:/PA/oh14det` remain preserved. No foreign PSCAD process was terminated and no failed result was relabeled PASS.

The first additional offline audit (`D:/PA/o14ohl-audit-two.json`) incorrectly compared the built executable hash directly with the vendor-relinked binary. Its initial script is preserved at `D:/PA/o14ohl-audit-initial.py`. Using the existing strict PE relink verifier and the saved `before-run.exe` resolved that audit-script error; the licensed reports/model files were unchanged.

## Verification

- At runtime commit `7432030`: `python -B -m pytest -q -k mmc -p no:cacheprovider`: **1345 passed, 7 skipped, 2839 deselected**, 256.41 s; log `D:/PA/o14ohl-mmc-regression-7432030.log`. Focused affected tests had also passed (49 tests).
- The same broad MMC selection passed before the final RC sizing correction at `047b609`; it is retained as historical regression evidence, not substituted for the final-revision run.
- Changed-file Ruff comparison against `a8fce2d`: no new findings (31 existing findings versus 33 at the baseline). Record: `D:/PA/o14ohl-lint-comparison.json`.
- Closeout manifest, integrity-auditor, delivery-documentation and changelog checks: **24 passed**; log `D:/PA/o14ohl-closeout-tests.log`. The updated manifest assertion file passes Ruff. All 22 other historical scope records remain unchanged; the parent MMC record retains its original status and adds the three named subscopes.
- Isolated package build and isolated-target installed-package planning probe passed at `7432030`. Wheel: `D:/PA/o14ohl-wheel-7432030/pscad_mcp-0.2.0-py3-none-any.whl`, SHA-256 `12dfb2055a0f1eb2a1c97662be24132d6a576833d94456654d5664be6b65fc67`. Both new overhead modules are included; the original installed Master/donor file contents are absent. Planning continues to return `model_accepted=false`.

The complete 26-scope inventory audit has no invalid evidence and verifies all three new overhead records. Its overall integrity remains `INCOMPLETE` only because the pre-existing `mmc_stage_a` and `modern_core_5` records lack durable reports, just as before this change. Before/after records are `D:/PA/o14ohl-inventory-before.json` and `D:/PA/o14ohl-inventory-after.json`. These historical gaps do not change the three overhead suite verdicts or complete the broader project.

Reproduce each suite from a clean frozen runtime checkout on the licensed host, serially and in a short dedicated workspace. The opt-ins are process-local:

```powershell
$env:PSCAD_MCP_ACCEPTANCE='1'
$env:PSCAD_MCP_NATIVE_AVM_FULL_ACCEPTANCE='1'
$env:PSCAD_MCP_ACCEPTANCE_CONCURRENT='1'
& D:/pscad-mcp/.venv/Scripts/python.exe -B scripts/run_mmc_native_avm_full_acceptance.py --workspace-root D:/PA/ohl --request-json D:/PA/o14ohl-inputs/request-640.json
```

Use the bound `request-500.json` or `request-800.json` for the other exact requests. Concurrent process ownership support does not guarantee distinct EMTDC communication ports; these final suites were run serially.

## Unverified scope

These results certify only the three named full-bridge overhead AVM requests and their installed flat-tower geometry at the recorded revision. They do not complete half-bridge overhead acceptance, arbitrary towers/ratings/lengths, detailed PWM, intrinsic DC fault blocking without external isolation, individual cell balance, switching stress/harmonics, thermal behavior or PSCAD 5.x. Historical cable acceptance keeps its own requests and revisions.
