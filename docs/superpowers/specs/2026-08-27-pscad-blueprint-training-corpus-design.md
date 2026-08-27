# PSCAD Blueprint Training Corpus Design

**Date:** 2026-08-27

**Status:** Approved for implementation planning

## 1. Purpose

Use the PSCAD models in the user-managed `moxing` directory as read-only inputs
for two related capabilities:

1. Blueprint Builder source templates and deterministic structural regression
   baselines.
2. A normalized local dataset containing PSCAD project topology, definitions,
   components, parameters, ports, connections, settings, and output-channel
   declarations.

The repository must not copy or commit the original PSCAD models. It stores only
hash-bound manifests, reviewed Blueprint assets, normalized dataset records, and
validation evidence. This corpus pipeline is independent of
`pscad_mcp.learning`; the silent-learning subsystem remains scalar-only and does
not store project content or train models.

## 2. Source Scope

The initial corpus contains these four PSCX entry points:

- `HVDC_Bipolar_1000MW_500kV.pscx`
- `HVDC_Bipolar5kA500kVtest.pscx`
- `HVDC_Bipolar5kA500kVtrans.pscx`
- `ls800zhengque1226.pscx`

`HVDC_Bipolar5kA500kVtrans.psmx` is recorded only when an entry point actually
references it. The `.bakx` backup and all `.gf46` compiler, executable, log, and
simulation-output artifacts are excluded from the corpus. Future source files
must be admitted through an explicit manifest change rather than directory-wide
implicit discovery.

The source root is supplied at generation time. It is never embedded in a
committed asset, report, test snapshot, exception, or dataset record. Source
files are opened read-only, are never staged or rewritten, and have their
SHA-256 values checked before and after extraction.

## 3. Chosen Approach

Implement a generic two-stage extractor:

1. A deterministic offline PSCX extractor produces the complete baseline corpus
   without starting PSCAD or requiring a license.
2. An optional live inventory verifier opens the same hash-bound project through
   the existing PSCAD service in read-only inspection mode and records semantic
   agreement for definitions, parameters, and ports.

Offline extraction is authoritative for dataset reproducibility. Live inventory
is additional verification evidence and must not silently alter normalized
records. A live mismatch fails verification and is reported explicitly.

Project-specific hard-coded conversion is rejected because it cannot scale to
new models and would hide schema differences. Raw XML dumping is rejected
because vendor IDs, personal metadata, formatting, and element order would make
the dataset noisy, unstable, and unsafe to reuse.

## 4. Architecture

Add corpus support beside the generic Blueprint Builder while keeping execution
and ingestion responsibilities separate:

- `pscad_mcp/builders/blueprint/corpus_models.py`: immutable corpus manifest,
  normalized graph, record, warning, and verification models.
- `pscad_mcp/builders/blueprint/corpus_schema.py`: strict versioned parsing and
  JSON-safe validation for committed corpus assets.
- `pscad_mcp/builders/blueprint/corpus_extractor.py`: bounded offline XML
  extraction, normalization, reference resolution, and privacy filtering.
- `pscad_mcp/builders/blueprint/corpus_writer.py`: canonical JSON and JSONL
  serialization with atomic replacement.
- `pscad_mcp/builders/blueprint/corpus_verifier.py`: source immutability,
  committed-asset drift, Blueprint regression, and optional live inventory
  checks.
- `scripts/build_blueprint_corpus.py`: explicit local generation and verification
  entry point.

Committed normalized assets live under
`pscad_mcp/assets/corpora/moxing_v1/`. Reviewed, executable no-mutation Blueprint
assets live under `pscad_mcp/assets/blueprints/`, one directory per source
project. Package-data rules include only the derived JSON and JSONL artifacts.

No new MCP tool is required in the first release. Corpus generation is a
maintainer workflow with explicit filesystem inputs, not a runtime model-building
operation exposed to clients.

## 5. Input Manifest

The generator accepts an explicit source root and a repository-owned corpus
specification. The specification contains only portable values:

