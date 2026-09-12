# MMC Fault Evidence Execution

- Branch: `codex/mmc-fault-evidence`
- Baseline: `45069e213fb4f4895599d5269711c57b409db33f`
- Interpreter: `D:/pscad-mcp/.venv/Scripts/python.exe`
- Working directory: `D:/pscad-mcp/.worktrees/mmc-fault-evidence`
- Baseline command: `python -m pytest tests/test_mmc_template_native.py tests/test_mmc_template_audit.py tests/test_blank_mmc_service.py tests/test_mmc_acceptance.py tests/test_output_discovery.py tests/test_hvdc_vsc_mmc_profiles.py -q`
- Observed: `45 passed, 2 skipped in 1.62s`; concurrent-support ancestor check exited 0.

## Checklist

- [x] Read acceptance rules and verify isolated baseline.
- [x] Run and record focused baseline.
- [x] Locate official full-bridge cells and actual fault switch implementation.
- [x] Freeze reachable-instance channel and physical contracts.
- [x] Instrument derived copies and verify save/reload identity.
- [x] Implement strict identity, metadata, time, units and physical evaluation.
- [ ] Run licensed steady state and fault/recovery cases with owned process cleanup.
- [ ] Independently recalculate evidence and freeze channel handoff.
- [ ] Integrate the final A schedule contract and rerun affected acceptance.

## Pre-Run Engineering Criteria

These are new case-specific engineering criteria, not an existing vendor
full-bridge certification specification. The existing fault-current upper bound
of 20 kA is retained. The official 640 kV DC and -900 MW terminal-2 setpoints
define the nonzero operating point. Recovery compares stable complete-cycle
windows before and after the event: DC voltage and active power within 5%, arm
RMS current within 10%, and summed capacitor voltage within 5%. A measured
pre-fault operating point below 90% of the declared voltage or power magnitude
cannot serve as a recovery reference. Voltage and power mean must have the
declared signs. Mean-normalized RMS variation is bounded by 5% for DC voltage
and power; arm RMS is checked on equal-duration windows covering whole 60 Hz
cycles. Independent cycle RMS variation is bounded by 5%. Voltage and terminal-2
controlled power must also be within 5% of their declared nominal reference;
the 90% floor alone is insufficient. These strengthened criteria were fixed
before the third attempt.

Every arm must demonstrate physical negative terminal voltage below -1 kV
during the fault window and physical firing-based blocking, followed by
unblocking throughout the electrical recovery window. The -1 kV threshold is
well above numerical roundoff and below one nominal cell's voltage (640/76 kV).
Actual fault switch state is taken from OPENBR, not the protection pulse named
`Fault mode` or the scheduled fault command.

## Source Findings

The original project SHA-256 is
`1900be93877400fba228b1808a5310980d801b0260d7df998df6c5a2f6a035dd`;
the original companion library SHA-256 is
`08466778704e547d7d9d80af99a48c09292dd3a51056ac26216c3913d5cc3a1b`.
Main reaches two MMC_Hb_PWM instances and three pole instances in each, hence
twelve arms. Shared Definition owner IDs alone identify only prototypes.
FullCellR_n uses DTBP=0 and FiringHBridge. Its external Ntop/Nbtm electrical
ports are valid terminal-voltage sources; its a/b nodes are internal and
conditional. Vc is a 76-element submodule capacitor-voltage vector.

The installed master:fault_sw exposes actual branch current as Iflt but exposes
OPENBR state only to animation. A derived-only clone can append an output for
that exact state while preserving the original electrical implementation.
The project's timer DF is 0.01 s, while the old materializer writes only the
unrelated forwarded FltDur parameter. This discrepancy requires an explicit
timer binding and waveform verification.

## Licensed Diagnostic Attempts

- `fault-evidence-20260908T034450263758Z`: owned PID 20540, licensed startup
  succeeded. First save reallocated the virtual Station document-root link;
  the original strict identity check stopped before compilation. Cleanup passed.
