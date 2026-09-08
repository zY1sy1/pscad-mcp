# MMC Master Mapping Offline Pre-Audit

Date: 2026-09-08. Scope: WP2 preparation while LCC WP1C continues separately.

This is a historical snapshot at `d226c2d`. Later native MMC work is recorded
in [the scoped licensed result](../../acceptance/mmc-native-probes-20260908.md).
The saved `--verify` command deliberately detects drift after repository code
or revision changes; use `--output` with a new filename for a new audit instead
of overwriting the original evidence.

The offline pre-audit is complete. The packaged fixed/parametric AVM path has
five distinct Master references: four have no exact installed definition, and
the remaining `master:source3` has incompatible requested ports and parameter
names. The official blank/native and detailed-PWM template pair has 73 distinct
Master references reachable from `Main`; every one has exactly one installed
definition. These are static inventory results, not verified bindings or a
compile/simulation result.

## Evidence And Scope

- Worktree: `D:/pscad-mcp/.worktrees/mmc-master-offline-audit`.
- Branch: `codex/mmc-master-offline-audit`.
- Audited baseline: `d226c2d2259c73d867c147259d14abe8d23e3228`.
- PSCAD library XML version: `4.6.2`; 345 unique Master definitions.
- [Complete reference inventory](evidence.md): packaged logical references,
  all 77 template/library Master references, and native wire objects.
- [Machine-readable evidence](evidence.json): 47 source hashes, component
  consumers, JSON pointers/XPaths, owner IDs, parameter values, conditional port
  occurrences, dimensions, and parameter types, units, ranges, choices and defaults.
- [Reproducible collector](collect_evidence.py): repository metadata parser and
  registry normalization helpers, XML parsing and Python AST inspection.

The collector visits all 12 project definitions and 47 sibling-library
definitions, and follows non-Master references from `H_MMC_Mono_DC:Main`.
Sixteen project/library definitions are reachable. Their 1,156 Master component
occurrences use 73 distinct names; the full files contain 1,270 occurrences and
77 names. These counts describe definition contents, not expanded runtime
instance counts. Conditional activity and parent parameter expressions are
not evaluated. Unused library prototypes are retained separately.

Blank recipe roles, packaged catalog/blueprint, parametric AVM overrides,
scenario control code, native/PWM sources and companion internals are covered.
Future WP3 control insertion and arbitrary user templates require a new audit.
No PSCAD or compiler was started, and no runtime, model, registry or acceptance
status was changed.

| Read-only source | SHA-256 before and after |
| --- | --- |
| Installed `master.pslx` | `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939` |
| Official `H_MMC_Mono_DC.pscx` | `1900be93877400fba228b1808a5310980d801b0260d7df998df6c5a2f6a035dd` |
| Official `intermediate.pslx` | `08466778704e547d7d9d80af99a48c09292dd3a51056ac26216c3913d5cc3a1b` |

## Logical Mapping Decisions

All five logical references lack a packaged Master catalog entry. Port names
are declared in the blueprint, but kind/dimension contracts for these entries
must still be defined. The dimensions below describe physical candidates or
required semantics, not an existing validated MMC catalog.