- corpus schema version and stable corpus name;
- exact allowed entry-point basenames;
- expected SHA-256 and byte length for every admitted file;
- optional companion dependency basenames and hashes;
- declared PSCAD versions where known;
- inclusion and exclusion policy identifiers; and
- normalization profile version.

No recursive wildcard admits additional source content. A missing file, extra
declared dependency, unexpected hash, symbolic link, non-regular file, or source
change during extraction fails closed.

## 6. Offline Extraction

Parse PSCX as XML with the Python standard library. The extractor disables any
external-resource behavior, imposes configured file-size and element-count
bounds, and rejects malformed or unsupported roots before producing output.

For each project, extract and normalize:

- project identity, PSCAD version, target, and allowed simulation settings;
- user and master-library component definitions;
- definition parameters, types, dimensions, units, bounds, and intent;
- definition ports, models, names, dimensions, modes, types, and coordinates;
- component instances, definition references, stable names, canvas ownership,
  locations, orientations, and instance parameter values;
- canvases and hierarchy relationships;
- electrical wires, data connections, signal labels, buses, and resolved
  endpoints where represented by the source schema;
- declared output channels and their source bindings; and
- referenced project or module dependencies.

Runtime numeric IDs may be used only while resolving references inside one
parse. They are replaced in committed output by deterministic logical keys
derived from stable structural fields. When a stable key cannot be constructed
without ambiguity, the record is marked unresolved and the quality gate fails
for Blueprint generation.

Unknown XML elements are counted and reported with bounded, schema-level names.
Their raw content is not copied into the corpus. This prevents silent loss while
avoiding an uncontrolled raw XML dataset.

## 7. Normalization and Privacy

Canonicalization uses UTF-8, ASCII-safe JSON escaping, sorted object keys,
stable record ordering, finite JSON numbers, normalized unit strings, and
forward-slash package-relative paths. Generated artifacts contain no wall-clock
timestamp, random identifier, absolute path, or host name, so identical inputs
and extractor versions produce byte-identical output.

The following content is always removed:

- project `creator` and `revisor` values;
- usernames, machine paths, recent-file values, and host-specific settings;
- build timestamps, volatile runtime IDs, and editor-only session state;
- credentials or environment-variable values;
- compiler, executable, log, backup, snapshot, and simulation-result content;
  and
- free-form fields not explicitly admitted by the normalization schema.

Engineering names, component definitions, parameter names and values, units,
ports, positions, and connectivity are retained because they are the intended
training features. Every retained field is enumerated by the strict corpus
schema.

## 8. Dataset Contract

The corpus produces a canonical `manifest.json`, one normalized project graph
per source model, and typed training records. Every record includes:

- corpus schema and normalization-profile versions;
- corpus and project stable identifiers;
- source content SHA-256, never the source path;
- record kind and deterministic record key;
- normalized feature payload; and
- resolution and verification status.

Record kinds are:

- `project`
- `definition`
- `component`
- `parameter`
- `port`
- `connection`
- `project_setting`
- `output_channel`

JSON project graphs support regression and inspection. Canonical JSONL records
support downstream training without coupling the repository to a particular ML
framework. The project graph is the evidence source from which JSONL records are
derived; the writer verifies record counts and content hashes in `manifest.json`.

## 9. Blueprint Template Contract

Each admitted PSCX receives a reviewed schema-version-1 Blueprint asset whose
source package is read-only and whose entry point and required files are bound to
the corpus hashes. The initial template applies no mutations. Its purpose is to
exercise planning, source audit, inventory binding, persistence-neutral graph
inspection, and structural regression against an existing complete project.

The generated candidate is never committed automatically as trusted executable
input. Generation writes it to a proposed-output location; verification parses
it with the production Blueprint schema, checks that the operation list is empty,
and compares its declared structure with the normalized graph. A maintainer then
reviews and promotes it into `pscad_mcp/assets/blueprints/`.

