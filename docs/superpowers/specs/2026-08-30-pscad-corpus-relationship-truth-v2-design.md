# PSCAD Corpus Relationship Truth v2 Design

**Date:** 2026-08-30

**Status:** Approved design; pending implementation plan

**Work package:** R1, offline corpus relationship truth

**Primary target:** Deterministic PSCAD 4.6.x PSCX/PSLX extraction without
starting PSCAD

## 1. Purpose

Upgrade the repository-owned PSCAD Blueprint corpus from geometry-heavy
schema v1 records to schema v2 relationship truth. The upgraded corpus must
materialize instance ports, confirmed electrical and data nets, port-to-net
memberships, explicit hierarchy relationships, inference candidates, and
bounded unresolved evidence while reusing the canonical topology engine.

This work package does not add an independent connectivity algorithm. Offline
corpus generation and runtime topology inspection must agree on confirmed net
membership for the same source evidence.

## 2. Current Evidence

The committed `moxing_v1` corpus contains four normalized project graphs with:

- 4,377 component instances;
- 3,255 connection records;
- 3,170 `geometry_only` connections, approximately 97.4 percent;
- 85 explicit endpoint connections, all representing hierarchy; and
- 177 output-channel records, of which 160 are resolved.

The current graph-local definition records are insufficient to close those
relationships. Only 70 component instances have a graph-local definition with
ports, yielding 304 materializable instance ports. A further 4,277 instances
reference definitions outside the normalized project graph, primarily the
implicit Master Library.

The runtime topology layer is more mature. It already provides immutable
components, ports, conductors, labels, hierarchy boundaries, confirmed nets,
candidate edges, conflicts, and unresolved evidence. Its conservative
connectivity rules have licensed PSCAD 4.6.2 evidence on a named historical
commit. This design reuses those rules but makes no new licensed acceptance
claim.

## 3. Goals

1. Make every referenced component definition deterministically classifiable
   as port-bearing or explicitly non-connective.
2. Materialize instance ports from hash-bound definition contracts and exact
   instance geometry.
3. Build confirmed nets through `build_connectivity()` rather than a second
   corpus-specific graph algorithm.
4. Preserve raw conductor geometry as evidence while adding canonical net and
   membership records.
5. Keep confirmed, candidate, unresolved, and blocking evidence separate.
6. Produce byte-deterministic schema v2 graph, JSONL, manifest, and Blueprint
   signatures.
7. Continue reading frozen schema v1 assets without fabricating v2 relations.
8. Keep every PSCX and PSLX input byte-for-byte unchanged.

## 4. Non-Goals

R1 does not:

- add or change MCP tools;
- add component-neighbor or net-trace queries;
- optimize Legacy or Modern live topology capture;
- change runtime topology diagnostics;
- start PSCAD, compile, simulate, save, or mutate a project;
- create a licensed acceptance claim;
- construct pairwise component adjacency records for every net;
- infer functional, causal, protection, or control semantics beyond source
  evidence;
- remediate silent-learning backlog candidates; or
- update `improvement-backlog.md`.

Those concerns belong to the later R2 query, R3 performance, R4 licensed
acceptance, and separately approved guidance-remediation work packages.

## 5. Alternatives Considered

### 5.1 Integrated schema v2

Extend the corpus schema and feed normalized offline evidence through the
canonical topology engine. This produces one relationship truth model for
runtime and corpus consumers, supports deterministic training records, and
makes drift testable. This is the selected approach.

### 5.2 Sidecar relationship index

Keep schema v1 unchanged and publish a separate relation index. This reduces
initial migration work but introduces a second lifecycle, independent hashes,
and a high risk that graph and relation assets drift. It is rejected.

### 5.3 Runtime-only projection

Compute relationships on demand and do not persist them in the corpus. This
avoids asset migration but cannot support stable training records or
byte-deterministic structural regression. It is rejected.

## 6. Architecture

The offline flow is:

```text
hash-bound PSCX/PSLX inputs
        |
        v
existing Corpus Extractor
        |
        v
Normalized ProjectGraph evidence
        |
        v
CorpusDefinitionCatalog + CorpusTopologyAdapter
        |
        v
canonical ProjectTopology
        |
        v
build_connectivity() and infer_candidate_edges()
        |
        v
ProjectGraph v2 + typed JSONL + manifest + Blueprint signatures
```

Two new focused modules are expected:

- `definition_catalog.py` owns hash-bound definition-source loading, exact
  scoped resolution, definition classification, and normalized port contracts.
- `corpus_relations.py` owns the conversion from normalized corpus records to
  canonical topology records and the projection back to corpus v2 records.

`corpus_extractor.py` remains responsible for bounded XML extraction, privacy
filtering, stable logical keys, and source immutability. `connectivity.py`
remains the only implementation that decides confirmed net membership.

## 7. Hash-Bound Definition Catalog

### 7.1 Input contract

Schema v2 `source-spec.json` adds a `definition_sources` collection. Every
entry contains only portable values:

- `namespace`, such as `master` or an explicit companion-library name;
- `basename`;
- `byte_length`;
- lowercase `sha256`; and
- one or more exact `pscad_versions`; and
- `policy`, fixed to `ports-and-classification-v1` for this release.

The generation command receives an explicit namespace-to-absolute-path
mapping. Absolute paths are process inputs only and are never serialized into
an asset, report, exception detail, or record.

Project-local definitions are obtained from the admitted PSCX itself.
Companion definitions are obtained only from explicitly declared dependencies
or definition sources. Master definitions are obtained only from the declared,
hash-bound Master source selected for the entry point's declared PSCAD version.
There must be exactly one applicable source for each namespace and version. If
an entry point declares more than one PSCAD version, every applicable source
must produce the same selected normalized contracts or promotion is blocked.

### 7.2 Parsing and reuse

Each unique byte source is read into one immutable payload, hashed before use,
and parsed once with `read_definition_metadata_document()`. A post-generation
integrity read verifies the source hash again without reparsing it. The
resulting in-memory index is keyed by exact scoped name. It preserves duplicate
port occurrences, conditional-port text, raw type/model/kind fields,
dimensions, and offsets.

`MasterBindingRegistry` is not the generic corpus catalog. It covers a small
audited set of builder logical names and may remain a consumer of the same
definition metadata, but corpus coverage must include every physical
definition referenced by the admitted source projects.

### 7.3 Resolution precedence

Resolution uses this fixed order:

1. exact project-local scoped definition;
2. exact explicitly declared companion/library scope for the selected PSCAD
   version; and
3. exact declared Master scope for the selected PSCAD version.

There is no unscoped fallback, basename similarity, alias guessing, or
case-insensitive first-match selection. A missing or duplicated exact match is
blocking.

### 7.4 Classification

Every referenced definition receives one classification:

- `port_bearing`: a unique definition contract contains one or more ports;
- `non_connective`: a unique definition contract explicitly contains no ports;
  or
- `unresolved`: the source is missing, ambiguous, malformed, or insufficient
  to determine a contract.

Formal promotion requires zero `unresolved` classifications. There is no
percentage threshold because a partial percentage would silently bless the
remaining unknown relationships.

## 8. Conditional Ports

Definition metadata preserves each conditional-port expression and duplicate
occurrence. R1 implements a tokenizer and recursive-descent parser for this
closed grammar only:

- exact case-sensitive identifiers;
- finite decimal integer and floating-point literals;
- Boolean literals `true` and `false`;
- parentheses;
- unary Boolean negation `!`;
- numeric addition `+`;
- comparisons `==`, `!=`, and `>`; and
- short-circuit Boolean conjunction `&&` and disjunction `||`.

Precedence, from highest to lowest, is parentheses, unary `!`, addition,
comparison, `&&`, and `||`. Chained comparisons are rejected. Numeric zero is
false and any other finite numeric value is true when a Boolean operand is
required. Boolean values convert to zero or one only for equality checks; they
are rejected by arithmetic and ordered comparison.

