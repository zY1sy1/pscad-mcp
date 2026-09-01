# LCC WP1B Fixed Autonomous Physicalization Design

**Date:** 2026-08-31

**Status:** Approved design, awaiting written-spec review

**Target platform:** Licensed PSCAD 4.6.2 Legacy Automation

## 1. Purpose

WP1B replaces the fixed LCC asset's structural companion with a real,
repository-authored PSCAD companion assembled from live-audited Master
primitives. It then proves that the fixed autonomous path can load, compile,
and complete a short no-fault EMTDC smoke simulation on the current commit.

On success, WP1B may promote only:

```text
scope            = lcc.fixed_autonomous
builder_path     = lcc.fixed_autonomous
capability_state = simulated
licensed_status  = PASS
```

This is simulation readiness, not final physical acceptance. Disturbance,
commutation-failure, independent-golden, and final `accepted` verdicts remain
outside WP1B.

## 2. Authoritative correction to the program roadmap

The program roadmap's original WP1B wording required a `GATES[12]` companion
port and twelve externally supplied firing pulses. Live inspection after that
roadmap was written established a different physical contract:

- installed Master SHA-256:
  `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939`;
- official CIGRE project SHA-256:
  `f36738fbec4c9bdb0995ca73726e16d18e85c10166eaa893e6599a591d5c4a43`;
- Master contains exactly one `g6p200` Definition described as `6 Pulse Bridge`;
- the official rectifier and inverter each use two `master:g6p200` instances;
- all four official instances use `FP=0` and `View=1`;
- with `FP=0`, `AO` is the active scalar real input in radians and the bridge
  performs its own six-valve firing;
- `FPN[6]` is conditional on `FP=1` or `FP=2` and is not active in the selected
  profile;
- `fp_int` is therefore not required.

This spec supersedes only the roadmap's WP1B gate-vector details. Every
`GATES[12]`, `FPN[6]`, twelve-way split, and direct
`master:thyristor_valve` requirement for this fixed companion is replaced by
two explicit scalar angle-order connections per 12-pulse bridge. The
effective twelve-valve evidence is:

```text
2 live-audited g6p200 instances
  x 6 internal firing positions per Master definition
  = 12 effective valve positions
```

The implementation must update the library, catalog, blueprint, validator,
tests, and documentation together. It must not leave a compatibility alias
named `GATES` because that would preserve a physically false interface.

## 3. Current baseline

WP1A completed at repository HEAD
`cab5deca9a47ac2dbff7e335e3956a29490eda47`. Its evidence-bearing licensed run
at commit `c6ad59f3f7638f8b884ea4b95e44c21cd31ff56c` proved only
`lcc.blank_native -> simulated/PASS`; the final independent suite was
`2202 passed, 46 skipped`. That result unlocks WP1B but cannot be reused as
fixed-autonomous evidence.

The current fixed asset remains non-physical:

- `library/cigre_lcc_v1.pslx` contains descriptive elements such as
  `six_pulse_group`, `valve`, and `control_block`, not a load- and
  compile-proven PSCAD composition;
- it references the nonexistent logical primitive `master:thyristor_valve`;
- `catalog-pscad-4.6.2.json`, `blueprint.json`, and `validator.py` all encode
  the obsolete `GATES[12]` contract;
- `SignalInterface` and `Initialization` are structural labels rather than
  verified physical definitions;
- the packaged `golden.json` is still a licensed-reference placeholder and
  cannot support a WP1B verdict.

The current raw asset identities are retained only as before-state evidence:

| Artifact | SHA-256 |
| --- | --- |
| asset manifest | `ee62e0dcbef5a9d89e1ef23964179b0a3b78aca6f412efcc0dac6bcb914f12ad` |
| project-level Master registry | `5556079998ebcab18e535e9c40b577374bbecf1917a74c50cc9cfbf0ac5f0d81` |
| structural companion library | `1330c2add269eb6bfcde7d8b446d6d31f5933da1f73809a2f6eff89c7c50cbdb` |

## 4. Scope

### 4.1 Included

1. Live audit of every bridge, control, constant, and signal-import primitive
   against the exact installed Master.