- `fault-evidence-20260908T034749658223Z`: both copies loaded, saved, compiled,
  simulated and produced all 56 required physical channels. No missing channel
  or invalid time/unit evidence. The actual fault lasted from 2.50025 to
  2.51275 seconds, confirming both the unrelated FltDur binding and the
  current-zero-only clearing behavior. Each of twelve arms showed physical
  negative Ntop-minus-Nbtm voltage during the fault and physical blocking.
  The 20 kA fault-current check passed. Nominal operating point and recovery
  failed. All owned processes exited and original inputs remained immutable.

The common Ntop-minus-Nbtm polarity is retained for every cell group; all source
cell instances have orient=0, and positive insertion is the normal series arm
voltage drop in that port direction. The negative-insertion check requires
each arm to demonstrate the opposite terminal polarity at some instant during
the applied fault, not all arms at the same instant. It does not infer passive
blocking merely from current direction or normalize a waveform's sign after
observing it.

## Bounded Control Diagnosis

The original model reaches 625-629 kV early, then falls under the unchanged
900 MW transfer target. The saved native controller outputs show T1 current
reference near its 1 pu limit. Source and generated code also show a separate
hard-coded antiwindup comparator threshold 0.99999; increasing only Imax would
leave the PI frozen. The old output named Reset is a different constant signal
and is not evidence that the actual FrzI signal is inactive.

The third attempt changes only T1 Imax from 1 to 1.05 pu and replaces the
antiwindup constant with an input-connected gain of 0.99999 times the actual
Imax. Both PI saturation and freeze remain enabled. T2 stays at 1 pu. The
unchanged 1000 MVA/370 kV bases give phase current base 1.560406 kA RMS and
2.206748 kA peak; 1.05 pu gives 1.638426 kA RMS and 2.317086 kA peak. At
900 MW/640 kV, the DC arm-current contribution is 0.46875 kA; the AC half-current
peak is 1.158543 kA, before adding observed circulating current. This is a
bounded controller-headroom experiment, not a relaxed physical current limit.
All twelve measured arm peaks remain subject to the existing 3 kA protection.
Actual FrzI and limited Imag are newly instrumented per terminal. Generated
Fortran must confirm that freeze tracks Imax before the run starts.

The native finite-duration fault now binds the real timer DF and selects the
terminal-2 P-N fault branch. Its clearing mode removes the externally imposed
fault at the programmed EMT time. This is explicitly different from a model
of a current-zero-only breaker; its OPENBR output still proves actual removal.
Fault window remains 2.5-2.7 s; pre-fault 2.0-2.4 s and recovery 4.6-5.0 s each
cover 24 complete cycles at the template's declared 60 Hz frequency.

The third attempt (`fault-evidence-20260908T042042762152Z`) completed both EMT
runs from c687a4a. INFX validation initially stopped on nested and named
compiler instance paths. Those reader-only defects were reproduced with
fixtures and corrected, then the completed immutable outputs were re-read in
`reanalysis-20260908T043843906835Z`. Sixty channels, including actual FrzI and
Imag, were recovered. T1 still spent 99.94% of the final window in freeze,
with Imag averaging 1.04994 pu. Final-window voltages remained about
475.97/458.53 kV. T2 power reached -898.56 MW but had 10.13% relative RMS ripple.
Full-run no-fault arm peaks were 2.79109/2.80114 kA, both below the unchanged
3 kA protection. The nominal and recovery criteria therefore remained FAIL.

The next single-variable diagnostic raises only T1 Imax from 1.05 to 1.1 pu,
with the same relative antiwindup threshold. The phase-peak increase is
0.11034 kA and its arm AC contribution increases by 0.05517 kA. T2, carrier
ratios, timestep, 640 kV/900 MW targets and physical limits remain fixed.
T1 measured input power is explicitly distinguished from T2's controlled
-900 MW setpoint: its target is supplying T2 plus nonnegative measured losses,
bounded by a predeclared 10% of delivered power. It is not a second 900 MW
control target. Both pre-fault and recovered DC voltage and T2 power must
independently meet the 5% nominal band as well as the pre/post recovery band.