The evaluator resolves an identifier from the exact instance parameter first
and otherwise from the exact definition default. Missing identifiers,
duplicate parameter names, non-finite numbers, and nonnumeric string values are
unresolved. The evaluator may return `active`, `inactive`, or `unresolved`.

An unsupported expression, missing referenced parameter, non-finite value, or
ambiguous duplicate parameter produces `CORPUS_PORT_CONDITION_UNRESOLVED` and
blocks promotion. It must not default the port to active or inactive.

Operators outside the closed grammar, including subtraction, multiplication,
division, function calls, indexing, assignment, and vendor macros, are
unsupported and block promotion. General-purpose `eval`, shell execution,
vendor macro execution, and arbitrary function calls are prohibited.

## 9. Schema v2 Records

### 9.1 Definition source

`CorpusDefinitionSource` records namespace, basename, byte length, SHA-256,
policy, selected definition count, and a deterministic catalog signature. It
contains no filesystem path.

### 9.2 Definition classification

`CorpusDefinitionClassification` records:

- stable scoped definition key;
- exact source namespace and physical definition name;
- `port_bearing` or `non_connective` classification;
- normalized port-contract keys;
- source SHA-256; and
- catalog evidence references.

Only promotable classifications enter a committed graph. Blocking unresolved
classifications remain in a proposed generation report, not in a promoted
truth asset.

### 9.3 Instance port

`CorpusInstancePort` records:

- stable key derived from component key, definition-port name, and occurrence;
- component key and definition-port key;
- name and occurrence;
- relative and absolute grid positions;
- namespace: `electrical`, `data`, or `unknown` in proposed output;
- dimension when known;
- activation state;
- definition-source evidence; and
- relationship status.

Absolute position uses the canonical PSCAD orientation transform. Missing
location, unsupported orientation, invalid offset, or unknown activation blocks
promotion rather than producing guessed geometry. An `unknown` namespace is
also blocking for a promoted instance port.

### 9.4 Confirmed net

`CorpusConfirmedNet` mirrors canonical `TopologyNet`:

- canonical SHA-256 net key;
- namespace;
- sorted instance-port keys;
- sorted conductor keys;
- sorted label keys; and
- sorted junction coordinates.

The net key is generated by the existing canonical connectivity code. The
corpus layer must not recalculate it with a separate formula.

### 9.5 Port-to-net membership

`CorpusPortNetMembership` is the durable component relationship primitive. It
records a port key, component key, confirmed net key, namespace, and stable
evidence references.

Pairwise component adjacency is derived at query time through:

```text
component -> instance port -> confirmed net -> instance port -> component
```

This preserves buses and multi-terminal networks as hyperedges and prevents
quadratic asset growth.

### 9.6 Hierarchy relation

`CorpusHierarchyRelation` preserves explicit parent/child and boundary-port
relationships. A hierarchy relation is confirmed only when both named ports,
canvases, namespace, dimension, and boundary geometry satisfy canonical
boundary validation.

### 9.7 Candidate edge

`CorpusCandidateEdge` mirrors canonical inference output and is always marked
`candidate_only`. Candidate edges:

- never enter confirmed nets;
- never satisfy a required connection;
- never enter the confirmed relation signature;
- never enter Blueprint truth expectations; and
- never remove an unresolved or error finding.

### 9.8 Unresolved evidence

`CorpusUnresolvedEvidence` contains a stable code, stable affected object keys,
bounded evidence references, and a classification describing whether it is an
engineering topology uncertainty or a blocking extraction gap. It never
contains raw XML, arbitrary exception text, or absolute paths.

## 10. Signatures and Determinism

Schema v2 distinguishes:

- `confirmed_relation_signature`, calculated from definition
  classifications, instance ports, confirmed nets, memberships, and confirmed
  hierarchy relations; and
- the existing full graph signature, calculated from the complete canonical
  serialized graph, including candidate and unresolved records.