2. A real `LCC12PulseBridge` composed from two `g6p200` instances.
3. Rectifier constant-current PI control with an explicit firing-angle
   limiter.
4. Inverter constant-extinction-angle PI control with real gamma feedback and
   an explicit limiter.
5. Deterministic enable and controller initialization.
6. Migration from `GATES[12]` to two scalar `AO` paths for each 12-pulse
   bridge.
7. Repository-authored, relative-path-only, redistributable PSLX content that
   references but does not copy Master definitions.
8. Independent component load, instantiate, read-back, reload, and compile
   fixtures.
9. Full fixed-topology integration from a blank case.
10. A short, no-fault licensed smoke simulation with real EMTDC outputs.
11. A durable fixed-autonomous report and a separate explicit promotion step.

### 4.2 Excluded

- inverter AC disturbance injection;
- commutation-failure indication or recovery acceptance;
- VDCOL, current-margin coordination, mode switching, and power reversal;
- disturbance or operating-point tuning;
- arbitrary ratings or the parametric LCC path;
- independent golden generation or comparison;
- replacement of the packaged placeholder golden;
- `accepted` capability state;
- PSCAD 5.x, MMC, and modification of installed Master or official examples.

## 5. Adopted architecture

WP1B uses one spec with two sequential implementation phases.

### 5.1 Phase A: physical companion foundation

Phase A establishes trusted primitives and proves the bridge Definition in
both terminal parameterizations:

```text
Master metadata audit
  -> companion binding audit
  -> deterministic PSLX composition
  -> library load
  -> bridge instantiate with UP=1 and UP=0
  -> parameter and active-port read-back
  -> save and reload
  -> component compile
```

Phase A must pass before controller composition begins. A failure in either
bridge parameterization cannot be hidden by compiling a larger case.

### 5.2 Phase B: controls, integration, and smoke

Phase B adds the two closed-loop controllers and deterministic initialization,
proves every new control/signal Definition in an isolated component fixture,
migrates the full blueprint to physical signal connections, compiles the
complete topology, and runs a short no-fault simulation.

The existing fixed builder keeps its plan, materialize, read-back, compile,
simulate, publish ordering. It gains an immutable verification profile named
`wp1b_smoke`, included in the plan hash and stale-plan check. This profile uses
the WP1B smoke gate and never calls the independent-golden or disturbance
acceptance evaluator. Existing full-acceptance behavior remains the default
outside the WP1B runner.

### 5.3 Rejected alternatives

- Repository-owned thyristor equations were rejected because installed Master
  has no suitable single-valve binding and the numerical/EMTDC scope belongs
  to a separate model-development project.
- Runtime extraction of official converter definitions was rejected because
  it would remain a native adapter, not a fixed autonomous companion.
- External `GATES[12]` with `FP=1` was rejected because it would additionally
  require `fp_int`, phase synchronization, and two six-pulse firing vectors.
- Open-loop fixed firing was rejected because it would not prove either
  controller is a real closed loop.

## 6. Master binding and audit contract

The existing project-level eight bindings retain their meaning. The Master
registry schema is extended with a separately named `companion_bindings`
section so project-level inventory, WP1A historical evidence, and companion
composition cannot be conflated.

| Logical companion role | Physical Definition | Required evidence |
| --- | --- | --- |
| `master:six_pulse_bridge` | `g6p200` | unique Definition, description, conditional ports, complete active parameter profile |
| `master:control_sum` | `sumjct` | real scalar inputs/output and exact enabled-input signs |
| `master:control_pi` | `pi_ctlr` | scalar `IN`/`OUT`, `GP`, `TI`, `YHI`, `YLO`, `YINIT`, integration mode |
| `master:control_limiter` | `hardlimit` | scalar `I`/`O`, internal `UL`/`LL`, `Dim=1`, `Limit=0` |
| `master:control_minimum` | `maxmin` | real scalar inputs/output, minimum mode, exactly two enabled inputs |
| `master:control_product` | `mult` | real scalar two-input product used only for enable gating |
| `master:real_constant` | `const` | real scalar order and initialization source |
| `master:integer_constant` | `consti` | integer scalar enable/block source |
| `master:signal_import` | `import` | unique named real-signal import and scalar output |

