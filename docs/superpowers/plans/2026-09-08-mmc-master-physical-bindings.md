# MMC Physical Binding And AVM Completion Plan

**Goal:** Replace the remaining MMC Master-name placeholders and AVM contract
defects with checked physical construction, then continue the applicable real
acceptance. A/B native timing/fault/public-service integration is owned by its
existing worktrees and is not duplicated here.

**Architecture:** Reuse the shared MasterBindingRegistry and binding-aware
placement/readback. Keep MMC normalization, assets and AVM work isolated on
`codex/mmc-master-offline-audit`. Use native companion components for compound
electrical assemblies rather than pretending they are installed Master names.
Source, dimensional, parameter, connectivity and energy contracts must all
survive planning, placement, save and reload.

- [x] Read current acceptance criteria and concurrent task ownership.
- [x] Reproduce the catalog's ignored scalar types and AVM discharge/energy
  consistency defects with focused tests.
- [x] Complete catalog types and coupled energy repairs, and review them.
- [x] Add an exact MMC direct-binding registry for DC node, three-phase source,
  transformer, scalar PI and ground. Normalize source R/X through magnitude
  and angle with finite/range checks, retain the original R/X evidence, and
  validate physical values against installed metadata before placement.
- [x] Build and verify every direct binding in an independently owned PSCAD
  instance; keep a source-hashed report and test cleanup separately.
- [ ] Feed audited binding evidence through the actual MMC planning/execution
  path; preserve injected test inventories while requiring real metadata for
  production use. Correct missing Master catalog entries and neutral wiring.
- [ ] Replace the false scalar `master:dc_cable` reference with an explicitly
  modeled line assembly and split sending/receiving conductor nets. Line L/C
  and coupling must come from a declared physical profile or explicit input;
  the existing length/resistance-only request cannot imply arbitrary dynamics.
- [ ] Implement the native average-arm companion with consistent capacitor
  voltage normalization, signed energy flow, actual R/L/current measurements
  and a real blocked diode path. Do not use an open circuit as half-bridge
  blocking and do not label PWM as AVM.
- [ ] Wire all twelve arms and actual controls/measurements, verify the
  constructed topology, then run component and complete-model acceptance.
- [ ] Diagnose each failed physical or implementation check and rerun the
  affected gate. Keep independent golden and full-model verdicts separate;
  report only a demonstrated external prerequisite after independent work.

Direct-source convention: the source behind its impedance uses line-line RMS
kV and a positive-sequence R+jX value at the requested frequency. The installed
source3 Type=3/Imp=1 profile expresses this as Z1/Phi1; source3 N3 with View=1
is the three-phase terminal. Transformer voltage parameters are AC line-line
RMS values, not a copy of the DC rating. The source and transformer choices
must be explicit in the immutable normalized plan.

## Current Evidence

- Direct bindings: licensed PASS at `025c645`, with five bindings, five saved
  wires, clean recompilation and immutable finalized project/artifacts. Report:
  `D:/PSCAD-Workspace/mmc-master-binding-acceptance-20260908/mmc-master-binding-20260908T095119234815Z-84db8e/report.json`.
- Cable constants: fresh native 100/300 km generation at `807502e`, with complete
  finite coefficient bodies and final fit records. Evidence directory:
  `D:/PSCAD-Workspace/mmc-cable-constants-20260908/verified-strict-frozen`.
  Native cable assembly and electrical loop acceptance remain pending.
- Average arm: first native attempt at `807502e` exposed module parameter import
  and fixed-node naming defects. Its owned PID exited and evidence was retained
  at `D:/PSCAD-Workspace/mmc-average-arm-acceptance-20260908/attempt-20260908-174633-918404c6/report.json`.
  Generator repairs and affected acceptance continue; this is not a physical
  PASS or a complete-converter verdict.