Candidate edges and volatile observation metadata are excluded from the
confirmed relation signature. A candidate change still changes the full graph
signature and generated bytes, making all drift reviewable without promoting
the candidate to truth.

All collections are sorted by stable key. JSON remains UTF-8 with ASCII-safe
escaping, sorted object keys, finite values only, and no timestamps or random
identifiers.

## 11. Failure Semantics

Stable error codes introduced by R1 are:

- `CORPUS_DEFINITION_SOURCE_MISMATCH` for a missing, changed, wrong-sized, or
  wrong-hash definition source;
- `CORPUS_DEFINITION_UNRESOLVED` for an absent exact scoped definition;
- `CORPUS_DEFINITION_AMBIGUOUS` for multiple exact matches;
- `CORPUS_PORT_CONDITION_UNRESOLVED` for a conditional port that cannot be
  evaluated deterministically;
- `CORPUS_PORT_GEOMETRY_UNRESOLVED` for missing or invalid instance-port
  geometry;
- `CORPUS_RELATION_INCOMPLETE` for a graph that cannot satisfy the zero
  unclassified-definition gate; and
- `CORPUS_RELATION_DRIFT` for verifier disagreement between regenerated and
  committed relationship truth.

Engineering defects such as a dangling endpoint or an intentionally ambiguous
interior crossing are normalized topology findings. They do not become
extractor exceptions when all source evidence is complete.

Generation occurs in a temporary sibling directory. Any blocking error leaves
the current committed assets unchanged and publishes no partial promoted
directory.

## 12. Migration

### 12.1 Version policy

Readers support schema v1 and v2 explicitly. A v1 graph returns only fields
defined by v1; the reader must not synthesize empty v2 fields that imply
relationship completeness. The generator writes only schema v2 with
normalization profile `pscad-xml-v2` after this migration.

### 12.2 Regeneration

Migration regenerates from the original admitted, hash-bound PSCX/PSLX inputs.
It does not infer v2 truth from committed v1 graph files. The source hashes and
entry-point identities remain unchanged.

The regenerated set includes:

- four project graph JSON files;
- four typed JSONL files;
- the corpus manifest;
- the source specification with definition sources;
- four no-mutation Blueprint graph signatures; and
- documentation describing schema v2 and its definition inputs.

One small frozen v1 fixture remains in tests solely for compatibility. The
package does not publish parallel v1 and v2 production corpora.

### 12.3 Blueprint behavior

Blueprint operations remain empty. Only schema/profile declarations, graph
signatures, and relationship-aware inventory expectations change. This
migration does not turn evidence-only Blueprints into autonomous builders or
physical acceptance assets.

## 13. Testing Strategy

### 13.1 Pure unit tests

Test exact source parsing, source hash validation, scoped resolution,
definition duplication, non-connective classification, duplicate port
occurrences, conditional-port evaluation, type and dimension normalization,
orientation transforms, stable keys, finite serialization, and deterministic
ordering.

### 13.2 Canonical parity fixtures

For each topology fixture, compare two paths:

1. PSCX provider -> canonical topology -> connectivity; and
2. corpus extractor -> catalog/adapter -> canonical topology -> connectivity.

Confirmed net membership, hierarchy boundaries, unresolved codes, and the
confirmed topology hash must match exactly. Fixtures cover ordinary wiring,
T-junctions, overlaps, interior crossings, buses, mixed electrical/data
namespaces, labels, hierarchy, conditional ports, and invalid evidence.

### 13.3 Candidate isolation

Tests prove that inference mode may add candidates but cannot change confirmed
nets, the confirmed relationship signature, diagnostics, HVDC/LCC adapters, or
Blueprint truth expectations.

### 13.4 Schema v1 compatibility

A frozen v1 source spec, manifest, graph, JSONL set, and Blueprint fixture must
continue to parse. Tests assert that v1 consumers receive v1 semantics and no
fabricated relationship-completeness claim.

### 13.5 Corpus regression