The selected `g6p200` profile is fixed and fully read back. No implementation
may rely on an unrecorded vendor default.

| Parameter | Group Y | Group delta | Contract |
| --- | ---: | ---: | --- |
| `UP` | terminal mode | terminal mode | rectifier `1`, inverter `0` |
| `FP` | `0` | `0` | scalar angle order in radians |
| `SNUB` | `1` | `1` | snubber enabled |
| `View` | `1` | `1` | active `N`, `DP/DN`, `AO`, `AM/GM`, `KB/CB` profile |
| `KV` | `-2` | `-1` | official group profile |
| `FR` | `50 Hz` | `50 Hz` | fixed benchmark frequency |
| `GP` | `10.0` | `10.0` | official bridge profile |
| `GI` | `50.0` | `50.0` | official bridge profile |
| `KP` | `0` | `0` | official bridge profile |
| `RON` | `0.01 ohm` | `0.01 ohm` | on-state resistance |
| `ROFF` | `100000000 ohm` | `100000000 ohm` | off-state resistance |
| `RD` | `5000 ohm` | `5000 ohm` | snubber resistance |
| `CD` | `0.05 uF` | `0.05 uF` | snubber capacitance |
| `EFVD` | `0 kV` | `0 kV` | forward-voltage profile |
| `EBO` | `100000 kV` | `100000 kV` | breakover profile |
| `TEXT` | `0 us` | `0 us` | external delay profile |
| `Tblock` | `0.04 s` | `0.04 s` | block timing profile |
| `RWSAFB` | `0` | `0` | official profile |
| `RWV` | `100000` | `100000` | official profile |
| `PFB` | `0` | `0` | official profile |

Empty display/signal-name parameters are also recorded canonically, rather
than omitted from the deterministic component profile.

For `FP=0` and `View=1`, the active-port audit must resolve exactly one
occurrence of each selected physical port:

```text
N[3]       electrical
DP         electrical
DN         electrical
AO         real scalar input, rad
AM         real scalar output
GM         real scalar output
KB         integer scalar input
CB         integer scalar input
```

`FPN` and `FDT` must not be selected in this profile. Missing, duplicated, or
simultaneously active conditional alternatives fail before materialization.

## 7. Companion definitions

### 7.1 `LCC12PulseBridge`

The public bridge interface is:

| Port | Kind | Dimension | Direction | Meaning |
| --- | --- | ---: | --- | --- |
| `ACY_A/B/C` | electrical | 1 each | bidirectional | Y-group AC terminals |
| `ACD_A/B/C` | electrical | 1 each | bidirectional | delta-group AC terminals |
| `DC_POS` | electrical | 1 | bidirectional | positive DC terminal |
| `DC_NEG` | electrical | 1 | bidirectional | negative DC terminal |
| `AO_Y` | real data | 1 | input | Y-group angle order, radians |
| `AO_D` | real data | 1 | input | delta-group angle order, radians |
| `ENABLE` | integer data | 1 | input | common bridge enable |
| `AM_Y/AM_D` | real data | 1 each | output | measured firing-angle evidence |
| `GM_Y/GM_D` | real data | 1 each | output | measured extinction-angle evidence |

The Definition contains exactly two `master:g6p200` instances. Their `N[3]`
ports bind to the separate AC groups. Their `DP/DN` terminals form one common
series DC path with one internal midpoint. `AO_Y` and `AO_D` connect directly
to the corresponding physical `AO` ports. `ENABLE` is restricted to integer
`0` or `1` and drives each block input as `KB = 1 - ENABLE`; both `CB` inputs
are tied to integer `0` for the WP1B no-fault profile.

The same Definition is instantiated twice in the full model. The rectifier
instance sets both internal bridges to `UP=1`; the inverter sets both to
`UP=0`. Save/reload evidence must prove the terminal-specific value and the
DC polarity mapping.

