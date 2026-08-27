# PSCAD Unified Topology Inspection and Diagnostics Design

**Date:** 2026-08-27
**Status:** Approved design, pending implementation plan
**Primary target:** PSCAD 4.6.2

## 1. Objective

Add a read-only topology inspection and diagnostics capability that can analyze
an existing PSCAD project, including unsaved changes visible through the live
PSCAD session. The capability must combine live API evidence with saved
PSCX/XML evidence, build one version-independent project graph, and run both
generic connectivity checks and the existing HVDC/LCC domain checks against
that graph.

The default behavior is conservative: missing or contradictory evidence is
reported as unresolved and is never silently guessed. An explicit inference
mode may return candidate connections with confidence and supporting evidence,
but inferred edges never make a project pass validation.

This phase is read-only. It reports repair suggestions but does not create,
delete, move, or reconnect canvas objects.

## 2. Scope

### 2.1 In scope

- Live inspection of loaded PSCAD canvases, including unsaved additions,
  moves, rotations, labels, and connections that the selected backend can
  observe.
- Saved PSCX/XML inspection for definitions, static ports, hierarchy, and
  connection evidence not exposed by the live API.
- A canonical model for canvases, components, ports, conductors, labels,
  junctions, nets, hierarchy, source evidence, conflicts, and unresolved data.
- Conservative graph construction for wires, buses, labels, and page ports.
- Optional inference output kept separate from the confirmed graph.
- Generic diagnostics for dangling objects, isolated networks, incompatible
  ports, ambiguous crossings, label conflicts, and source conflicts.
- HVDC/LCC rules implemented as consumers of the canonical topology.
- PSCAD 4.6.2 live acceptance on timestamped project copies.
- PSCAD 5.x backend contract coverage without a real end-to-end acceptance
  claim until a licensed 5.x environment is available.

### 2.2 Out of scope

- Automatic repair, rewiring, component placement, or project saving.
- Screenshot, OCR, or symbol-image recognition.
- Inferring hidden electrical semantics without API, file, definition, or
  profile evidence.
- Treating a compile, a synthetic waveform, or unit tests as licensed PSCAD
  acceptance.
- Replacing the existing canvas mutation tools.

## 3. Architectural Principles

1. One canonical topology is the source of truth for diagnostics.
2. Providers collect evidence; they do not apply domain rules.
3. Reconciliation preserves conflicts instead of choosing silently.
4. Connectivity is deterministic and independent of PSCAD version.
5. Generic and domain diagnostics are separate rule packages.
6. Read-only behavior is enforced structurally and verified in acceptance.
7. Existing public tools and HVDC result shapes remain compatible while their
   internal data source is migrated.

## 4. Architecture

```text
Live PSCAD API --> LiveSnapshotProvider --+
                                           +--> Reconciler --> ProjectTopology
Saved PSCX/XML -> PscxSnapshotProvider ----+                         |
                                                                     +--> Generic rules
                                                                     +--> HVDC/LCC rules
```

The new package is organized as follows:

```text
pscad_mcp/topology/
  models.py
  service.py
  reconcile.py
  connectivity.py
  geometry.py
  hashing.py
  providers/
    base.py
    live.py
    pscx.py
  diagnostics/
    base.py
    generic.py
    hvdc.py
pscad_mcp/tools/topology_tools.py
```

The existing `pscad_mcp.hvdc.scanner` and
`pscad_mcp.hvdc.builders.lcc.project_graph` implementations provide the
starting XML, orientation, port, wire, and net parsing behavior. Reusable logic
is moved behind the new providers and graph builder instead of being copied.
Existing HVDC/LCC callers are migrated through adapters so public behavior can
remain stable during the transition.

## 5. Backend Boundary

The generic `list_canvas_components` response does not contain enough
information to reconstruct topology. Add one read-only backend contract:

```python
async def inspect_canvas_topology(
    project_name: str,
    canvas_name: str,
) -> LiveTopologySnapshot: ...
```

`LiveTopologySnapshot` contains the live object inventory, component identity,
location, orientation, active ports, conductor vertices, labels, object kinds,
and source capability notes. It does not contain diagnostic conclusions.

The Legacy implementation should prefer bulk automation/XML canvas commands
and cached definition metadata. It may use the existing static-port transform
fallback when the live component proxy omits port data. The Modern
implementation should use native canvas component and port APIs and preserve
the vendor-reported wire vertices. Both implementations return the same model
and explicitly report fields they cannot observe.

The topology provider depends on this abstract backend contract, not on
`mhi.pscad`, `mhrc.automation`, or backend-specific proxies.

## 6. Canonical Data Model

The canonical model uses immutable, JSON-safe records.

### 6.1 Identity

- Canvas key: normalized canvas path within the project.
- Component key: `canvas + object_id`.
- Port key: `component_key + port_name`.
- Conductor key: `canvas + object_id`, with a provider-local stable key only
  when PSCAD supplies no object ID.
- Net key: SHA-256 of the sorted confirmed endpoint keys, confirmed conductor
  keys, label namespace, and scope.

