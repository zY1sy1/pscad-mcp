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

The XML is an original repository-authored structural companion contract. It
contains references only to characterized `master:` definitions; no vendor
definition body is redistributed. Local Breaker projects were not sources for
this asset, and no user project XML, parameter set, or schematic was copied.

Compilation in a licensed PSCAD 4.6.2 installation remains a required release
gate and is recorded separately from this provenance ledger.