Blueprint acceptance uses only structure and model-observed values. These
templates cannot claim physical acceptance, and their publication scope is
`evidence_only` or `model_run_through_only` as appropriate.

## 10. Optional Live Verification

Live verification is opt-in and requires explicit environment configuration for
the source root, workspace, PSCAD version, and licensed execution permission. It
opens each project only for inventory inspection and must not save, compile,
simulate, or publish the source.

The verifier compares offline and live observations for:

- project and canvas discovery;
- definition identity;
- component cardinality and selector uniqueness;
- parameter names, values, and units where exposed;
- port names, dimensions, modes, and types; and
- output-channel declarations where exposed.

Live evidence records the source hash, backend identity, PSCAD version, exact
check outcomes, and a `live_verified` flag. A skipped test or unavailable license
never sets `live_verified=true`.

## 11. Failure Handling and Quality Gates

Corpus generation fails without replacing committed output when any of these
conditions occurs:

- source hash or size differs from the admitted manifest;
- a source file changes between pre-read and post-read checks;
- XML is malformed, exceeds configured bounds, or uses an unsupported project
  root;
- component, definition, canvas, port, or connection references are dangling or
  ambiguous;
- deterministic logical keys collide;
- a number is non-finite or a value cannot be serialized safely;
- a privacy-denied field reaches a proposed artifact;
- record counts or hashes disagree with the project graph;
- regeneration differs without a schema or normalization-profile version bump;
  or
- a Blueprint candidate does not parse or match its normalized source graph.

Unknown but bounded schema elements produce a quality report. They block
Blueprint promotion when they affect topology, parameters, or connectivity;
otherwise they remain explicit warnings in the manifest.

Writers build all artifacts in a temporary sibling directory, validate the full
set, and atomically replace the destination only after every gate passes.

## 12. Testing Strategy

### Pure Tests

Test strict corpus parsing, canonical serialization, stable logical keys, record
derivation, privacy filtering, finite values, ordering, hash calculation, and
warning classification.

### Offline Fixture Tests

Use small repository-owned PSCX fixtures covering definitions, instances,
parameters, ports, nested canvases, electrical wires, data links, outputs,
dangling references, duplicate identifiers, malformed XML, unknown elements,
and privacy-denied settings. Verify that generation never changes fixture bytes.

### Local Corpus Regression

An opt-in test reads the user-supplied source root, verifies the four admitted
hashes, regenerates into a temporary directory, and byte-compares every artifact
with the committed corpus. The test must never write inside the source root.

### Blueprint Regression

Parse every promoted Blueprint through the production schema, audit its source
package with the expected hashes, require an empty initial operation list, and
compare normalized graph signatures and inventory expectations.

### Licensed Verification

Opt-in licensed tests compare the offline corpus with live PSCAD inventory. They
must prove the source hashes remain unchanged and report skips as unverified.

## 13. Documentation and Operational Workflow

Document one repeatable maintainer command that requires an explicit source root
and proposed-output directory. The workflow is:

1. verify the admitted source manifest;
2. extract and normalize into a temporary output;
3. run privacy and quality gates;
4. generate candidate no-mutation Blueprints;
5. compare proposed output with committed assets;
6. optionally run live inventory verification; and
7. review and promote derived assets through a normal commit.

README documentation must state that the corpus is derived from user-managed
models, excludes original model files and simulation results, and is unrelated
to silent local learning.

## 14. Completion Criteria

The feature is complete when:

1. all four admitted PSCX files produce deterministic normalized graphs and typed
   training records;
2. the source directory remains byte-for-byte unchanged;
3. committed artifacts contain no absolute paths or denied metadata;
4. record hashes and counts validate against the manifest;
5. four reviewed no-mutation Blueprint assets pass production schema and source
   hash audits;
6. offline fixture, corpus regression, packaging, and full repository tests pass;
7. optional licensed checks clearly distinguish verified, skipped, and failed
   outcomes; and
8. documentation preserves the boundary between corpus generation and silent
   learning.
