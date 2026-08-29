# Master Binding Registry Design

**Date:** 2026-08-29

**Status:** Implemented; licensed PSCAD 4.6.2 Master-binding compile gate passed 2026-08-30

## Goal

Make every `master:*` definition used by the fixed LCC catalog instantiate the
real PSCAD 4.6.2 Master Library definition, with explicit port mappings,
parameter mappings, shape/unit transforms, read-back checks, and compile
evidence.

## Scope

The first implementation covers the eight Master definitions currently used by
`pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/catalog-pscad-4.6.2.json`:

| Logical definition | PSCAD 4.6.2 definition | Shape or transform |
| --- | --- | --- |
| `master:three_phase_source` | `source3` | Select electrical `A`, `B`, `C`; ignore auxiliary transfer ports |
| `master:converter_transformer` | `xfmr-3p2w` | Select the six winding terminals; use the component present in the official CIGRE LCC examples and map connection/phase controls explicitly |
| `master:ac_filter_branch` | `cfilter` | Expand one logical three-phase branch into three two-terminal instances; connect `N` explicitly |
| `master:smoothing_reactor` | `inductor` | `IN -> A`, `OUT -> B`, convert `Inductance_mH` to `L` in henries |
| `master:dc_line_section` | `resistor` | `IN -> A`, `OUT -> B`; the fixed blueprint models its declared total line resistance, while length remains explicit engineering evidence |
| `master:ac_meter` | `multimeter` | Use the real `A`/`B` measurement pair and explicit measurement mode |
| `master:dc_meter` | `multimeter` | `IN -> A`, `OUT -> B`; enable instantaneous voltage and current so the series path is retained |
| `master:ground` | `ground` | `GND -> A` |

“Every Master element” means every Master entry in this fixed catalog, not all
definitions shipped by the vendor. MMC companion definitions, PSCAD 5.x, and
arbitrary user-rated generation are separate scopes.

## Non-goals

- Do not replace the logical catalog names with vendor-specific names.
- Do not create synthetic XML definitions and label them as Master Library
  evidence.
- Do not generate wrapper definitions for the normal path.
- Do not infer a missing parameter or port from a component name.
- Do not claim a build is usable when the live Master definition cannot be
  read, is ambiguous, or fails compilation.

## Current Evidence

The installed source is `C:\Program Files (x86)\PSCAD46\master.pslx`, PSCAD
4.6.2. The source inspection shows that the existing catalog already has the
right physical identities for the eight entries, but its representation is not
uniform:

- `cfilter` exposes electrical `A`, `B`, and `N`, while the logical catalog
  describes phase-labelled input/output ports.
- `inductor` uses one physical `L` parameter; the catalog's numeric
  `Inductance_scale` must be a transform, never a physical parameter name.
- `source3` and `xfmr-3p2w` expose auxiliary and conditional
  ports in addition to the power terminals.
- `multimeter` has duplicate removable/non-removable `A` and `B` metadata;
  the binding must select the electrical pair deterministically.
- `xfmr-3p2w` represents winding connection with `YD1`, `YD2`, and
  `Lead`, while the logical catalog uses `Connection` and `PhaseShift_deg`;
  this requires an enumerated transform and a documented voltage-base rule.
- Direct inspection confirmed that `dc_mac_2w` is the vendor's "Two winding
  DC Machine" and that `D` means mechanical damping. It is therefore rejected
  as a line binding. The fixed catalog supplies total line resistance, so the
  executable lumped representation is `resistor:R`; `Length_km` is retained in
  the plan as reviewed, hash-covered engineering evidence and is never sent to
  PSCAD as a fake physical parameter.

The semantic correction above is backed by the installed 4.6.2 Master source
and by the official CIGRE LCC examples downloaded on 2026-08-29. Those examples
use `master:xfmr-3p2w` for the converter transformers and use explicit passive
DC-network elements rather than `dc_mac_2w`.

## Architecture

### Versioned Binding Registry

Add a repository-owned, schema-validated registry for the fixed catalog. Each
binding record contains:

```json
{
  "logical_name": "master:smoothing_reactor",
  "physical_definition": "inductor",
  "instances": 1,
  "ports": {
    "IN": {"physical": "A", "kind": "electrical", "dimension": 1},
    "OUT": {"physical": "B", "kind": "electrical", "dimension": 1}
  },
  "parameters": {
    "Inductance_mH": {
      "physical": "L",
      "unit_transform": {"kind": "scale", "factor": 0.001}
    }
  },
  "shape": {"kind": "direct"}
}
```

The registry uses strings for physical names. Unit conversions, enum/value
conversions, repeated-instance expansion, and grounding are separate typed
transform records. A numeric scale is never stored in `parameter_mapping`.
Every generated plan records the registry schema version, the complete registry
hash, the live `master.pslx` hash, and the per-definition evidence used for the
resolution.

### Live Resolver and Audit

