# MMC Native Signal Audit and Acceptance Preparation

This is offline preparation at `a759a468933109af2169bcc2d67ad4e977a3deb2`.
No PSCAD instance, compiler or licensed simulation was started. It does not change
the historical `INCOMPLETE_ANALYSIS` verdict or establish current acceptance.

## Artifacts

- `signal-manifest.json`: every one of 177 scalar channels, full INFX owner and
  instance identity, dimension, exported units, signal-source expression, source
  component, source part, INF/INFX records, sample statistics and SHA-256 evidence.
- `required-channel-table.md`: the nine WP4 roles and every relevant existing
  channel, including rejected aliases and missing instrumentation.
- `acceptance-matrix.json`: actual test requests, analytic constraints, planner
  results, six engine plans and 66 scenario recommendations with unchanged
  thresholds, required metrics, events, units and WP4/WP6 release requirements.
- `collect_signal_audit.py` and `collect_acceptance_matrix.py`: reproducible
  read-only collection; writes are confined to this audit directory.
- `verification.txt`: successful collector runs, matching repeat hashes and
  static-check results.

## Historical Signal Findings

The finalized 2026-08-29 native run has 18 numbered OUT parts, 177 scalar channels
and 5201 samples over 0..1.3 s at 4000 Hz. OUT time columns agree. All 177 scalar
channels resolve to an INFX full owner ID and a compiled PGB source assignment.
Every sampled file and code input is hashed before and after collection.

| Required role | Historical evidence | Missing or ambiguous scope |
| --- | --- | --- |
| fault_active | No direct output | Fault mode calls 71/143 export FltPulse, a 1 ms protection pulse, not the actual fault-switch command |
| v_inserted | Absent | Add physical Ntop-minus-Nbtm measurements; capacitor sums and voltage orders are not substitutes |
| blocking_state | Calls 29/30 are Dblk2P/Dblk1P | Active-low blocking request; actual gate input additionally ORs Fltm, internal Block_Finder_H flag is unexported, units empty |
| i_dc_fault | Call 33, selected physical branch current | Flt_Select=5 selects IFlt_Mid; native definition says kA, exported units empty |
| v_dc | Edc1/Edc2 and pole-to-ground outputs | Station/pole identity required; exported units empty |
| i_arm | All twelve top/bottom phase currents | Physical varrlc branch currents in kA by definition; exported units empty |
| v_cap | Twelve sums of 76 capacitor voltages | Individual 76-element Vc arrays are not exported; sums have empty units |
| recovery_enable | Dblk1P and Discon1 transitions | Enable-state evidence only; voltage/power/current recovery still requires contract checks |
| time | All 18 OUT time columns; INFX Time/s | Complete historical time domain only |

The two converter instances differ materially:

- T1 De-blocking changes to 1 at 0.300 s, to 0 at 0.311 s, then to 1 at
  0.561 s. Discon1 is 1 over 0.311..0.561 s. Fault mode_1 is 1 only over
  0.311..0.312 s.
- T2 De-blocking changes to 1 at 0.500 s. Fault mode and Discon2 stay zero.
- Selected fault-current absolute peak is 4.806393083855 at 0.3115 s. Its kA
  interpretation has model-definition evidence; the historical INF unit is
  still blank. This audit does not rerun or promote the current-bound verdict.

The module names containing `Hb` do not prove half-bridge topology. This
historical project reaches `FullCellR_n` with four gate arrays and
`FiringHBridge`. It is a full-bridge native template run, with no demonstrated
intrinsic-blocking acceptance. It is distinct from the installed parametric
template and its different project/library hashes.

## Concrete Probe Sites

All coordinates below are local schematic coordinates in the historical
`BLANK_MMC_scenario_source.pscx`, not in the installed parametric template.
Immutable source hashes and exact XPath/Fortran-line evidence are in the manifest.

| Site | Source component | Probe coordinates and interpretation |
| --- | --- | --- |
| Upper inserted terminal voltage | MMC_Hb_Pole_PWM / FullCellR_n 2087957400, orient 0 | Ntop (846,342), Nbtm (846,432) |
| Lower inserted terminal voltage | MMC_Hb_Pole_PWM / FullCellR_n 1092787740, orient 0 | Ntop (846,630), Nbtm (846,720) |
| Upper/lower raw capacitor array | FullCellR_n Vc:DimC, Real Output | (900,378) / (900,666); 76 elements in this compiled run |
| Upper gate blocking input | FiringHBridge 1522304910 / Block | (2196,1440), scalar Integer Input, active 1 |
| Lower gate blocking input | FiringHBridge 1370947611 / Block | (2196,1890), scalar Integer Input, active 1 |
| Actual fault timer | Main / tfaultn 1067520513 | Y (1206,594); FltActive label 1174284206 at (1224,594); DF is 0.01 s |
| Selected physical fault command | Main / datatap 1506967676, index 5 | DC_flt_Mid label 308537607 at (1476,414) |
| Selected fault branch | Main / fault_sw 349503808 | Name=DC_flt_Mid, Iflt=IFlt_Mid; A (1530,900), B (1494,900) |

`master:voltmeter` measures N1 minus N2. Connect N1 to Ntop and N2 to Nbtm,
and preserve that declared sign for both arms. Six station/phase instances
require twelve measurements. Do not flip polarity after inspecting results to
obtain a negative-voltage PASS. The internal FullCellR_n a-minus-b Vbr and
EBRD=-Vth are different quantities from external terminal insertion voltage.