| Logical reference | Current demand | Installed evidence | Recommendation and remaining decision |
| --- | --- | --- | --- |
| `master:dc_bus` | Four nodes; one `DC` port each; no parameters | No exact definition. `nodelabel:A` is an unconditional Natural port, raw dimension 0, normalized by the existing registry to electrical dimension 1. | Prioritize `DC -> A` on `nodelabel`; define stable per-node `Name` values and explicit measurement settings. Verify connectivity and naming in a later isolated compile. |
| `master:source3` | Two sources; `AC`; `Amplitude`; AVM adds `Frequency`, `GridR`, `GridX` | Exact definition exists once. No `AC` port or any of those four parameter names. `N3` has dimension 3 under `View==1`; scalar `A/B/C` exist under `View==0`. | Decide a dimension-3 AC contract or explicit phase expansion. `Amplitude -> Vm` and `Frequency -> F` are candidates. Impedance conversion requires a selected source model and `Type`/`Imp` settings. |
| `master:transformer` | Two units; `AC`, `VALVE`; AVM adds `rated_power_mva`, `rated_dc_voltage_kv` | No exact definition. Official reachable converter uses `xfmr-3p2w`; its `N1/N2` are dimension 3 when `View!=0`. | Prefer reviewing `xfmr-3p2w` first; `Tmva` is MVA, `V1/V2` are AC line-line RMS kV. Define winding voltages, connections and neutral treatment. DC rating alone does not specify `V2`. |
| `master:dc_cable` | Two conductors; `IN/OUT`; `length_km`; AVM adds half of total `line_resistance_ohm` | No exact definition. Official project uses native `TLine` objects with `DCTL` configuration. `cable_interface` and `tline_interface` are each one end of a paired interface. | Define a paired-interface/native-line adapter or an explicitly limited lumped model. A two-port rename cannot represent the required line configuration and constants. |
| `master:pi_controller` | Two internal control-block references in the companion contract; no internal ports or parameters declared | No exact definition. `pi_ctlr` exists once, with scalar `IN` occurrence 0 and dimension-2 `IN` occurrence 1 under different conditions. | Define the physical control and choose `Mthd`/`INTR`, `GP`, `TI`, output limits and initialization. A scalar profile can select `Mthd=0`, `INTR=0`, `IN` occurrence 0, subject to the intended controller equations. |

### DC Bus Candidate Evidence

The existing blueprint uses each `dc_bus` as a named junction on a conductor,
not as a two-terminal series element. The official project's `Main` contains
four `master:nodelabel` instances:

| Node name | Owner ID | Voltage signal | Settings |
| --- | --- | --- | --- |
| `T1P` | `237093484` | `EdcPG1` | `MeasV=1`, `PU=0` |
| `T1N` | `122006338` | `EdcNG1` | `MeasV=1`, `PU=0` |
| `T2P` | `1972091014` | `EdcPG2` | `MeasV=1`, `PU=0` |
| `T2N` | `1263621230` | `EdcNG2` | `MeasV=1`, `PU=0` |

This gives `nodelabel` direct usage evidence beyond a similar name. A minimal
new node contract can explicitly set `MeasV=0` and use separate measurement
components; alternatively it can deliberately adopt named voltage outputs.
The choice must be fixed before generating an executable binding. Avoid
reusing the default `NodeName` across distinct nodes; the exact naming scope
and electrical behavior still require a connectivity/compiled-netlist check.

Other candidates are not interchangeable:

- `short` is a **3 phase short**, with dimension-3 `N3` and dimension-1 `N1`.
  It is not a scalar two-terminal DC conductor.
- `nodeloop` is a three-phase node with conditional scalar or bundled ports
  and transfer outputs; it does not match the single DC-junction contract.
- `xnode` is an external electrical node, with a `Name` parameter and boundary
  semantics that need a module-port contract. It is not the default candidate
  for a local junction.
- `Wire classid="Bus"` is a native canvas object, not `master:dc_bus` or a
  Master definition. The official project has two such objects, `T1` and `T2`.
  Choosing this representation would require the wire lifecycle, not ordinary
  component placement.

### Parameter And Line Constraints

`source3.Vm` is line-line RMS kV with minimum 0.001; `F` is Hz with minimum
0.001. `R1s`/`R1p` are ohms, `L1p` is henries, and `Z1`/`Phi1` provide a
conditional impedance representation. `GridX` cannot be copied into an
inductance or angle parameter. The official template actually uses
`source_3`, a distinct source model; its settings cannot be silently applied
to `source3`.

