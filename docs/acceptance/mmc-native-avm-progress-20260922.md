# Native MMC AVM implementation evidence, 2026-09-22

The public parameterized cable AVM now constructs a native two-station,
twelve-arm model, preserves the authored XML, checks compiler finalization,
and leaves unaccepted candidates in staging. Complete MMC acceptance and
publication are still pending. A steady operating envelope PASS is narrower
than the required startup, protection, fault, and complete physical contracts.

## Measured startup closure and current control work

At `0d7c1cd`, the default 40 MJ request passes measured precharge, forward and
reverse steady envelopes, and network identities. It deblocks at **0.2974 s**
after both stations satisfy the voltage, current, and energy-convergence hold;
time alone cannot release the valves. Peak precharge current is 1.473304 kA,
the final hold current is at most 0.055451 kA, and the station-energy excursion
over the two-cycle hold is 1.1935% (limit 2%). Operating windows are anchored
to the recorded readiness transition, and the requested one-second power
reversal still lasts one second.

- Report: `D:/PSCAD-Workspace/mmc-native-avm-precharge-20260922/attempt-20260922-230206-81f38406/report.json`.
- SHA-256: `44d382427514b08b8a4a79ae9497002b0a63694b5859118f32016bad93a86694`.
- Source and code hashes unchanged; owned PID 49328 exited.
- Complete offline regression at this revision: **2949 passed, 48 skipped**,
  134.38 s.

This remains a scoped result: steady insertion margin and arm-energy ripple
do not yet meet the complete physical contract. Subsequent controller work
is not covered by this historical PASS.

Later work adds a bounded circulating-current integrator and exposes its
actual state/reference. A compiled native-Fortran regression closes the exact
controller equations around an RL plant and verifies rejection of positive
and negative voltage bias plus reset while blocked. This removes the large
mean energy offset seen with proportional-only circulating control, but did
not by itself stabilize all parameterized operating points. An unfiltered
power-feedforward experiment worsened the result and was reverted. The arm
off-state resistance is restored to 100 Mohm; a per-device vendor default of
1 Mohm created unintended leakage when applied to an entire averaged stack.

The experimental `dq_current` path now contains an explicit synchronous-frame
PLL and dq current controllers. Native-Fortran tests cover frequency changes,
phase steps, loss of voltage, and bidirectional current/power tracking through
an inductive plant. PLL lock acquisition requires a two-cycle hold; genuine
voltage loss clears lock immediately, while sustained phase/frequency loss
uses hysteresis to avoid repeated blocking on a brief phase transient. Its
licensed two-station acceptance is still being completed. Neither tests nor
an independent-controller result establish whole-model acceptance.

Two concurrent attempts at `d589f84` encountered a vendor runtime socket
conflict (`WinSock #10048` on port 30129) and a companion run stopped at
0.0901 s. These reports are retained under `mmc-native-avm-circpi*-20260922`.
Their owned instances exited. Later licensed runs are serialized, while
keeping isolated workspaces and ownership checks. The runner now rejects
incomplete time coverage before interpreting precharge and distinguishes
runtime interruption from a complete-run physical failure.

Candidate directory hashes use a 20-character prefix to avoid PSCAD 4.6's
legacy path-length limit. Full plan hashes remain in the evidence; an existing
candidate directory is never reused. Native compiler page-bound warnings
also remain a delivery/layout issue to close.

## Earlier implementation and evidence

The following results supersede the original implementation below within their
declared scope. **Full model acceptance remains pending.** The native public
builder continues to retain candidates in staging and does not publish them.

- Full offline regression at `3dcf54f`: **2944 passed, 48 skipped**, 139.71 s.
- Single-arm licensed acceptance at `c4a2301`: PASS, source/code immutable,
  managed PID 35692 cleaned. Report:
  `D:/PSCAD-Workspace/mmc-average-arm-acceptance-20260922/attempt-20260922-220023-63615a3e/report.json`;
  SHA-256 `ce67fd9e178580f7a04d76aa5066d1569db1563fac3d6aa601be8d9d833d9ada`.
- Public native AVM at `fea47ff`, with an explicit **48 MJ** engineering
  request: assembly, forward/reverse steady envelopes, and independent
  network identities PASS. Source/code immutable, managed PID 35256 cleaned.
  Report: `D:/PSCAD-Workspace/mmc-native-avm-energy48-20260922/attempt-20260922-221153-d87c0fed/report.json`;
  SHA-256 `75ac0e567702991f73f2119aed4ff0a94a6779540ddf9b0b0e317c058147c7f8`.
  This is a different request from the original 40 MJ reference, and is not
  evidence that the default 40 MJ configuration passed at this revision.