The wrapper contains no copied Master Definition body and no fabricated
individual valve records. Its structural assertion is exactly two audited
six-pulse bridge instances and one verified DC series path.

### 7.2 `RectifierControl`

The revised public interface is:

```text
inputs:  VDC, IDC, IORDER, ENABLE
outputs: AO_Y, AO_D, ALPHA
```

`AO_Y`, `AO_D`, and `ALPHA` are scalar real signals in radians. The control
computes a signed current error with audited `sumjct`, gates it with `ENABLE`
through audited `mult`, applies one audited `pi_ctlr`, and applies an audited
`hardlimit` to the firing-angle order. The limited scalar output fans out to
`AO_Y` and `AO_D`; there is no pulse-vector generation.

The closed-loop sign is fixed as:

```text
enabled_error = ENABLE * (IDC - IORDER)
alpha_command = LIMIT(alpha_min, alpha_max, PI(enabled_error))
```

Increasing measured current therefore increases alpha and opposes the current
error. `VDC` is connected and recorded as controller telemetry but does not
enter the minimal WP1B current law; VDCOL remains a WP1C addition.

The fixed asset retains `IORDER=1.0 kA` and the existing initial
`AlphaOrder=15 deg` (`0.2617993877991494 rad`) as deterministic defaults.
PI gain, integral time, output limits, and `YINIT` are explicit typed asset
parameters, included in the companion hash and read-back report. `YINIT` must
equal the declared initial angle so the first simulation step is deterministic.

### 7.3 `InverterControl`

The revised public interface is:

```text
inputs:  VDC, IDC, GM_Y, GM_D, GAMMA_ORDER, ENABLE
outputs: AO_Y, AO_D, GAMMA
```

The controller uses audited `maxmin` in minimum mode to select the lower of
`GM_Y` and `GM_D` as the conservative gamma feedback, computes
extinction-angle error with audited `sumjct`, gates the correction with
`ENABLE` through audited `mult`, applies one audited `pi_ctlr`, and applies an
audited `hardlimit`. The limited scalar order fans out to `AO_Y` and `AO_D`.
`GAMMA` exposes the same feedback value used by the loop.

The closed-loop sign is fixed as:

```text
gamma_feedback = MIN(GM_Y, GM_D)
enabled_error  = ENABLE * (GAMMA_ORDER - gamma_feedback)
ao_command     = LIMIT(ao_min, ao_max, PI(enabled_error))
```

For the audited `UP=0` profile, a positive low-gamma error increases the
angle-order command. `VDC` and `IDC` are connected and recorded as telemetry
but do not enter the minimal WP1B gamma law; current-margin coordination and
VDCOL remain WP1C work.

The fixed `GAMMA_ORDER` remains `18 deg`
(`0.3141592653589793 rad`). All transfer to `g6p200.AO` is in radians. Any
degree-form display or report value must be an explicit conversion and cannot
change the physical AO unit.

### 7.4 `Initialization` and signal ownership

`Initialization` becomes a real instantiated Definition, not a metadata tag.
It owns only deterministic fixed orders, initial PI state, and enable state.
For WP1B it produces one rectifier order, one inverter gamma order, and
terminal enable signals from audited `const`/`consti` instances. The fixed
no-fault schedule is `ENABLE=1` from `t=0` through the complete `0.1 s` smoke;
deterministic PI `YINIT` values own initialization. It must not contain a
disturbance, VDCOL, power reversal, or mode transition.

`SignalInterface` is retained only as a real, instantiated signal adapter for
meter-owned named `VDC_RECT`, `VDC_INV`, and `IDC` outputs. It uses audited
`import` instances, must resolve exactly one producer for each required name,
and exposes typed scalar ports to the controllers. `GM_Y` and `GM_D` are wired
directly from the inverter bridge to `InverterControl` and do not pass through
a named import. A zero-port `interface_contract` element is invalid.

Both definitions must load, instantiate, read back, and compile during the
control-fixture gate at the start of Phase B. If the audited `master:import`
profile cannot resolve a unique named signal, Phase B fails before
full-topology materialization; the implementation may not replace feedback
with a constant.

## 8. Blueprint and catalog migration