Object IDs are not matched across different canvases. Definition and location
may support an inference candidate but never replace exact identity in
conservative mode.

### 6.2 Records

- `EvidenceRef`: source kind, source object reference, observation time,
  project/file fingerprint, and evidence status.
- `TopologyCanvas`: key, display name, parent definition, and page ports.
- `TopologyComponent`: key, name, scoped definition, location, orientation,
  active state, parameters required by rules, ports, and evidence.
- `TopologyPort`: key, relative and absolute position when available, kind,
  dimension, active state, optional required contract, and evidence.
- `TopologyConductor`: key, kind (`wire` or `bus`), normalized vertices,
  electrical namespace, and evidence.
- `TopologyLabel`: name, namespace (`electrical`, `data`, or `unknown`), scope,
  location, and evidence.
- `TopologyNet`: confirmed endpoints, conductors, labels, junctions, and a
  deterministic net key.
- `TopologyConflict`: field, live value, file value, affected objects, and
  evidence references.
- `CandidateEdge`: proposed endpoints, confidence, inference reasons, and
  counter-evidence.
- `ProjectTopology`: snapshot metadata, canvases, objects, confirmed nets,
  conflicts, unresolved items, candidate edges, and topology hash.

## 7. Snapshot and Reconciliation Flow

### 7.1 Stable live snapshot

1. Read a lightweight live inventory fingerprint.
2. Read components, ports, conductors, labels, and required metadata.
3. Read the lightweight fingerprint again.
4. If the fingerprints differ, retry the full live read once.
5. If the second attempt is also unstable, return
   `TOPOLOGY_SNAPSHOT_UNSTABLE` and do not emit a complete topology.

The fingerprint includes canvas identity plus observable object IDs, kinds,
locations, orientations, and conductor summaries. It must be cheap enough to
avoid doubling the full inspection cost.

### 7.2 File snapshot

The file provider resolves the loaded project's saved PSCX path under the
existing path policy, calculates its SHA-256 hash, parses the requested canvas
and reachable definitions, and returns normalized evidence. Parse failures are
bounded and structured; raw XML text is never included in MCP error details.

### 7.3 Merge policy

- Live evidence is authoritative for current object existence, location,
  orientation, active ports, labels, and conductor geometry.
- File evidence supplements scoped definitions, static port contracts,
  hierarchy, and fields the live provider explicitly cannot observe.
- An object found only in the saved file is marked `stale_file_evidence` and is
  excluded from the effective live graph.
- A live object absent from the file remains in the effective graph and is
  marked `unsaved_live_evidence`.
- Contradictory observed values produce `TopologyConflict`; neither value is
  silently discarded.
- File-only conductor data is not treated as current when the live provider
  cannot confirm conductor state. It remains unresolved.

## 8. Connectivity Rules

All geometry is normalized to PSCAD grid coordinates before graph building.
Port transforms account for all supported rotations and mirror states.

In conservative mode:

- A conductor endpoint or explicit vertex coincident with a port connects to
  that port.
- Collinear overlapping conductor segments in the same namespace merge.
- A conductor vertex lying on another conductor segment creates a T-junction.
- Two conductor interiors that merely cross do not connect without an explicit
  vertex, junction, vendor connection record, or equivalent evidence. The
  crossing is reported as ambiguous.
- A bus joins only endpoints or explicit vertices that touch its geometry.
- Electrical node labels and data labels use distinct namespaces.
- Labels connect only when normalized name, namespace, and scope match.
- Page and definition boundaries connect only through explicit page or
  definition ports.
- Unknown namespace, missing geometry, malformed conductor vertices, or
  ambiguous hierarchy produces unresolved evidence instead of an edge.

Inference mode runs after the confirmed graph is complete. It may propose
candidate edges based on location tolerance, definition contracts, label
similarity, or graph context. Candidate edges are stored separately and are
not included in confirmed net hashes or pass/fail validation.

## 9. MCP Tools

### 9.1 `inspect_project_topology`

```text
inspect_project_topology(
  project_name,
  canvas_name="Main",
  mode="conservative"
)
```

Returns snapshot metadata, normalized object counts, confirmed nets,
conflicts, unresolved evidence, optional candidate edges, and the topology
hash. Large object collections use the repository's existing bounded-output
conventions; the response must retain stable object references even when
details are summarized.

### 9.2 `diagnose_project_topology`

```text
diagnose_project_topology(
  project_name,
  canvas_name="Main",
  ruleset="generic+hvdc-auto",
  mode="conservative"
)
```

Supported initial rule sets are `generic` and `generic+hvdc-auto`. The latter
always runs generic diagnostics, then selects the applicable HVDC/LCC rules
from confirmed evidence. An ambiguous family produces the existing
`HVDC_TOPOLOGY_AMBIGUOUS` finding rather than selecting a rule package by
guessing.

Both tools are read-only and are registered through the existing guarded MCP
tool registration path.

## 10. Diagnostic Model

Each finding contains:

- stable `code`;
- `severity`: `info`, `warning`, or `error`;
- `status`: `observed`, `derived`, `conflict`, or `unresolved`;
- confidence from 0.0 to 1.0;
- stable affected object references;
- bounded evidence references;
- concise message;
- read-only suggested action.

Initial generic diagnostic codes:

- `PORT_UNCONNECTED`
- `REQUIRED_PORT_UNCONNECTED`
- `WIRE_DANGLING_ENDPOINT`
- `ISOLATED_NETWORK`
- `PORT_KIND_MISMATCH`
- `PORT_DIMENSION_MISMATCH`
- `CROSSING_AMBIGUOUS`
- `LABEL_CONFLICT`
- `SOURCE_CONFLICT`
- `TOPOLOGY_INCOMPLETE`

`REQUIRED_PORT_UNCONNECTED` is emitted only when a definition or selected
domain contract explicitly marks the active port as required. A port with no
required contract may receive `PORT_UNCONNECTED`, but not an error solely
because it is unconnected.

HVDC/LCC rules preserve existing public codes, including
`HVDC_TOPOLOGY_AMBIGUOUS`, `HVDC_RETURN_PATH_UNRESOLVED`, and
`HVDC_MAPPING_CONFLICT`.

Operational failures such as unavailable PSCAD, missing project, or unreadable
canvas remain structured tool errors. Engineering defects and evidence gaps
are returned as findings. Candidate edges never remove an error or unresolved
finding from the conservative result.

## 11. Read-Only Safety

The topology call path must expose no mutation dependency. Providers may call
only backend methods classified as reads. They must never call component
parameter setters, canvas creation methods, save operations, builds, or
simulation controls.

Acceptance verifies all of the following:

- project file hash is unchanged;
- object counts and identities are unchanged;
- PSCAD dirty state is unchanged when the API exposes it;
- no mutation backend method is invoked;
- repeated inspection of an unchanged project produces the same topology
  hash.

## 12. Performance

The 4.6.2 provider should use bulk canvas reads and definition metadata caches
instead of one automation round trip per field. Cache keys include the
definition source path and file hash so library changes invalidate cached
ports and parameter contracts.

Targets on the acceptance machine:

- approximately 500 canvas objects: complete diagnosis within 3 seconds;
- approximately 2,000 canvas objects: complete diagnosis within 10 seconds.

Responses record phase timings for live capture, file parse, reconciliation,
graph construction, generic rules, and domain rules. Timing data is diagnostic
metadata and does not change the topology hash.

## 13. Verification Strategy

### 13.1 Unit tests

Test port transforms, segment normalization, overlaps, T-junctions, interior
crossings, buses, label namespaces, hierarchy, stable identities, hashing,
conflict preservation, and inference isolation.

### 13.2 Golden PSCX fixtures

Maintain manually audited fixtures for:

- ordinary electrical wiring;
- mixed electrical and control signals;
- custom library definitions;
- hierarchical pages and definition ports;
- HVDC/LCC topology.

Expected components, ports, conductors, nets, conflicts, and findings are
checked exactly.

### 13.3 Backend contract tests

Legacy and Modern fake backends describe the same logical projects. Tests
verify normalized parity, live-only unsaved objects, saved-only stale objects,
movement and rotation, snapshot instability, and partial capability behavior.

Modern 5.x remains contract-tested only until a licensed 5.x end-to-end run is
available.

### 13.4 Licensed PSCAD 4.6.2 acceptance

Run read-only inspection on timestamped copies representing ordinary,
custom-library, hierarchical, and HVDC/LCC projects. Reports record the commit,
PSCAD version, input hashes, topology hashes, rule version, timings, finding
counts, and source capability inventory.

Acceptance thresholds:

- every confirmed connection in the manually audited truth set matches;
- every seeded dangling port, broken conductor, kind conflict, dimension
  conflict, and label conflict is detected;
- a healthy baseline has no false `error` finding;
- uncertain evidence is unresolved rather than guessed;
- two unchanged reads produce the same topology hash;
- project files and live canvases remain unchanged;
- the stated performance targets pass on the acceptance machine.

## 14. Delivery Sequence

### Phase 1: Canonical generic topology

Implement canonical models, both providers, reconciliation, confirmed graph
construction, generic diagnostics, MCP tools, fixtures, and 4.6.2 read-only
acceptance.

### Phase 2: Unified HVDC/LCC rules

Adapt existing HVDC scanning, classification, return-path, and LCC graph
validation to consume `ProjectTopology`. Preserve public HVDC tool responses
and stable error codes, add cross-check fixtures, then extend the licensed
read-only acceptance report.

Both phases belong to this design, but Phase 2 begins only after the generic
topology acceptance thresholds pass. This prevents domain rules from hiding
errors in the underlying graph.

## 15. Completion Criteria

The work is complete when both MCP tools are registered, generic and HVDC/LCC
rules consume the canonical topology, all non-licensed tests pass, the 4.6.2
read-only acceptance report passes for the named commit and fixtures, and the
documentation distinguishes 4.6.2 licensed acceptance from 5.x contract-only
coverage.