The fourth attempt (`fault-evidence-20260908T045334292345Z`, 60c124f) completed
all readback and output identity checks. It retained a physical FAIL: no-fault
terminal voltages averaged 519.75/501.03 kV, T1 FrzI remained active for 93.69%
of the final window, while T2's power reference and stability checks passed.
No-fault full-run arm peaks were 2.88057/2.75489 kA. T1 Imax is not increased
further. The next convergence experiment changes only EMT timestep 50 to
25 us, retaining 250 us output sampling and all physical/control criteria.

The fifth attempt (`fault-evidence-20260908T050725531192Z`, 770fad7) used 25 us.
Both runs completed with valid identities and clean owned-process exit.
Steady-state voltages remained 520.40/504.23 kV, while T2 power was stable at
-900.024 MW. This does not support coarse timestep as the main undervoltage
cause. Full-run arm peaks were 2.74209/2.26094 kA. A diagnostic FFT of the frozen
4-5 s raw waveforms showed dominant DC-voltage content near 303 Hz, also visible
in T1's limited current reference.

The next single-variable experiment inserts a 5 ms first-order real-pole
filter only in VSCControl2's DC outer-loop error feedback branch. Owner
177754199 changes from Edc_Pu to the filtered signal; the other two Edc_Pu
labels, raw physical voltage outputs, PWM normalization and fast protection
remain unchanged. The Master realpole uses unit gain, no output limiting,
and TIMEZERO reset to the actual raw Edc_Pu input, so snapshot or nonzero initial
voltage is not replaced by an artificial zero. Its 31.8 Hz corner attenuates
303 Hz by about 19.6 dB. The original 4.6-6.5 Hz DC-loop estimate assumed a
series PI; the source-backed parallel-PI correction is recorded below. This is a controller feedback
change; acceptance uses only raw physical DC voltage. Only the five-second
no-fault case runs until the unchanged nominal/stability gate closes.

The sixth attempt (`fault-evidence-20260908T055316670642Z`, d7b5757) completed
the steady-only run with all input/output/support identities and owned cleanup
verified. All capacitor-sum, arm-current, and power checks passed, but the two
raw DC-voltage checks failed. T1/T2 means were 613.70/600.00 kV with raw relative
RMS ripple 25.50%/27.54%. Their 302.5 Hz components were about 202.5/215.8 kV
in amplitude and nearly in phase. FrzI duty reduced to 61.59% at T1; all-run arm
peaks were 2.43201/1.94203 kA. The filtered signal was not used as acceptance
voltage. This is progress in control behavior, not a physical PASS.

The next diagnostic changes only T2's carrier ratio 3 to 23 at the unchanged
60 Hz fundamental, matching T1's installed setting. The source uses 76
phase-shifted carriers; 1380 Hz is the individual carrier frequency and is not
claimed as the effective arm switching frequency. Added min/max outputs measure
actual single-submodule voltages in each arm, to distinguish capacitor imbalance
from a stable capacitor sum. All original physical bands remain fixed.

The seventh attempt (`fault-evidence-20260908T063325715595Z`, 9451bfa) found
almost no change after T2's carrier ratio changed: raw DC voltages averaged
613.589/600.019 kV versus 613.703/599.997 kV in the preceding case. It retained
physical FAIL with all identities, support copies and cleanup verified. New
single-cell extrema in the final window were 7.160-11.460 kV at T1 and
7.606-8.617 kV at T2. These diagnostics do not certify individual cell balance.

The original line comprises two 200 km segments in series, hence 400 km total.
Independent source-backed modal approximation placed its lowest parallel
mode near 310 Hz, close to the observed 303 Hz; this is supporting evidence,
not a proof of the closed-loop cause. The line geometry/constants remain fixed.