Catalog, blueprint, and validator changes are atomic at the asset level.

1. Remove `GATES` from bridge and both controller definitions.
2. Add `AO_Y` and `AO_D` as scalar real ports with radian semantics.
3. Add bridge `ENABLE`, `AM_Y/AM_D`, and `GM_Y/GM_D` contracts.
4. Add controller feedback ports and physical parameter contracts.
5. Replace each old gate net with two explicit AO nets. The full two-terminal
   topology therefore has four AO nets:

```text
rectifier_control.AO_Y -> rectifier_bridge.AO_Y
rectifier_control.AO_D -> rectifier_bridge.AO_D
inverter_control.AO_Y  -> inverter_bridge.AO_Y
inverter_control.AO_D  -> inverter_bridge.AO_D
```

6. Add explicit order, enable, current, voltage, and gamma feedback nets. No
   required control input may remain unconnected.
7. Add or reconfigure DC meters so the named producers `VDC_RECT`, `VDC_INV`,
   and `IDC` each exist exactly once and are imported by `SignalInterface`.
8. Use two converter-transformer secondaries per terminal so both ACY and ACD
   groups are electrically supplied. The fixed blueprint must not leave either
   three-phase bridge group unconnected.
9. Preserve separate source buses, smoothing reactors, DC line, return, and
   ground ownership. WP1B verifies connectivity and compile, while WP1C owns
   grounding adequacy and physical tuning acceptance.
10. Replace valve-list assertions with two-`g6p200`, active-`AO`, `FP=0`,
   terminal `UP`, and DC-series-path assertions.
11. Add smoke-only outputs for time, `IDC`, both terminal DC voltages, four AO
    orders, gamma feedback, and enable state. These are not a golden contract.

`acceptance.json` and placeholder `golden.json` cannot participate in the
WP1B verdict. The manifest gains a separately named smoke contract whose hash
is included in plan and report identities.

## 9. Audit and validator boundaries

A focused companion module owns physical PSLX validation and live Definition
evidence. `validate_companion_library()` remains a compatibility entry point
but delegates to that module. General topology comparison remains in
`validator.py`.

The physical companion audit must prove:

- exact custom Definition set and unique scoped names;
- real PSCAD Definition/form/svg/schematic content, not descriptive XML tags;
- exact external typed ports and parameters;
- exact internal Master instance identities and cardinalities;
- exact internal connections, including AO and DC series paths;
- active conditional-port profile for every Master child;
- no unresolved or foreign Definition;
- no vendor script/form/svg/Definition body copied into the companion;
- no absolute drive, UNC, user-profile, official-project, or workspace path;
- no structural-only `valve`, `six_pulse_group`, `control_block`,
  `interface_contract`, or `initialization_contract` used as physical proof;
- deterministic canonical hash after parse and reload.

Offline XML audit is necessary but not sufficient. Only licensed load,
instance read-back, and compile can produce physical PASS evidence.

## 10. Build and evidence flow

### 10.1 Run phase

```text
clean named commit
  -> WP0 static/licensed preflight
  -> source, Master, registry, manifest hashes
  -> companion Master audit
  -> Phase A bridge fixtures
  -> Phase B control and signal fixtures
  -> fixed immutable plan with wp1b_smoke profile
  -> materialize companion and blank case
  -> place/connect/read back full topology
  -> save/reload identity audit
  -> full compile
  -> short no-fault simulation
  -> real output discovery and smoke checks
  -> publish final fixed project
  -> cleanup owned PSCAD session
  -> before/after immutability checks
  -> durable fixed-autonomous report
  -> strict report re-index
```

The run phase writes only a fresh timestamped directory under the configured
acceptance workspace. It never updates the checked-in program baseline.

### 10.2 Smoke contract

The default licensed smoke duration is `0.1 s` at the fixed asset's
`50 us` EMTDC and output steps. A PASS requires all of the following:

- every Phase A bridge fixture and Phase B control/signal fixture compiled
  after load and reload;
- the complete fixed topology compiled from a blank case;
- EMTDC time is numeric, strictly increasing, begins at or after `0`, and
  reaches the configured duration within one output step;