The resolver reads the regular, immutable Master Library source and parses the
requested physical definitions with the existing XML metadata reader. For each
binding it verifies:

1. the physical definition exists exactly once;
2. every mapped port exists with the declared kind and dimension;
3. duplicate physical port names are disambiguated by a declared occurrence or
   electrical/transfer kind;
4. every mapped parameter exists and its writable/type/unit contract is
   compatible;
5. every transform is supported by a deterministic conversion function.

The read-only inventory and mapping responses expose the logical name, physical
name, selected ports, parameter transforms, source hash, and verification state.
The resolver never edits `master.pslx`.

### Shape Adapters

The normal direct path is used for source, transformer, line, meters, reactor,
and ground. The registry supplies two explicit adapters:

- `phase_expand`: one logical `cfilter` becomes three physical `cfilter`
  instances, each with its own `A`/`B` phase path and `N` connected to the
  declared ground net;
- `parameter_transform`: logical units, enum values, and reviewed fixed-model
  constants are converted before
  the physical component is created, with the converted value included in
  read-back evidence.

The registry must include reviewed transform definitions for transformer
connection/phase values, the fixed transformer voltage base, the filter's
per-phase rating and harmonic order, and the line's total resistance. A
binding is considered complete only when those transforms are executable for
the request; the presence of a same-named physical parameter is not enough.

If a catalog field has no reviewed physical counterpart, planning returns a
structured unsupported-binding error instead of silently dropping it.

### Assembly and Read-back

The LCC planner emits physical definitions and mapped arguments from the
resolver. The Legacy backend creates those physical components, then reads
back component definition, ports, and parameters. The expected logical-to-
physical record and observed record must match before the next operation or
before publication. Plan hashes include all mapping evidence, so changing the
registry, Master source, or transform invalidates an old build plan.

The native blank-template path also runs the resolver against every Master
reference it retains. Converter-specific definitions continue to come from the
audited companion library; this registry is specifically the proof that the
generic elements remain genuine Master components.

## Failure Semantics

Use structured, fail-closed errors aligned with existing HVDC/LCC contracts:

- `MASTER_BINDING_MISSING`: physical definition or required mapping is absent;
- `MASTER_BINDING_AMBIGUOUS`: duplicate definitions or ports cannot be selected
  deterministically;
- `MASTER_PORT_MISMATCH`: kind or dimension differs from the registry;
- `MASTER_PARAMETER_MISMATCH`: type, writable status, unit, or enum contract
  differs;
- `MASTER_TRANSFORM_UNSUPPORTED`: a logical value has no reviewed conversion;
- `MASTER_SOURCE_CHANGED`: the live Master hash differs from the plan;
- `MASTER_READBACK_FAILED`: PSCAD did not return the requested physical state;
- `MASTER_COMPILE_FAILED`: the mapped project did not compile.

No target project, companion copy, or output evidence is published after any of
these failures. Existing destinations and source files remain unchanged.

## Testing and Acceptance

### Offline tests

- Parse the registry and reject unknown fields, duplicate logical names, invalid
  transforms, and non-positive dimensions.
- Resolve all eight bindings against a fixture Master PSLX and verify exact
  physical names, selected port occurrences, parameter transforms, and hashes.
- Verify three-phase `cfilter` expansion and explicit neutral/ground handling.
- Verify `Inductance_mH -> L` conversion and enum/phase conversion round trips.
- Verify missing, ambiguous, wrong-kind, wrong-dimension, and stale-source
  failures occur before mutation.

### Fake-backend tests

- Confirm physical definitions, mapped parameters, and expanded instances reach
  the backend.
- Confirm read-back mismatch prevents publication and records evidence.
- Confirm a changed registry or Master source invalidates the exact plan hash.

### Licensed PSCAD smoke acceptance

Against PSCAD 4.6.2 and a timestamped copy of the fixed LCC blueprint:

1. audit all eight bindings from the installed `master.pslx`;
2. instantiate every mapped Master element, including all three expanded
   `cfilter` instances;
3. read back each physical definition, port contract, and converted parameter;
4. compile the staged project;
5. verify the original Master source and pre-existing workspace files are
   byte-for-byte unchanged.

The smoke acceptance is a mapping/compile gate. It does not by itself claim the
separate LCC commutation-fault or MMC fault-acceptance scopes.

The 2026-08-30 licensed run verified all eight logical bindings, read back the
physical definitions and converted parameters, observed three `cfilter`, three
neutral-ground, and three neutral-wire members for the filter expansion,
compiled the generated case, and confirmed the installed Master source stayed
at SHA-256 `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939`.

## Compatibility and Rollout

Existing logical catalog names and MCP request shapes remain unchanged. The
registry is additive, while planning becomes stricter: a request that formerly
used an unverified logical Master definition now returns a structured error with
the missing evidence. Once all eight bindings pass the licensed smoke gate,
their physical mapping evidence is included in normal LCC plans and reports.
