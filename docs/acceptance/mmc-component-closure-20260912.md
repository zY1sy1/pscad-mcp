# Native MMC Component Evidence, 2026-09-12

## Accepted Scope

Frozen runtime revision: `8054c692843dddc0b7b2fd3d851eeb1032c795a0`.
The independently owned average-arm and two cable-loop runs below passed.
Each report retains `model_accepted: false`: none is complete-converter or
independent-golden acceptance.

| Gate | Report | SHA-256 | Managed PID |
| --- | --- | --- | --- |
| Half-bridge average arm | `D:/PSCAD-Workspace/mmc-average-arm-acceptance-20260908/attempt-20260912-130637-f1577838/report.json` | `82a9b03694bba671b0c9e2d769429af73878c926111b72f997293644a034e1f4` | 29136 |
| 100 km cable | `D:/PSCAD-Workspace/mmc-cable-acceptance-20260912/attempt-20260912-130316-dc41f010/report.json` | `d8585b778e1ebcce40a675499c19c0e562198cb5f550ec61427c37bd69fc6a5f` | 32124 |
| 300 km cable | `D:/PSCAD-Workspace/mmc-cable-acceptance-20260912/attempt-20260912-130436-801eb2e1/report.json` | `545ab2f745bb38fd99774cda96c952a2ee44daf0783951a6bacb8745c7957812` | 15912 |

All three owned PIDs exited, without terminating foreign processes. Source
inputs and runtime checkout code retained their hashes. The generated native
model files retained exact hashes after their constrained compiler-finalization
stage. The PE executable comparison permits only its four-byte link timestamp
and four-byte checksum to differ during vendor relinking; every other byte must
match. After the run, both complete executable hashes are checked through cleanup.

### Average Arm

The native circuit passed physical precharge, signed charge/discharge,
blocked capacitor-charging and reverse-bypass conduction, normal-path opening,
R/L measurements, capacitor energy integration and terminal power balance.
Measured arm inductance was approximately `0.020000 H`. The public equivalent
voltage convention remains `Veq = Vphysical / 2`, with `Cphysical = Ceq / 4`.
This fixture tests a half-bridge arm, not intrinsic full-bridge fault blocking.

### Cable

Each fixture uses one coupled two-conductor frequency-dependent cable, a 10 kV
source, a 100 ohm load and a 0.01 ohm ground reference. Sending and receiving
terminals stay electrically distinct. Native DTA references and the actual
runtime `.clo` hash must agree with the separately verified constants evidence.

| Length | Measured Sending Current | Independent DC Reference | Maximum Relative Current Error |
| --- | --- | --- | --- |
| 100 km | 0.085857445984309 kA | 0.0858577910670762 kA | 0.000401924% |
| 300 km | 0.067012980258288 kA | 0.06701360794622666 kA | 0.000936657% |

Both cases passed the fixed current, source-voltage, KCL, load-Ohm-law, loss and
steady-ripple criteria over 290-300 s of a 300 s run. The corrected profile
declares `DCenab=1`, functional-form correction, high-frequency error elimination,
and `shntcab=1e-10 S/m`. The analytical reference includes distributed leakage
and was independently checked against a 100-section resistive ladder. The
source geometry and source PSCX/Master files were not edited.

Constants evidence:
`D:/PSCAD-Workspace/mmc-cable-constants-dc-20260912/attempt2/Cable2_100km/evidence.json`
and the sibling `Cable2_300km/evidence.json`. These receipts record all effective
fitting parameters, source hashes, native commands, final DC-corrected fit
records and complete coefficient bodies. Geometry provenance does not establish
thermal, insulation or full-converter rating suitability.

## Preserved Failures

- Arm attempt `attempt-20260911-131216-78ea0296`: native compilation succeeded;
  the generator had not authored the nested hierarchy order. Fixed by matching
  the observed order, without relaxing semantic comparison.
- Arm attempt `attempt-20260912-121710-4b3a1035`: PSCAD relinked its executable
  during run. An initial broad executable exception was superseded by the strict
  PE metadata comparison in `e2f9c25`; rely on the final report above.
- Cable attempt `attempt-20260912-123916-2524bb62`: a fixed `GND` label conflicted
  with the sending-negative alias. Subsequent attempts exposed local cable
  configuration scope and runtime grounding constraints.
- Cable attempt `attempt-20260912-125018-8d9cd432`: full native runtime output
  identified `DSLINT: Invalid Node Numbers`; PSCAD requires finite resistance
  between a cable terminal and ground. The correction uses 0.01 ohm, above the
  simulator's 0.0005 ohm idealization limit.
- Cable attempt `attempt-20260912-125503-51f6b2a7`: the original uncorrected donor
  fit remained physically wrong after 300 s, with 12.54% current error. Merely
  extending the run was insufficient. This prompted the explicit DC-corrected
  profile; no original evidence or acceptance threshold was overwritten.

All cable failures are under
`D:/PSCAD-Workspace/mmc-cable-acceptance-20260912/`.

## Integration Status

Direct Master bindings are carried through fixed and parameterized planning and
execution. The fixed blueprint now has separate cable-end nets and a 40 MJ
nominal total capacitor-energy derivation. Unlabeled routes use `create_wire`.

At `41dd20e`, planning and saved-graph validation share cable-bypass checks and
recognize grounding by actual component definition, including source-neutral
references. At `f439a76`, the MMC reader recognizes real PSCX User/Wire objects,
infers wire namespace from observed typed contacts, and uses the existing
topology connectivity implementation for label aliases. Missing port contracts,
ambiguous intersections and malformed conductors remain unresolved, never PASS.
Native cable geometry and control scripts are not interpreted as conductors.

Verification after `f439a76`: the complete offline suite passed with
`2881 passed, 48 skipped`; fatal Ruff checks (`E9,F63,F7,F82`) and
`git diff --check` passed. Skipped opt-in tests are not licensed acceptance.

The following required implementation is still outstanding:

1. Replace the descriptive packaged companion and `master:dc_cable` placeholders
   in the actual fixed/parameterized production assembly paths.
2. Carry native component identity, audited companion port contracts, output
   selectors and net receipts through saved-graph validation and reload.
3. Construct and connect twelve native arms with real station, energy and
   circulating-current controls, then run the required startup, forward-power,
   reversal and reverse-power checks.
4. Complete the applicable full-model/fault and independent-golden acceptance.

These are implementation work, not a demonstrated external blocker. No whole
MMC completion, merge, or deployment is claimed by this component evidence.