- required output channels are present exactly once and have a common valid
  time domain;
- every required sample is finite, with no `NaN` or infinity;
- both terminal controls and both bridges are enabled in the declared enabled
  window;
- all four AO channels remain within their configured hard limits;
- PSCAD reports no compile or runtime error;
- output artifacts are regular files owned by the run workspace;
- project, companion, output, journal, and report artifacts are hashable;
- source, Master, registry, manifest, and compiler identities are unchanged;
- the owned PSCAD session exits and remaining PSCAD processes equal zero.

The smoke contract deliberately does not require rated voltage, power balance,
low ripple, disturbance response, commutation failure, recovery, or golden
waveform similarity.

### 10.3 Promotion phase

Promotion is a separate operator action and reuses the strict WP1A promotion
infrastructure. It requires a clean checkout at the report commit, re-indexes
the report, rechecks all current hashes, advances current-commit truth, and
applies only the `lcc.fixed_autonomous` report.

Promotion must not preserve an older current-commit PASS for a different
scope. Older evidence remains historical, while untouched scopes keep their
proven capability state and lose stale current-commit evidence according to
the existing advancement rules.

## 11. Durable report contract

The fixed runner and CLI follow the existing explicit `run` and `promote`
split. A PASS report contains:

```text
scope            = lcc.fixed_autonomous
builder_path     = lcc.fixed_autonomous
kind             = licensed_simulation
capability_state = simulated
status           = PASS
```

Required evidence groups are:

1. repository branch, full commit, and clean state;
2. PSCAD 4.6.2 backend, license, x64, and compiler identities;
3. Master before/after hash and companion binding audit;
4. registry, asset manifest, catalog, blueprint, library, provenance, and
   smoke-contract hashes;
5. Phase A bridge results and Phase B control/signal fixture results, including
   load, instance ID, active ports, parameters, reload identity, and compile;
6. immutable plan hash and full fixed build journal;
7. published project and companion hashes;
8. selected output plus every legacy numbered part and metadata hash;
9. time-domain, finite-sample, enable, AO-limit, and runtime smoke evidence;
10. process inventory before/after and cleanup result;
11. strict explicit exclusions.

PASS exclusions are exactly:

```text
disturbance_acceptance
commutation_failure_acceptance
independent_golden
final_accepted
```

A FAIL report uses `capability_state=failed`, records the earliest failing
stage and structured error, preserves all evidence already produced, and uses
`null` for artifacts that do not exist. FAIL is durable but never promotable.

## 12. Failure and cleanup semantics

The following conditions fail closed:

- Master Definition missing, duplicated, unreadable, or conditionally
  ambiguous;
- `FP`, `View`, `UP`, AO, electrical port, or fixed parameter mismatch;
- any live `FPN`/`FDT` selection under the `FP=0` profile;
- registry, source, manifest, companion, plan, or compiler drift;
- vendor Definition body, foreign scope, absolute path, or structural-only
  physical claim in the companion;
- missing or extra internal Master instance or wrong internal connection;
- component identity, active ports, parameters, polarity, or connection drift
  on read-back or reload;
- signal adapter lacks one real producer for a required feedback;
- component or full-topology compile failure;
- smoke output missing, ambiguous, outside ownership, invalid in time, nonfinite,
  disabled, out of AO bounds, or accompanied by a runtime error;
- publication hash/identity mismatch;
- source or Master mutation during the run;
- shutdown failure or remaining PSCAD processes.

Read-back failure stops before compile where possible. The runner unloads or
rolls back only its own fixture/project and keeps its failure workspace and
report. It must not wildcard-kill PSCAD or touch a user-owned process. If an
owned process cannot be closed normally, cleanup evidence forces FAIL and the
operator closes it manually.

## 13. Testing strategy

### 13.1 Offline contract tests