- The default 40 MJ request at `c4a2301` passes network identities but fails
  steady DC-voltage excursion. Its report remains FAIL:
  `D:/PSCAD-Workspace/mmc-native-avm-public-acceptance-20260922/attempt-20260922-220023-5606ec02/report.json`,
  SHA-256 `498280fa9f9b5efa7af9e6449561cb8101626c6e6fb225ca79a319b7b1a64e68`.
  The P-terminal peak deviations are 12.1161% forward and 10.1047% reverse;
  the unchanged limit is 10%. Managed PID 36412 was cleaned.

The 48 MJ request still exhibits clipped insertion commands and insufficient
modulation margin. Neither its energy-ripple diagnostics nor its startup,
PLL, protection, reversal dynamics, or fault behavior have a full PASS.

Implemented consistency repairs:

- Equation version v3 computes grid impedance from the requested AC voltage
  and SCR, without a second DC-voltage scaling. A native fixture's explicit
  grid resistance is included in the requested total, not added on top.
- Cable planning freezes the actual coaxial geometry and per-core DC
  resistance. Both candidate and generated constants must agree. A 100 km
  VSCTrans pair has approximately 16.59826 ohm loop resistance; this does not
  scale with converter ratings. Unrelated PWM/overhead estimates are retained.
- Native arm non-ohmic loss budgeting uses valve-side apparent current,
  including reactive power. Native controller gains and filter times now
  consume the declared candidate bandwidth and rating scales. Explicit Vdc
  PI overrides have physical units, including MW/kV and normalized seconds.
- The native model declares 1 Mohm pole and valve common-mode grounding and
  records their losses. Its public arm open resistance uses the installed
  vendor's 1 Mohm value. These changes alone did not resolve the startup
  matrix error exposed by extra series arm ammeters; the failed attempts are
  retained. Eliminating those additional branches removed the matrix error.
- Arm current is observed on the existing physical resistor branch. Native
  DSDYN copies align independent terminal currents/voltages with those arm
  exports. An ordinary gain was insufficient because PSCAD scheduled it in
  DSOUT. The explicit sampling component passes strict KCL (1e-9 kA), pole
  voltage identity (1e-6 kV), energy/capacitance identity (1e-9 relative), and
  modulation-clipping identity checks. No OUT samples are shifted afterward.
- Near zero charge, the explicit non-ohmic sink is limited by available
  capacitor charge across the two-step interface. This eliminated an observed
  approximately -55 V startup excursion; the retained minimum after repair is
  roundoff, approximately -4e-13 kV. Rated-voltage loss remains unchanged, and
  measured loss power is exported for energy accounting.
- Negative Q commands and phase offsets are permitted by their native forms.
  Actual P/Q/Vdc controller references are now exported. The acceptance runner
  can load a complete request JSON and binds its hash into immutable evidence.

Diagnostic requests and failed runs are preserved under
`D:/PSCAD-Workspace/mmc-native-avm-controls-20260922` and the corresponding
`mmc-native-avm-*-20260922` attempt directories. Lowering modulation to 0.8,
reducing the common bandwidth to 64 Hz, or increasing energy to 80 MJ with
modulation 0.8/0.82 did not establish physical acceptance. Voltage oscillation
has a dominant 6–7 Hz component. Further Vdc-loop tests use explicit frozen
requests, preserve the same envelope limits, and remain diagnostics until all
required physical checks pass.

## Earlier frozen result

- Revision: `7a186fbc67d51f1296a326f3d6a27726b5c4ecc6`.
- Report: `D:/PSCAD-Workspace/mmc-native-avm-public-acceptance-20260922/attempt-20260922-205626-5eda1190/report.json`.
- Report SHA-256: `d31745e1d0bcf19c6bebcf8122cc965108ce7f29817f64b0a36725097bd4c369`.
- Native PSCAD 4.6.2 run: 3 s, 30,001 samples, 88 identity/unit-bound channels.
- Assembly and steady operating envelope: PASS. `model_accepted` remains false.
- Source inputs and source code retained their hashes. Managed PID 25004 exited.
- Both project and library passed semantic finalization. The generated-module
  v2 policy records the vendor's direct Main hierarchy permutation and compares
  calls by unchanged link/name identity only with automatic sequencing enabled.
  Parameters, wiring, scripts, identities, and nested calls remain protected.
