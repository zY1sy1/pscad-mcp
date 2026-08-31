# CIGRE LCC companion library provenance

This repository-authored companion library encodes the fixed single-pole,
12-pulse benchmark described by M. Szechtman, T. Wess, and C. V. Thio,
"A benchmark model for HVDC system studies," *Electra*, no. 135,
April 1991, pp. 54-73.

## Parameter ledger

- The two six-pulse groups, Y-Y/Y-delta transformer interfaces, and twelve
  valve instances follow the benchmark topology in Figure 2 and the bridge
  description on pages 58-61.
- The DC series path and terminal polarity follow Figure 3 and the line
  equations on pages 61-63.
- Rectifier constant-current and inverter constant-extinction-angle control
  roles follow the control diagrams in Figures 5 and 6.
- Initial conditions and the declared signal interface are documented in
  Table 4 and the initialization discussion on pages 68-70.

The PSLX is generated deterministically by
`scripts/build_lcc_companion_library.py` from repository-authored component,
port, parameter, and wire ledgers. It contains references only to live-audited
`master:` definitions; no vendor form, SVG, schematic, script, or Definition
body is redistributed. Local Breaker projects were not sources for this asset,
and no user project XML, parameter set, or schematic was copied.

Each 12-pulse bridge contains two `master:g6p200` instances with `FP=0`,
`View=1`, separate Y/delta AC groups, a common DC series path, and scalar
radian `AO` inputs. The effective twelve-valve count derives from two audited
six-pulse Master bridges; the companion does not fabricate individual valve
records. `RectifierControl` uses current-error PI and hard limiting;
`InverterControl` uses minimum gamma feedback, PI, and hard limiting. Page
interfaces use audited `pin`, `breakout`, `import`, and `export` primitives.
The no-fault smoke channels use ten audited `master:pgb` output blocks inside
the companion definitions. Initialization enable states pass through audited
integer-to-real `unity` adapters before reaching their output blocks; the
external integer enable contract is unchanged.

Offline structure evidence does not imply physical PASS. Load, instance
read-back, save/reload, component compile, full-topology compile, and no-fault
simulation in licensed PSCAD 4.6.2 remain separate required gates.

## Master binding ledger

`master-bindings-pscad-4.6.2.json` is the authoritative physical binding for
the eight logical Master entries in this asset set. It was audited against the
installed PSCAD 4.6.2 `master.pslx`; no vendor definition body is copied into
the registry or companion library.

- `three_phase_source -> source3`, with three-phase `View=0`.
- `converter_transformer -> xfmr-3p2w`, matching the component used by the
  official CIGRE LCC examples inspected on 2026-08-29.
- `ac_filter_branch -> cfilter`, expanded into three instances with explicit
  neutral grounds, per-phase MVA, and harmonic-order conversion.
- `smoothing_reactor -> inductor`, converting mH to H.
- `dc_line_section -> resistor`, using the catalog's total resistance. The
  rejected `dc_mac_2w` candidate is a DC machine, not a transmission line.
- `ac_meter` and `dc_meter -> multimeter`, with explicit modes that retain the
  required electrical pair.
- `ground -> ground`.

The schema-v2 companion section separately binds every Master primitive used
inside the repository-authored PSLX, including `pgb -> output_channel`. These
bindings contain metadata and parameter contracts only; no vendor Definition
body is redistributed.

The official examples informed component identity and semantics only. They are
not redistributed by this asset package. Licensed Master-binding compile
reports are generated under the configured acceptance workspace and remain
separate from the packaged provenance and from full-model waveform acceptance.
