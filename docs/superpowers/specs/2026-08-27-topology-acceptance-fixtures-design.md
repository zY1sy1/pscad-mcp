# PSCAD Topology Acceptance Fixtures Design

**Date:** 2026-08-27
**Status:** Approved direction, pending written-spec review
**Parent design:** `2026-08-27-unified-topology-diagnostics-design.md`
**Primary target:** Licensed PSCAD 4.6.2 Legacy

## 1. Objective

Create a reproducible, independently auditable set of real PSCAD projects and
an absolute truth manifest for the unified topology diagnostics acceptance
gate. The fixtures must be loadable by PSCAD 4.6.2, exercise the required
generic topology behavior, and avoid deriving expected results from the
topology implementation under test.

This design supplements Task 12 of the unified topology implementation plan.
It does not weaken the rule that Phase 2 starts only after a current-commit
licensed `PASS` report.

## 2. Workspace Layout

The source and run workspaces remain separate:

```text
D:\PSCAD-Workspace\topology-sources\
  ordinary\ordinary.pscx
  seeded-defects\seeded-defects.pscx
  custom-library\custom-library.pscx
  hierarchy-uncertain\hierarchy-uncertain.pscx
  scale-500\scale-500.pscx
  scale-2000\scale-2000.pscx
  construction-record.json

D:\PSCAD-Workspace\topology-truth.json
D:\PSCAD-Workspace\topology-acceptance\
  topology-acceptance-<timestamp>\...
```

`topology-sources` contains immutable accepted inputs. The runner creates only
timestamped copies below `topology-acceptance`. It rejects a source located in
the run workspace.

## 3. Fixture Set

### 3.1 Ordinary

A small healthy circuit made from installed Master Library components and
explicit orthogonal wires. Every active port is connected, the confirmed net
membership is known from the construction record, and no generic error or
unresolved evidence is expected.

### 3.2 Seeded defects

One project contains five isolated construction zones, one per required error
code:

- `LABEL_CONFLICT`: equal label text and scope with electrical and data
  namespaces;
- `PORT_DIMENSION_MISMATCH`: two confirmed ports of dimensions 1 and 3 on one
  electrical net;
- `PORT_KIND_MISMATCH`: a data port touches an explicit interior vertex of an
  otherwise fully terminated electrical conductor;
- `REQUIRED_PORT_UNCONNECTED`: an active local-definition port explicitly
  marked `required=true` with no confirmed conductor;
- `WIRE_DANGLING_ENDPOINT`: one conductor endpoint terminates on a compatible
  port and the other terminates in empty space.

The zones are spaced and routed so they do not create incidental crossings,
isolated networks, label aliases, or extra dangling endpoints. The manifest
records every expected code occurrence, not only the set of code names.

### 3.3 Custom library

A healthy project contains a local two-port definition instantiated twice and
connected at every active port. It verifies definition metadata, port offsets,
orientation, and project-scoped definition resolution without relying on a
definition name from the Master Library.

### 3.4 Hierarchy uncertainty

A local child definition declares a page port while its parent instance omits
the matching outer port contract. This must produce one exact hierarchy
boundary unresolved reference and no inferred confirmed edge. The project is
intentionally incomplete, but it must not contain unrelated error findings.

### 3.5 Scale 500 and scale 2000

The scale projects use a local two-port component arranged in a collision-free
chain with a routed return conductor outside the component envelope. They
contain exactly:

- 250 components plus 250 conductors for 500 PSCAD objects;
- 1,000 components plus 1,000 conductors for 2,000 PSCAD objects.

All ports are terminated and every conductor belongs to a port-bearing net.
The layouts avoid interior crossings, label matching, and hierarchy, so the
performance cases are healthy and their confirmed net truth is deterministic.

## 4. Construction And Normalization

Construction is reproducible and uses a PSCAD-saved empty case as the format
seed. A dedicated preparation command performs these stages:

1. Create a new timestamped staging directory outside both final workspaces.
2. Build each project from a declarative recipe with explicit object identity,
   definition, geometry, port, conductor, label, and hierarchy records.
3. Use structured XML APIs for PSCX changes; do not use string replacement.
4. Start one owned PSCAD 4.6.2 Automation process, load every staged project,
   and save a normalized copy.
5. Close the owned process and fail if its PID remains alive.
6. Audit the normalized PSCX with a standalone standard-library XML reader
   that does not import `pscad_mcp.topology`.
7. Atomically publish the audited projects to `topology-sources` and the truth
   manifest to `D:\PSCAD-Workspace\topology-truth.json`.

The preparation command refuses an existing destination and never overwrites
an accepted source set.

## 5. Independent Truth

The declarative construction recipe is the truth origin. It records exact
component and conductor identities, port contracts, vertices, label
namespaces, hierarchy boundaries, and expected generic defect occurrences.

The standalone auditor verifies that the PSCAD-normalized files still match
that recipe and then projects the manifest fields:

- absolute `source_project` path;
- canvas name and healthy flag;
- sorted complete confirmed-net membership strings;
- sorted expected error-code occurrences;
- sorted expected unresolved references;
- exact minimum object count;
- required live source capabilities.

The builder and auditor must not call `TopologyService`,
`PscxSnapshotProvider`, `build_connectivity`, `diagnose_generic`, or either MCP
topology tool. Current implementation output may be compared with the manifest
only after the manifest has been published.

## 6. Safety And Evidence

- Source projects are never inspected in place by the acceptance runner.
- Construction and acceptance both refuse an already-open PSCAD process.
- Only processes launched and recorded by the command may be asked to quit.
- Project source hashes are recorded before acceptance and must equal copied
  before/after hashes.
- The preparation report records PSCAD version, executable, owned PID, recipe
  hash, source hashes, manifest hash, and normalization timestamp.
- A failed normalization or audit publishes neither sources nor manifest.

## 7. Verification

Before the licensed acceptance gate runs:

1. Unit-test recipe validation, exact object counts, stable manifest ordering,
   atomic publication, destination refusal, and the prohibition on topology
   implementation imports.
2. Run the preparation command against licensed PSCAD 4.6.2.
3. Re-open every published source project in a fresh owned PSCAD process.
4. Produce a review summary containing source hashes, object counts, net
   membership, seeded codes, unresolved references, and capability
   requirements.
5. Obtain explicit human approval of that summary before treating the manifest
   as acceptance truth.

After approval, run `scripts/run_topology_acceptance.ps1`. Only its validated
current-commit `PASS` report may update `docs/acceptance-status.json` and unlock
Phase 2.

## 8. Non-Goals

- The fixture builder is not a general PSCAD model generator.
- The fixtures do not prove electrical simulation correctness.
- The manifest does not include inference candidates as confirmed truth.
- The preparation run does not itself count as topology acceptance.
- No PSCAD 5.x acceptance claim is added.