- strict companion-binding schema and Master metadata audit;
- exact `FP=0`/`View=1` conditional-port selection;
- rectifier `UP=1`, inverter `UP=0`, and group-specific `KV` profiles;
- exactly two `g6p200` instances and one DC series path per bridge;
- absence of `GATES`, `FPN`, `FDT`, `fp_int`, and fabricated valve children;
- exact scalar AO ports and four full-topology AO nets;
- PI, limiter, enable, initialization, and feedback ownership;
- catalog/blueprint/library/manifest/provenance hash consistency;
- structural-only, vendor-body, absolute-path, foreign-scope, and unknown
  Definition rejection;
- smoke and report strict schemas, canonical serialization, and atomic writes;
- FAIL and incomplete report promotion rejection.

### 13.2 Fake-service lifecycle tests

- exact audit, load, instantiate, read-back, save, reload, compile order;
- component fixture isolation and owned rollback;
- wrong active port, parameter, orientation, polarity, or connection failure;
- source/Master/registry/manifest change before and after mutation;
- stale verification profile or plan hash rejection;
- no full compile after component compile failure;
- no smoke after full compile failure;
- invalid time, missing/nonfinite output, disabled control, AO bound failure,
  timeout, runtime error, and cleanup failure;
- durable FAIL report written after cleanup evidence;
- run phase leaves the program baseline byte-identical;
- promotion changes only `lcc.fixed_autonomous` after commit advancement.

### 13.3 Licensed Phase A gate

On a clean exact commit, load and compile isolated fixtures for:

- `LCC12PulseBridge` in rectifier mode;
- `LCC12PulseBridge` in inverter mode;

Each bridge fixture must instantiate, read back, save, reload, read back again,
and compile. No Phase A result is inferred from the full topology.

### 13.4 Licensed Phase B gate

First load, instantiate, read back, save/reload, and compile isolated fixtures
for `RectifierControl`, `InverterControl`, `Initialization`, and
`SignalInterface`. Only after all four pass, create a fresh blank case through
the production fixed builder, materialize the complete topology, verify every
required connection, compile, run the `0.1 s` no-fault smoke, discover real
output files, evaluate only the smoke contract, publish, cleanly exit, and
write/re-index the durable report.

After the report passes, execute explicit promotion and then run focused
baseline tests. The final branch gate also requires the complete repository
suite, targeted Ruff checks, PowerShell parser validation, whitespace checks,
and independent code/spec review with no unresolved critical or important
finding.

## 14. Expected implementation surface

The implementation plan may refine file grouping but must preserve these
ownership boundaries:

- packaged asset: companion registry section, library, catalog, blueprint,
  smoke contract, manifest, and provenance;
- companion physical audit: a focused new module, with
  `validate_companion_library()` as a delegating compatibility entry point;
- fixed plan/executor: immutable `wp1b_smoke` profile, AO ports/nets,
  read-back, smoke gate, and rollback;
- fixed acceptance orchestration: strict report, `run`/`promote` CLI, and
  PowerShell runner;
- tests: offline asset/audit, planner/validator/executor fakes, component
  licensed gate, full fixed licensed smoke, report, and promotion;
- documentation: completion record and current-truth transition only after the
  licensed result exists.

No implementation file is changed by this design commit.

## 15. Exit criteria and handoff

WP1B is complete only when:

- both Phase A bridge parameterizations and all Phase B control/signal
  Definition fixtures pass licensed load/read-back/reload/compile;
- the full fixed topology compiles from a blank case;
- the no-fault smoke satisfies every WP1B smoke requirement;
- source, Master, registry, manifest, and compiler identities remain stable;
- the durable report is strict, hash-complete, re-indexed, and `PASS`;
- PSCAD cleanup is complete with zero remaining process;
- explicit promotion changes only `lcc.fixed_autonomous` to
  `simulated/PASS`;
- all four exclusions remain present and `accepted` is not claimed;
- focused/full tests, lint, script parsing, and independent review pass.

WP1B then hands WP1C a physically loadable fixed companion, explicit AO
interfaces, real closed loops, a compiled/simulated blank-case project, and a
current-commit smoke report. WP1C remains responsible for grounding adequacy,
operating-point tuning, disturbance injection, commutation-failure evidence,
bounded response, and recovery. WP6 remains responsible for the independent
golden and final `accepted` verdict.