The opt-in corpus regression uses explicit local source mappings, verifies all
entry-point and definition-source hashes, regenerates to a temporary directory,
and byte-compares every proposed v2 asset with the committed set. Every input
hash must match before and after generation.

### 13.6 Privacy and safety

Tests scan generated assets and bounded errors for absolute paths, usernames,
host names, denied settings, raw XML, credentials, timestamps, and environment
values. Test doubles prove that R1 has no PSCAD connection, save, build,
simulation, or mutation dependency.

### 13.7 Repository verification

The implementation is not complete until focused tests, the full non-licensed
test suite, packaging checks, corpus drift checks, and configured lint all pass.
A skipped licensed test does not affect R1 because R1 makes no licensed claim.

## 14. Performance Constraints

R1 enforces structural performance properties rather than a brittle universal
wall-clock threshold:

- every unique PSCX/PSLX byte source is parsed once, with separate bounded
  pre-use and post-generation integrity reads;
- definition resolution uses a prebuilt scoped O(1) lookup;
- component/port/net storage remains linear in emitted records;
- no pairwise component adjacency collection is materialized;
- phase timings and source-read counts are recorded in non-signature
  verification output; and
- existing canonical 500/2,000-object topology performance gates remain
  unchanged.

Tests assert source-read counts and guard against a per-component Master parse.
The later R3 work package owns Legacy live-capture and generic-diagnostic
optimization and will set current-commit licensed timing gates.

## 15. Expected Code and Asset Surface

Expected implementation areas are:

- `pscad_mcp/builders/blueprint/definition_catalog.py`;
- `pscad_mcp/builders/blueprint/corpus_relations.py`;
- `pscad_mcp/builders/blueprint/corpus_models.py`;
- `pscad_mcp/builders/blueprint/corpus_schema.py`;
- `pscad_mcp/builders/blueprint/corpus_extractor.py`;
- `pscad_mcp/builders/blueprint/corpus_writer.py`;
- `pscad_mcp/builders/blueprint/corpus_verifier.py`;
- `pscad_mcp/builders/blueprint/corpus_assets.py`;
- `scripts/build_blueprint_corpus.py`;
- focused corpus, topology-parity, privacy, compatibility, and packaging tests;
- `pscad_mcp/assets/corpora/moxing_v1/`; and
- the four promoted no-mutation Blueprint assets.

Runtime backend files, MCP topology tools, acceptance status, and learning
backlog files are outside R1 ownership.

## 16. Delivery Boundaries

R1 is one implementation plan and one isolated `codex/` branch or worktree.
It finishes before R2 begins. R2 may then add relation-oriented MCP queries
against the same canonical topology model. R3 may optimize live capture and
diagnostics after query contracts are stable. R4 runs licensed PSCAD 4.6.2
acceptance only after the final runtime changes land on a clean commit.

The six silent-learning guidance candidates remain review-only until the user
explicitly approves a candidate-ID list. They are not authorized by approval
of this design.

## 17. Completion Criteria

R1 is complete only when all of the following are true:

1. Every referenced definition is classified as `port_bearing` or
   `non_connective`; there are zero unclassified definitions.
2. Every instance port used by relationship truth has exact activation,
   namespace, dimension, and absolute geometry evidence.
3. Every confirmed net is produced by canonical `build_connectivity()`.
4. Candidate edges do not affect confirmed nets, the confirmed relation
   signature, Blueprint truth, or domain adapters.
5. All four formal corpus projects are regenerated as schema v2.
6. Graph, JSONL, manifest, and Blueprint signatures cross-validate.
7. Frozen schema v1 assets remain readable with v1 semantics.
8. Every PSCX/PSLX source hash is unchanged before and after generation.
9. Generated assets contain no denied private or host-specific data.
10. Focused tests, full non-licensed tests, packaging checks, corpus regression,
    and configured lint pass.
11. No MCP API, backend behavior, repository acceptance status, or licensed
    claim changes as part of R1.