The gate input is `NOT DBlk OR Fltm`. It is a gate command; the internal
Block_Finder_H output is the stronger switching-state determination and is not
currently sampled. FullCellR_n's Vc port has no unit attribute; the SumVc0
parameter declares kV. Any new array probe needs reviewed unit provenance.

### Separate Source Profiles

Do not reuse the historical coordinates above in the installed template. The
collector audits both paired PSCX/PSLX profiles and checks every proposed
cell-terminal, capacitor-output and blocking-input site against wire endpoints.

| Contract | Historical native profile | Installed ModelsInProgress profile |
| --- | --- | --- |
| Project SHA-256 | 9cabfdc706ce74fdbc1faf3490454ce12eb3fb8a316cecc3f8dec9aa7d2bd1f8 | 1900be93877400fba228b1808a5310980d801b0260d7df998df6c5a2f6a035dd |
| Library SHA-256 | f3e94afdc5541984c01b10f4d49a2d7ddcb480f11327f6347f17edd56595a562 | 08466778704e547d7d9d80af99a48c09292dd3a51056ac26216c3913d5cc3a1b |
| Upper/lower FullCellR_n IDs | 2087957400 / 1092787740 | 488611367 / 1215143890 |
| Nbtm local offset | (0,36) | (0,54) |
| Upper/lower Nbtm absolute | (846,432) / (846,720) | (846,450) / (846,738) |
| Upper/lower FiringHBridge IDs | 1522304910 / 1370947611 | 1374623403 / 1247560741 |
| Block local offset | (18,72) | (0,72) |
| Upper/lower Block absolute | (2196,1440) / (2196,1890) | (2178,1440) / (2178,1890) |
| Gate routine / FrChange | HBridge_Ctrl / 1 | HBridge_Ctrl1 / 0 |
| Cell routine | MMC_FullB, BPS_L=0 | FULLCELL1_CFG/FULLCELL1_EXE, DTBP=0 |

Ntop and Vc offsets, scalar Integer Block input, Real dynamic Vc output,
SumVc0 kV and capacitor uF unit declarations agree. Both cell definitions use
Block_Finder_H with 1 documented as blocked, but that does not prove identical
external routines or dynamics. No vendor definition bodies are copied here.

The historical staged library exactly matches the journal's archived library at
`D:/pscad-mcp-official-examples-20260829/mmc-4.6.2/intermediate.pslx`. Its archived
project also matches the journal hash `1b75c245...`. The evidence establishes
different source profiles; it does not establish who changed them or when.

## Matrix Results and Remaining Gates

The existing licensed-test request constructors were imported without invoking
tests. Real offline parser, derivation, planner and recommendation functions gave:

| Case | Rating / link | Offline preparation |
| --- | --- | --- |
| feasible-1 | 640 kV, 1000 MW, 0 MVAr, 60 Hz; 200 km overhead | Analytically feasible; both engine plans created |
| feasible-2 | 500 kV, 750 MW, 100 MVAr, 60 Hz; 100 km cable | Analytically feasible; both engine plans created |
| feasible-3 | 800 kV, 1200 MW, -120 MVAr, 50 Hz; 300 km overhead | Analytically feasible; both engine plans created |

Each engine plan contains four candidates and all eleven standard scenarios.
All six intended infeasible constraints were rejected by both derivation and
planner: modulation_margin, dc_current, line_drop, grid_strength,
control_bandwidth and resource_limit. The 66 recommendation rows retain the
production thresholds and `intrinsic_dc_fault_blocking=false`.

The unmodified installed template correctly hits
`MMC_ABSOLUTE_PATH_UNRESOLVED` for missing `C:/Temp/my_constants_file.tlo`.
Planning succeeds using existing immutable, historically prepared source copies
with verified line-constant bindings. No files were repaired or materialized by
this audit. Those plans are preparation records, not executable publication.

The parameter parser currently rejects `converter=full_bridge`. All three test
requests are half_bridge, while their audited detailed template declares
full_bridge. A planned half-bridge request is not proof of topology conversion.
The separate full-bridge WP6 paths must retain their own implementation and
dynamic evidence; the current half-bridge test matrix cannot satisfy them.

Required next work is new derived-copy instrumentation, exact station and
polarity binding, save/reload, compilation and fresh licensed physical checks.
Missing probes and metadata are implementation/evidence gaps, not evidence of
license contention. This offline task did not test runtime/license availability.

WP6 also needs an independently reviewed reference with fixed project/library
and output hashes, version, compiler, parameters, selectors, units, review ID,
reviewer, date and scope. Builder-generated golden or synthetic arrays cannot
fill that prerequisite. No reviewed reference was found or claimed here.

## Reproduction

Run from the worktree root:

```powershell
python docs/audits/2026-09-08-mmc-native-followup/collect_signal_audit.py
python docs/audits/2026-09-08-mmc-native-followup/collect_acceptance_matrix.py
```

The collectors fail on changed historical trace shape, missing owner/source
bindings, unexpected guard results, or source changes during collection. Source
and collector hashes in the manifests identify the evidence precisely. The
historical run's code commit is unknown because its journal omits that field;
the collection commit must not be attributed to that simulation.