- Public build state is `built`, and the requested final target is absent.
  A compiled candidate cannot be promoted by the parent lifecycle until the
  required dynamic physical acceptance has been supplied.

| Metric | Forward, 0.6–0.9 s | Reverse, 2.5–2.8 s |
| --- | ---: | ---: |
| P-terminal active power mean | 1000.334811 MW | -1000.953945 MW |
| Active power NRMSE, limit 5% | 1.906299% | 0.253691% |
| P-terminal maximum DC voltage deviation, limit 10% | 9.519835% | 7.622229% |
| Vdc-terminal maximum DC voltage deviation, limit 10% | 6.498452% | 3.662829% |
| P-terminal peak DC current, limit 1.25 pu | 1.057715 pu | 1.082116 pu |
| Vdc-terminal peak DC current, limit 1.25 pu | 1.048942 pu | 1.104664 pu |

Reactive power RMS errors also pass the declared 5% rated-power envelope in
both windows. The reversal starts at 1 s and lasts the requested 1 s; the
reverse window is calculated from the completed ramp. The voltage/current
limits retain the public scenario contract; the additional P/Q tracking
limits are explicit in `native_envelope.py`. These checks do not establish
all modulation, PLL, startup, fault, or energy-ripple requirements.

The generated project and native library are under the report directory:
`workspace/.mmc-candidates/88d58ff13321d86f2ba7108622792ef917f36846802991db2b55c3235be68ebf/avm-0/model/`.
The project is `AVM_88d58ff13321_avm_0.pscx`; the library is
`cigre_mmc_avm_v1.pslx`. Their pre-compiler XML is retained in the sibling
`authored-models` directory. The cable constants and their source receipts are
retained with the candidate.

## Repairs and retained counterexamples

The previous instantaneous power feedback mixed primary current with secondary
voltage; the generator now measures both on the primary side. The converter
uses its measured valve-side voltage reference, with rotating-frame filtering,
instead of assuming the transformer has no phase shift. P/Q control, cascaded
Vdc/P control, capacitor-voltage normalization, circulating-current control,
and total/differential arm-energy feedback are implemented in native components.

The PSCAD parallel PI implements `GP*e + integral(e/TI)`. Passing small GP and
an unscaled integral time caused immediate saturation. Scaling the PI input
and setting GP=1 realizes the intended `Kp*(e + integral(e/Ti))` response.
Also, a unary symbolic negative limit compiled as zero: a native gain block
now generates the negative power-correction limit. The voltage-reference
filter uses its explicit Timezero reset to honor a zero initial value.

The voltage/current-source arm interface introduced numerical energy. At
50 microseconds, measured terminal/storage accounting exposed approximately
450 MW of artificial power per station. A 2-microsecond diagnostic reduced
that error to approximately 18 MW, confirming timestep dependence. The arm
now predicts capacitor drive voltage across both interface delays while
retaining the actual native capacitor state. An analytic voltage-driven RLC
regression verifies bounded damped response and timestep convergence.

The affected single-arm licensed gate passed at
`b2c9dd239aca1d6abc03c6ab58391dade15ee377`:
`D:/PSCAD-Workspace/mmc-average-arm-acceptance-20260922/attempt-20260922-193051-7054b77a/report.json`,
SHA-256 `e640f5c38b37d896decb4976dfcaa35567a4dedf1af09a90986f3ba31754229b`.
Its source hashes remained unchanged and managed PID 50376 exited.

All failed and diagnostic attempts remain in the dated workspace directories.
In particular, the stricter envelope rejected reports where the average DC
voltage looked correct but individual samples exceeded 10%. No envelope
threshold was increased to obtain the passing result.

## Work still required

1. Close the complete modulation, PLL/dq, protection, power/loss balance,
   and arm-energy/ripple contracts with fresh licensed evidence. Network
   identities and measured precharge have separate scoped PASS evidence.
2. Complete the applicable native AVM fault scenarios and recovery acceptance.
   Existing PWM timing/fault work remains owned by its separate worktrees.
3. Complete native modulation/ripple sizing consistency and validate additional
   requested operating points. Native cable geometry and DC resistance are
   already bound into planning and verified against generated constants.
4. Complete independent reload/portable dependency delivery and the accepted
   candidate promotion path. Fixed-profile golden acceptance still requires
   an independently reviewed reference; no golden data has been fabricated.

The complete offline suite on frozen revision `7a186fb` passed with **2919
passed and 48 skipped** in 136.27 s, with licensed acceptance opt-ins cleared
in the test process. This does not replace the remaining licensed physical
acceptance.