The next experiment uses the seventh run as its fixed baseline and adds only
power-mode DC-port damping: `Idref1 - 1.5*(Edc_Pu-MmcFilteredVdcPu)` feeds InA
of the existing mode selector before the total Imag/Imax limiter. At T2, negative
d-axis reference exports power to the AC system, so a positive raw-minus-filtered
voltage increment makes the current request more negative and increases DC
power absorption. The local high-pass has zero DC gain and retains the prior
TIMEZERO initialization. T1 remains in DC-voltage mode, so its selected branch
is unchanged. All current limiting and FrzI paths see the combined request.

The 1.5 pu gain corresponds to approximately 0.00366 S static incremental
conductance at 1000 MVA/640 kV, compared with the 900 MW constant-power magnitude
of 0.00220 S. This estimate does not include current-loop delay, transformer
leakage or saturation and is not claimed as a stability proof. Actual damping,
selected d-axis reference before/after limiting, actual dq current and physical
station DC current are saved for phase/amplitude diagnosis. The average power
target, raw-voltage acceptance and all physical limits remain unchanged.

The eighth attempt (`fault-evidence-20260908T070331092930Z`, 09ecea7) failed
physically despite valid complete identities and cleanup. T2 active power fell
to -777.71 MW; its pre-limit d-axis request ranged -1.678 to -0.274 pu, while the
actual total limiter clipped it at -1 pu. The 302.5 Hz oscillation increased.
Coherent actual-id/limited-reference ratios had phases about +104.5 degrees at
T2 and -144.2 degrees at T1. These jointly disturbed response ratios are not
identified transfer functions, but rule out reliance on the static gain alone.
This failed current-reference damping branch is not increased or retained in
the next voltage-path experiment.

The next candidate returns to the seventh fixed baseline and adds only common
arm-voltage virtual resistance. In measured convention, ic=(IaTop+IaBtm)/2;
the three phase means sum to -Idc_station. The eighth run independently gave
-1.31801 versus -1.31792 kA at T1 and +1.30808 versus +1.30815 kA at T2, with
about 0.0635 kA instantaneous residual RMS. The sign/coefficient are verified;
instantaneous perfect KCL is not inferred from those differently sequenced
measurements.

The source equations are VrefT=DBlk_ramp-Vref-Vz and
VrefB=DBlk_ramp+Vref-Vz. Setting
Vz_effective=Vz-(2*30/640)*HP_5ms(ic) raises both requested inserted arm voltages
in the direction opposing the measured circulating current. Each incremental
requested arm voltage is 30*HP(ic)*(actual sum(Vc)/640) kV; at nominal summed
capacitor voltage this corresponds to 30 ohm per arm or 20 ohm at the DC port.
The commanded AC differential term is unchanged, the high-pass DC gain is
zero, and this is not a claim of physical resistor losses. The filter resets to
the actual raw circulating-current signal at TIMEZERO.

Raw/effective Vz, raw/high-pass ic, signed arm-voltage requests, actual inserted
voltage, capacitor extrema and original protection measurements are retained.
The existing comparator still limits the number of selected cells to the
physical count. Additionally, any steady request with absolute modulation
above 2 pu fails the diagnostic gate; implicit clipping cannot manufacture a
passing working point. All original nominal, recovery and current bounds remain.

The ninth physical attempt (`fault-evidence-20260908T075010061627Z`, f441438)
reduced the 303 Hz voltage component to roughly 6.25/7.90 kV at T1/T2, but
retained physical FAIL. Raw DC means were 547.38/533.43 kV with 4.94%/5.33%
relative RMS ripple. T2 power remained -900.06 MW, while arm requests reached
2.3-2.56 pu and T1's current request stayed at 1.1 pu with FrzI continuously
active. This is an unaccepted diagnostic, not grounds to raise damping or
accept modulation clipping. The official transformer has no active tap and
its compiled ratio is 230/370 kV; measured current-ratio evidence confirms
that ratio. Apparent power inferred only from P/Q omits waveform distortion.