The official transformer prototype is owner `247869978` in `VSCConverter`,
with `View=1`, `YD1=0`, `YD2=1`, `Tmva=Sbase`, `V1=Vtr_1`, `V2=Vtr_2`, and
`f=freq`. Those expressions and neutral connections need instance-specific
resolution; their presence does not establish a numeric transform for AVM.

The official native lines are `TL12a` (owner `2005307872`) and `TL12b`
(owner `1533195475`), each with `Length=200 [km]`, `Dim=2`, `Freq=0 [Hz]`,
and reference `H_MMC_Mono_DC:DCTL`. The configuration consumes
`Line_FrePhase_Options`, `Line_Ground`, and `Line_Tower_2_Flat`.
`mmc/line_constants.py:96` already extracts these objects read-only; its
compiler/execution path was not called. These are overhead-line configuration
records, not evidence for an underground-cable model.

Reject `dc_mac_2w` as a DC line candidate: its installed description is
**Two winding DC Machine**, and parameter `D` means mechanical damping in pu.
The `F1/F2` terminals and parameter name do not provide line semantics.

## Additional Blockers Exposed By The Inventory

1. **Missing catalog contracts block planning.**
   `mmc/planner.py:307` calls `require_definition` against the packaged
   catalog, which contains six companion entries and zero Master entries.
   AVM `_inventory_catalog` requests live Master metadata but does not fill
   `asset_set.catalog`. The next WP2 implementation needs both the audited
   registry and the logical planner contracts, including text node names.
   `mmc/catalog.py:164` currently validates declared parameters as numeric,
   so a text-name contract also needs an explicit policy.
2. **The packaged companion is descriptive XML.**
   Its root is `pslx`, with six lowercase `definition` records and zero native
   PSCAD `Definition` records. The two `pi_controller` references are
   `control_block` declarations. Mapping those names does not turn the
   described equations into a compilable physical library.
3. **The two DC lines have both terminals on one net.**
   Blueprint lines 72 and 73 each include the corresponding line's `IN` and
   `OUT` in a single electrical net. The planner routes all net endpoints and
   `executor.py:395` creates a continuous wire. With real distinct line
   terminals this would bypass the line. This is a static topology defect,
   not an observed simulation result.
4. **The arm connections are not represented by the existing nets.**
   None of the 12 `MMCAverageArm` component IDs appears in any net endpoint;
   neither transformer `VALVE` port is connected there. The six phase midpoint
   operations and two DC-terminal operations do not supply endpoint mappings;
   `executor.py:374` can record them as declarative markers when no backend
   primitive exists. Physical connection evidence must be established before
   claiming a connected autonomous MMC.

These findings are recorded for WP2/WP5 follow-up. This pre-audit does not
change the active LCC work, shared Legacy backend, asset hashes or program
acceptance status.

## Next Implementation Boundary

Use this inventory to define the node, three-phase AC, transformer and line
contracts, then implement the MMC registry through the shared
`pscad_mcp/core/master_bindings.py` APIs. Preserve exact port occurrences,
fixed selectors, parameter conversion checks, source hashes and read-back.
Plan physical companion and connectivity work explicitly alongside mapping.

Any code implementation and integration must first recheck the current
baseline and WP1-to-WP2 dependency gates in the roadmap, especially parametric
LCC readiness and stability of shared backend changes. Licensed component
smokes and end-to-end simulation follow after an exclusive PSCAD run window
is available. This audit does not unlock those gates.

## Verification

Relevant existing offline checks: **83 passed, 1 skipped**. The skipped case
is retained as unexecuted evidence. No licensed tests were run.

The collector's `--verify` mode recollects every source, compares the full
JSON and Markdown inventory, and writes nothing. Run from the worktree:

```powershell
& 'D:\pscad-mcp\.venv\Scripts\python.exe' docs/audits/2026-09-08-mmc-master-offline/collect_evidence.py --verify
```

All 47 recorded sources retained their before/after hashes during collection.
Independent XML count, source-hash and artifact checks are recorded in
`verification.txt` alongside the report.
