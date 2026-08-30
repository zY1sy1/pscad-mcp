# LCC WP1A Native Acceptance Completion Record

## Implementation Commit

- Evidence-bearing implementation commit:
  `c6ad59f3f7638f8b884ea4b95e44c21cd31ff56c`.
- Branch at licensed run: `codex/lcc-mmc-completion-roadmap`.
- Repository preflight: clean named branch, exact commit, `PASS`.
- Scope: `lcc.blank_native`; builder path: `lcc.blank_native`.
- Capability/status: `simulated/PASS`, not `accepted`.

## Official and Master Inputs

- Official template:
  `D:/pscad-mcp-example-inspection-20260829/cigre_lcc_bidirectional/Cigre_LCC_Bidirectional.pscx`.
- Template SHA-256 before/after:
  `f36738fbec4c9bdb0995ca73726e16d18e85c10166eaa893e6599a591d5c4a43` /
  `f36738fbec4c9bdb0995ca73726e16d18e85c10166eaa893e6599a591d5c4a43`.
- Installed Master: `C:/Program Files (x86)/PSCAD46/master.pslx`.
- Master SHA-256 before/after:
  `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939` /
  `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939`.
- Master registry file:
  `D:/pscad-mcp/pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/master-bindings-pscad-4.6.2.json`.
- Registry file SHA-256:
  `5556079998ebcab18e535e9c40b577374bbecf1917a74c50cc9cfbf0ac5f0d81`.
- Registry semantic SHA-256:
  `06a0086774dfb4e3448c5e697a80de60dcc0000e0bde3f51e77badba75663b76`.
- Asset manifest SHA-256:
  `ee62e0dcbef5a9d89e1ef23964179b0a3b78aca6f412efcc0dac6bcb914f12ad`.
- Compiler configuration SHA-256:
  `bd6183220badfa7a32f5419e8563d9b5c598fc370d50970d9e0bfaba092f6ca1`.
- Compiler executable SHA-256:
  `fd179ba3ddb0df54ddc59911042947d97a20f039297279eb6cbf9554b32c8665`.
- Canonical preflight SHA-256:
  `8de116c5efbda4cbb32dc5af2fabc9bf383bbd20806e9a81ab2869bd17b01bc4`.

## Build and Journal Evidence

- Project: `WP1A_NATIVE_LCC`.
- Workspace:
  `D:/PSCAD-Workspace/lcc-wp1a-native-acceptance/native-lcc-20260830-232036-018`.
- Build ID: `c629d2572cda4bb49af37c691ee96597`.
- Plan SHA-256:
  `c06b0d2ecaba2a87caa8043be856a953c0073d3141b703ea1a651f8cc2f804c0`.
- Journal:
  `D:/PSCAD-Workspace/lcc-wp1a-native-acceptance/native-lcc-20260830-232036-018/.pscad-mcp/lcc-builds/c629d2572cda4bb49af37c691ee96597/journal.json`.
- Journal SHA-256:
  `7ae196fec00cb449a138a0ca7fb8d14a55a84cc1ea5c07d6a0b90192adb1957a`.
- Exact history: `validated -> staging_created -> compiled -> simulated ->
  acceptance_passed -> published`.
- Terminal state: `published`.
- Published project SHA-256:
  `7845609df208593ea0bb7e57fc97049641d48eecb0746545a0cc18eccb0501ae`.
- Companion library SHA-256:
  `589d45d22b5686a5c2747d9117dfaa4a6fa569dece33a38ed602ef2cd195ad34`.
- Scenario source SHA-256:
  `7845609df208593ea0bb7e57fc97049641d48eecb0746545a0cc18eccb0501ae`.
- Selected output: `WP1A_NATIVE_LCC_01.out`, SHA-256
  `a31bf2d2ebd21939c4c0d1abf80e6d99f8d3d54df15c6ec3827bceb6cff10683`.
- Numbered output parts: four (`_01.out` through `_04.out`); `.inf` and `.infx`
  metadata are hash-indexed by the durable report.

## Physical Acceptance Evidence

- Verdict: `PASS`.
- `disturbance=true`.
- `failure_indication=true`.
- `bounded_dc_response=true`.
- `recovered=true`.
- Fault time/duration: `0.8 s` / `0.1 s`.
- Current limit / observed peak: `3.0 pu` / `2.5924014069693 pu`.
- Recovery window: `0.5 s`.
- `Fault/LCC Fault Active`: `state`, 10,001 samples, domain `0.0-2.5 s`.
- `Inverter/DC Current`: official-template unit metadata is undeclared (`""`),
  10,001 samples, domain `0.0-2.5 s`.
- `Inverter/Gamma`: official-template unit metadata is undeclared (`""`),
  10,001 samples, domain `0.0-2.5 s`.

## Durable Report Identity

- Run ID: `native-lcc-20260830-232036-018`.
- Report:
  `D:/PSCAD-Workspace/lcc-wp1a-native-acceptance/native-lcc-20260830-232036-018/native-lcc-acceptance-report.json`.
- Report SHA-256:
  `1fe448921d339f677fe6f70bfecc057615fd0eb7aee17dd897ab3292acaaf4be`.
- Report commit: `c6ad59f3f7638f8b884ea4b95e44c21cd31ff56c`.
- Generated at: `2026-08-30T15:21:13.496363Z`.
- Kind/capability/status: `licensed_simulation` / `simulated` / `PASS`.
- Re-index, strict domain validation, artifact hashes, baseline identities, and
  report hash all passed before promotion.

## Baseline Transition

- Baseline: `docs/acceptance/lcc-mmc-program-baseline.json`.
- `repository.base_commit` advanced to
  `c6ad59f3f7638f8b884ea4b95e44c21cd31ff56c`.
- `lcc.blank_native` now references `native-lcc-20260830-232036-018` as
  `simulated/PASS`.
- All other scopes retain `evidence_run_id=null`; no Master, fixed, parametric,
  MMC, or accepted scope was promoted.
- Earlier native reports remain historical audit entries and do not support the
  current scope.

## Test and Review Evidence

- Independent final code review: no findings.
- Final independent full suite: `2202 passed, 46 skipped`; one pre-existing
  Pydantic unresolved-forward-reference warning remained.
- Final focused offline gate before the licensed run: `105 passed, 3 skipped`.
- Final post-promotion baseline gate: `38 passed`.
- Ruff: all targeted acceptance, orchestration, CLI, and promotion checks passed.
- PowerShell parser: zero syntax errors.
- Review regressions cover source/Master/compiler/template identity binding,
  branch mismatch, report and checkout races, compiler mutation, unreadable
  sources, unexpected runtime identity, and durable FAIL persistence.

## Explicit Exclusions

- `fixed_autonomous`.
- `parametric_lcc`.
- `independent_golden`.
- `final_accepted`.
- No electrical topology, control threshold, waveform algorithm, official
  template, installed Master, fixed LCC, parametric LCC, MMC, or PSCAD 5.x
  implementation was changed or promoted by WP1A.

## WP1B Unlock Decision

WP1A exit criteria are satisfied. WP1B fixed-autonomous companion
physicalization is unlocked. The native template result remains only
`simulated/PASS`; WP1B must not reuse it as fixed-autonomous evidence, and final
`accepted` status remains blocked on WP6 independent-golden acceptance.