Revision f108bac adds exact-node measurements of the physical AC command
magnitude before DC normalization (VSCControl2 multiplier 736319288, output
3204/2034) and the normalized magnitude before the 1.5 clamp (divider
235800143, output 3204/1944). It also observes local converter-side Edc,
each phase's Vref/Vz and deblocking ramp. These distinguish the existing
line-side voltage base from local DC and actual arm capacitor sums.

Per-arm energy is measured from the full 76-cell vector. The installed cell
form declares C in uF, and compiled Main forwards 2800.0 without SI conversion.
The diagnostic therefore uses `0.5e-6*C*SUM(Vc**2)` in MJ when Vc is kV.
`FULLCELL1_EXE` return RVD1_5 is also exposed as the vendor aggregate equivalent
source voltage; it is not asserted to be the selected-cell voltage sum.
The energy formula and the original cell unit declaration are checked before
instrumentation, and their generated-code form is retained with the run.

Revision c5ed2e2 repairs an independently verified source binding: Main T2
charging-delay owner 606940312 previously used Tcharging1 even though the
terminal has its own Tcharging2 signal (label owner 2129272491). The derived
copy now uses Tcharging2; T1 delay owner 584272924 retains Tcharging1. A
regression proves that this is the only source-XML change, and the runner
requires one generated EMTDC_XTTRANS call for each terminal setting. Original
settings are 0.02 s for T1 and 0.0 s for T2, so the correction also removes
the unintended 20 ms delay at T2.

The c5ed2e2 diagnostic (`fault-evidence-20260908T085929376555Z`) showed T1
has excess total capacitor energy (51.934 MJ against 45.272 MJ nominal) but
severe unequal cell voltages (mean within-arm standard deviation 4.793 kV).
T2 has 31.791 MJ and remains nearly balanced (0.0156 kV within-arm standard
deviation). The stored source, support and output hashes remained unchanged;
owned cleanup completed. The result remains physical FAIL.

Read-only linked-routine investigation, independently reviewed in
`independent-review-20260908.md`, found that positive sorter NS only orders
the requested low-voltage prefix. The firing controller selects the opposite
high-voltage suffix when signed insertion times arm current is negative.
For k >= Dim/2 the suffix set is nevertheless correct by complement; an
unordered suffix alone therefore does not establish wrong selection.

The b653102 run (`fault-evidence-20260908T091449749308Z`) added same-control-step
index bounds/inversions, actual NS/Enab and capacitor-current moments. Its
inversions established incomplete ordering but did not establish wrong sets.
The e70bed7 run (`fault-evidence-20260908T092347227867Z`) added direct selected
set boundary gaps and an explicit applicability flag. On Enab-active samples
in [4.6, 5.0), the actually consumed suffix with 0 < k < 38 was wrong in all
2117 T1 samples and all 627 T2 samples, with maximum gaps 11.8215/0.3956 kV.
All refreshed consumed-prefix cases and suffix cases with k >= 38 were correct.
Both runs retained physical FAIL and completed owned cleanup with unchanged
sources/support. Their finalized outputs and diagnostics remain separate.

The resulting candidate changes only E_SORTER's sort extent to Dim in a
runtime-cloned sorter Definition. Component NS remains the actual requested
cell count and is distinguished from the algorithm sort extent in diagnostics.
The existing Enab includes count changes, signed-count edges and deblocking;
it is retained, as are the original current and firing inputs. Full sorting
provides both extreme subsets at refresh events, but does not promise new
sorting during held steps. Raw electrical gates and the 2 pu arm modulation
limit remain fixed, and the next run records actual EMT elapsed time.

