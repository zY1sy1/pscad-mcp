# LCC WP1B Fixed Autonomous Physicalization Completion

**Completed:** 2026-09-01

**Scope:** `lcc.fixed_autonomous`

**Capability:** `simulated/PASS` (licensed no-fault smoke only)

## Evidence Identity

- Commit: `3a09c8fe0b6ebf676f2bfd47e7ad89d8cba9117d`
- Branch: `codex/lcc-wp1b-fixed-physicalization`
- Run: `fixed-lcc-20260901-080458-594`
- Report: `D:/PSCAD-Workspace/lcc-wp1b-fixed-acceptance/fixed-lcc-20260901-080458-594/fixed-lcc-acceptance-report.json`
- Report SHA-256: `030a59d2af8fdbfad76e364eebd7435135135f09bbbbf9df787c8ce5fb68ed14`
- Plan SHA-256: `0d2a6ee947a5cbd329906bfda4cb2e4a77b5b94d94738e537057583462f50744`
- Journal SHA-256: `cdcd351be307b68e5c48522c9aefc1aac873cb4aac998b54fe276807248bcfc6`

The report was independently reloaded and all referenced files were rehashed
before promotion. The report commit matched HEAD and no PSCAD process remained.

## Immutable Inputs

| Input | SHA-256 |
| --- | --- |
| Installed `master.pslx` | `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939` |
| Registry file | `e618ab79d535e91148724721b6efaa096ac3f988894ecfe207e6b3806608991a` |
| Canonical registry | `3f153e093282c5db62d5f27c5364eadc2d624c98c40f0f8642295a372cbf1523` |
| Asset manifest | `115479abfefd89e5e34b0472b503d630c1025ca85560b43b2ee10d4e8b391542` |
| Catalog | `1a96e5336ab7480803a089d49e2f9c9bce46bce6f6995dc3bf595f0f0771ab22` |
| Blueprint | `9268eca63fd22b169e576aba9ef25e160ee9247b17adeaf08f4958f1b840896e` |
| Companion library | `e8745e5e50ece823583024b4e124ebf9e6092a756e72b4c4da000a0d050c62a9` |
| Smoke contract | `2a80dccfec5a3e465609b54dfdca611e1217f3b5fe36ef5f5820e342e96360cc` |
| Compiler configuration | `bd6183220badfa7a32f5419e8563d9b5c598fc370d50970d9e0bfaba092f6ca1` |
| GFortran executable | `fd179ba3ddb0df54ddc59911042947d97a20f039297279eb6cbf9554b32c8665` |

Every tracked source recorded identical before/after hashes.

## Component Gate

All fixtures passed load, read-back, reload, and structured compile-message
checks.

| Fixture | Definition | Before compile | Final project | Compile |
| --- | --- | --- | --- | --- |
| `bridge_rectifier` | `cigre_lcc_v1:LCC12PulseBridge` | `0b13c2ce35be6e43e95f114d0fe26a6edd2d07a5a242789372434877abf2e879` | `4ce12a30bdfe4fd007bedc613f89d15a58e65fbcc2e831916500070af5bc5411` | PASS |
| `bridge_inverter` | `cigre_lcc_v1:LCC12PulseBridge` | `a24ddacc03bf89bb0571b744da1b3aa65fa1a1d42ad23d224bffcf454206c9fe` | `dd9ee07a74511674ae729cfaea0536755bdf6a2fa9fedc467fac429e080d93d9` | PASS |
| `rectifier_control` | `cigre_lcc_v1:RectifierControl` | `0ff9c17eb288fb69ab2f8600aec1442eb62043380063c2dfbec9298617ee51b7` | `4ed5da88478da5d9de9cafe47a2ddcc1b3c64877fbbd2efb9df3989237f026fc` | PASS |
| `inverter_control` | `cigre_lcc_v1:InverterControl` | `d446a6d053e7220b37b5915b6522a77d5c4043f357d32a5e56f1059be80f5f70` | `c4a15a11778c80c66b5e52bfc0778ece12b78bd921bac6b4c9c6832624a2ae7d` | PASS |
| `initialization` | `cigre_lcc_v1:Initialization` | `976fc98f92a25345d8d1d7d05d58034e2900f45d2dc99dfa7ccaffdea73e91d0` | `34d4b340fe59cd2acb91211da260b967021daae91c7277d9dc3fb8f3772fbd84` | PASS |
| `signal_interface` | `cigre_lcc_v1:SignalInterface` | `619f10dda861c7b25a4289a750a2d736cdd429c9a2d3cd70e4f0f7a4d33ec948` | `4297e6728c0a2469c570851cb27250e702c54ad714fdc05e1d760eb1e7607005` | PASS |

The signal-interface before-compile hash in the immutable report is
`619f10dda861c7b25a4289a750a2d736cdd429c9a2d3cd70e4f0f7a4d33ec948`.

## Full Topology And Smoke

- State chain: `validated -> staging_created -> components_placed -> parameters_verified -> connections_verified -> structure_verified -> staging_saved -> compiled -> simulated -> smoke_passed -> published`.
- Published project: `WP1B_FIXED_LCC_PUBLISHED.pscx`.
- Published project SHA-256: `f15d2f4d350c2c4302e6e6a016b35ac09e0601c4957c1b3bc5da02d54a854305`.
- Final project reload and compile smoke: PASS.
- Selected OUT SHA-256: `13564efd93a789353058b4a657a73c0166c9a05057042e0b30be3214f817da6d`.
- INF SHA-256: `aba32a7966eebcda83c983193d05bb27bd8e1afdb6e36a733a021cdb6b5bc0cc`.
- INFX SHA-256: `13661270dd8a08f32e0b9a4918ebf0e770368b081e11b4f8e3dab269516bfcd7`.
- Domain: 0.0 s through 0.1 s.
- Output step: 0.00005 s.
- Samples: 2,001 per required channel.
- Checks: exact time coverage/cadence, finite outputs, continuously enabled controls, and bounded AO channels all PASS.
- Remaining PSCAD processes: 0.

## Verification And Review

- Fresh pre-promotion full suite: `2362 passed, 47 skipped`.
- Generated companion `--check`: PASS.
- Asset audit: PASS, two `g6p200`, 12 effective valves, scalar FP=0 AO.
- PowerShell parser: PASS.
- Changed-code fatal Ruff checks: PASS.
- Broad historical Ruff inventory: 52 pre-existing findings; no new finding was introduced.
- `git diff --check`: PASS.

Review corrections were committed independently, including saved-graph
fail-closed validation, orthogonal endpoint routing, exact smoke cadence,
durable setup/cleanup FAIL reports, LF asset attributes, mandatory bridge
binding, PSCAD label-anchor isolation, ground-return endpoint wires, Legacy OUT
normalization, and independent final publication identity. All failed licensed
directories and diagnostic directories were retained.

## Promotion And Exclusions

Explicit promotion changed only `lcc.fixed_autonomous` to `simulated/PASS` and
updated the fixed asset manifest identity. Older current-commit claims were
invalidated by the baseline transition rules.

The following claims remain excluded:

- `disturbance_acceptance`
- `commutation_failure_acceptance`
- `independent_golden`
- `final_accepted`

WP1C owns disturbance, commutation-failure, and recovery evidence. WP6 owns
the independent golden reference and the final `accepted` decision.