Capacitor balance drive is now measured directly after FULLCELL1_EXE as
`SUM(Vc*Ic)-SUM(Vc)*SUM(Ic)/DimC`, keeping all terms in one control step.
Earlier externally reconstructed drive used the output-stage capacitor sum
and is directional diagnostic evidence only, with possible stage/sampling
error. Vc is kV and Ic is kA; startup energy/current integration crosschecks
support MW/kA scaling. Later distorted T1 data sampled at 250 us is not an
exact energy-derivative measurement.

Reproduce the sorting boundary diagnostic from this worktree with process-local
imports, passing a finalized run directory (never a live output directory):

```powershell
$env:PYTHONPATH = (Get-Location).Path
& 'D:/pscad-mcp/.venv/Scripts/python.exe' -m docs.acceptance.mmc-fault-evidence.diagnose_sorter 'D:/PSCAD-Workspace/mmc-fault-evidence/fault-evidence-20260908T092347227867Z'
```

The command validates original contract/sample/output-index hashes and the
complete output dataset before reporting refreshed/held subset coverage. It
does not generate a physical acceptance verdict.

## September 12 Readiness Resume

The fixed 78204a0 late-window steady attempt
`fault-evidence-20260908T094200138111Z` passed its then-implemented checks,
with verified owned cleanup and unchanged source/support hashes. T1/T2 DC
means were 638.989/626.654 kV, ripple 0.245%/0.252%, and maximum arm request
1.88721 pu. T1 within-arm cell standard deviation fell to 0.01738 kV.
The complete steady/fault attempt `fault-evidence-20260908T095525138020Z`
remained FAIL: four T2 arm-capacitor means in [2.0, 2.4] were
607.745-607.941 kV, below the unchanged 608 kV nominal lower bound. Their
four recovery rows inherited the invalid prefault operating point. Actual
fault application, negative insertion, blocking and the fault-current bound
passed. Owned cleanup and source/support immutability were verified.

The steady and fault cases have identical trajectories before the fault.
The previous `_steady` helper checked only [4.6, 5.0], so its PASS did not
prove readiness in the already-required [2.0, 2.4] window. The resumed gate
now checks both existing windows, reports each separately, and preserves
all thresholds and the original frozen checks object. A regression reproduces
the misleading late-window PASS using a 607.8 kV prefault capacitor sum.
Focused validation: 93 fault-channel tests passed; lint passed. The root's
independent full offline suite at fixed 78204a0 had 2525 passed and 49 skipped;
that result does not replace the still-pending physical readiness closure.

The generated `PIwithFreeze` implements parallel PI:
`u=Kp*e+integral(e/Ti)`. T1 uses KpDCRec=12 and TiDCRec=0.08, giving
Ki=12.5 per second. The reference is nominal 640 kV with a 10 ms reference
filter, zero DC droop and no FrzI activation in the readiness window.
Using the two terminals' nominal capacitor energy 90.543 MJ gives the
common-energy approximation `dv_pu/dt=5.522*di_pu` and a slow closed-loop
pole of -1.0585 per second when the existing 5 ms feedback filter is included.
The observed T1 DC error in 2.0-5.0 s has a 0.9396 s exponential decay time,
consistent with that scale. This is a reduced-model explanation of the tail,
not a closed-loop stability proof for every MMC/line mode.

In [2.0, 2.4], T1/T2 capacitor-energy slopes are 2.206/2.134 MW while the
AC power balance is 51.703 MW. Subtracting those slopes leaves 47.363 MW,
including losses and other stored-energy changes; the late-window residual
is 47.458 MW. T1's readiness-window current-reference peak is 0.96354 pu,
with its existing 1.1 pu limit retained. The next candidate changes only
the actual T1 DC integral parameter from 0.08 to 0.04: Ki becomes 25 and
the estimated slow pole -2.1525 per second, while Kp and the fast reduced-model
pole pair remain essentially unchanged. A several-MW increase in tail
recharging is small relative to the observed current-reference margin;
the licensed double-window steady gate must still verify actual limits.
