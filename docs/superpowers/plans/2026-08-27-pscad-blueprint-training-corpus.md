# PSCAD Blueprint Training Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, privacy-filtered corpus and four reviewed no-mutation Blueprint candidates from the explicitly admitted PSCX models without copying or changing the source projects.

**Architecture:** A strict repository-owned source specification admits exact basenames, sizes, and hashes. A bounded offline extractor converts each PSCX into an immutable normalized project graph; a canonical writer derives JSONL records and promotes a complete candidate directory only after schema, hash, privacy, and Blueprint gates pass. Optional live verification compares the offline graph with the existing PSCAD service but never changes corpus records or source files.

**Tech Stack:** Python 3.10+, standard-library `xml.etree.ElementTree`, `hashlib`, `json`, `argparse`, `tempfile`, immutable dataclasses, existing Blueprint schema/audit APIs, pytest/unittest-compatible tests.

---

## File Map

- `pscad_mcp/builders/blueprint/corpus_models.py`: immutable corpus specification, graph, record, warning, manifest, and verification records.
- `pscad_mcp/builders/blueprint/corpus_schema.py`: exact-field parsing for source specifications and committed manifests.
- `pscad_mcp/builders/blueprint/corpus_extractor.py`: source admission, bounded XML parsing, privacy filtering, normalization, and stable logical-key construction.
- `pscad_mcp/builders/blueprint/corpus_writer.py`: canonical JSON/JSONL derivation, content hashes, candidate validation, and directory promotion.
- `pscad_mcp/builders/blueprint/corpus_verifier.py`: graph/record drift checks, no-mutation Blueprint generation and verification, and optional live inventory comparison.
- `scripts/build_blueprint_corpus.py`: maintainer CLI for generation, comparison, promotion, and opt-in live verification.
- `pscad_mcp/assets/corpora/moxing_v1/source-spec.json`: portable allowlist with the four observed PSCX hashes and sizes.
- `pscad_mcp/assets/corpora/moxing_v1/manifest.json`: generated artifact counts and hashes.
- `pscad_mcp/assets/corpora/moxing_v1/graphs/*.json`: four normalized project graphs.
- `pscad_mcp/assets/corpora/moxing_v1/records/*.jsonl`: typed records derived only from those graphs.
- `pscad_mcp/assets/blueprints/<project-key>/blueprint.json`: reviewed empty-operation Blueprint assets.
- `tests/fixtures/blueprint_corpus/*.pscx`: small repository-owned XML fixtures, including malformed and privacy cases.
- `tests/test_blueprint_corpus_schema.py`: contract and exact-field tests.
- `tests/test_blueprint_corpus_extractor.py`: bounded extraction, normalization, stable-key, reference, and source-integrity tests.
- `tests/test_blueprint_corpus_writer.py`: canonical byte, record, manifest, privacy, and atomic-promotion tests.
- `tests/test_blueprint_corpus_verifier.py`: Blueprint and live-inventory agreement tests.
- `tests/test_blueprint_corpus_regression.py`: opt-in local four-model regeneration and byte comparison.
- `tests/test_blueprint_corpus_live.py`: opt-in licensed read-only inventory comparison.

### Task 1: Strict Corpus Contracts and Source Allowlist

**Files:**
- Create: `pscad_mcp/builders/blueprint/corpus_models.py`
- Create: `pscad_mcp/builders/blueprint/corpus_schema.py`
- Create: `pscad_mcp/assets/corpora/moxing_v1/source-spec.json`
- Create: `tests/test_blueprint_corpus_schema.py`
- Modify: `pscad_mcp/builders/blueprint/__init__.py`

- [ ] **Step 1: Write failing exact-contract tests**

```python
def test_parse_corpus_spec_returns_immutable_portable_contract():
    parsed = parse_corpus_spec(valid_spec())
    assert parsed.name == "moxing_v1"
    assert parsed.entry_points[0].basename == "HVDC_Bipolar_1000MW_500kV.pscx"
    assert parsed.entry_points[0].byte_length == 348498
    assert parsed.entry_points[0].sha256 == "159e89dde51845fe2043b04286d13d362ddb866d597678c19e961a6c69c86993"
    assert parsed.to_dict() == valid_spec()
    with pytest.raises(TypeError):
        parsed.entry_points[0].dependencies["x"] = "y"


@pytest.mark.parametrize("field", ["absolute_path", "generated_at", "host", "unexpected"])
def test_parse_corpus_spec_rejects_unknown_or_nonportable_fields(field):
    value = valid_spec()
    value[field] = "forbidden"
    with pytest.raises(BackendError, match="CORPUS_SPEC_INVALID"):
        parse_corpus_spec(value)
```

- [ ] **Step 2: Run the tests and confirm the missing-module RED state**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_schema.py -q`

Expected: collection fails because `corpus_models` and `corpus_schema` do not exist.

- [ ] **Step 3: Implement immutable models and strict parsing**

```python
@dataclass(frozen=True)
class CorpusSource:
    project_id: str
    basename: str
    byte_length: int
    sha256: str
    pscad_versions: tuple[str, ...]
    dependencies: tuple[CorpusDependency, ...]


@dataclass(frozen=True)
class CorpusSpec:
    schema_version: int
    normalization_profile: str
    name: str
    inclusion_policy: str
    exclusion_policy: str
    entry_points: tuple[CorpusSource, ...]


def parse_corpus_spec(value: Any) -> CorpusSpec:
    record = exact_mapping(
        value,
        {"schema_version", "normalization_profile", "name", "inclusion_policy", "exclusion_policy", "entry_points"},
        "corpus_spec",
    )
    if record["schema_version"] != 1:
        raise corpus_error("CORPUS_SPEC_UNSUPPORTED", "Only corpus schema version 1 is supported.")
    entries = tuple(parse_source(item, index) for index, item in enumerate(record["entry_points"]))
    require_unique((item.project_id for item in entries), "project_id")
    require_unique((item.basename for item in entries), "basename")
    return CorpusSpec(
        schema_version=1,
        normalization_profile=portable_name(record["normalization_profile"], "normalization_profile"),
        name=portable_name(record["name"], "name"),
        inclusion_policy=portable_name(record["inclusion_policy"], "inclusion_policy"),
        exclusion_policy=portable_name(record["exclusion_policy"], "exclusion_policy"),
        entry_points=entries,
    )
```

`parse_source` and `parse_dependency` must parse exact nested field sets and validate lowercase SHA-256 values, positive byte lengths, simple basenames, and non-empty PSCAD version strings. `portable_name` rejects absolute paths and path separators; `require_unique` rejects duplicate IDs or basenames; every parser rejects booleans used as integers and non-JSON values.

- [ ] **Step 4: Add the observed portable allowlist**

`source-spec.json` must contain exactly these PSCX entries:

```json
{
  "schema_version": 1,
  "normalization_profile": "pscad-xml-v1",
  "name": "moxing_v1",
  "inclusion_policy": "explicit-entry-points-v1",
  "exclusion_policy": "no-backups-builds-results-v1",
  "entry_points": [
    {"project_id": "hvdc-bipolar-1000mw-500kv", "basename": "HVDC_Bipolar_1000MW_500kV.pscx", "byte_length": 348498, "sha256": "159e89dde51845fe2043b04286d13d362ddb866d597678c19e961a6c69c86993", "pscad_versions": ["4.6.3"], "dependencies": []},
    {"project_id": "hvdc-bipolar-5ka-500kv-test", "basename": "HVDC_Bipolar5kA500kVtest.pscx", "byte_length": 364336, "sha256": "de29d301921f659ba30d0bd28760ae8ef184871c80e0e14896bfd575367ffb81", "pscad_versions": ["4.6.2"], "dependencies": []},
    {"project_id": "hvdc-bipolar-5ka-500kv-trans", "basename": "HVDC_Bipolar5kA500kVtrans.pscx", "byte_length": 485964, "sha256": "ca9f2a7915fba3d96e67bb19d33f2aba00476f126fe93fbcec4cd445275162ee", "pscad_versions": ["4.6.2"], "dependencies": []},
    {"project_id": "ls800zhengque1226", "basename": "ls800zhengque1226.pscx", "byte_length": 2665188, "sha256": "027d8b21f2f2035e5a67cb93197ee881286871f3ac323211b811e0e8339294aa", "pscad_versions": ["4.6.2"], "dependencies": []}
  ]
}
```

Do not admit the observed `.bakx`, `.gf46`, or `.psmx`. A read-only search confirmed that `HVDC_Bipolar5kA500kVtrans.pscx` contains no `.psmx` reference, so every initial dependency list is intentionally empty.

- [ ] **Step 5: Run schema tests and commit**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_schema.py -q`

Expected: all corpus schema tests pass.

```powershell
git add pscad_mcp/builders/blueprint/corpus_models.py pscad_mcp/builders/blueprint/corpus_schema.py pscad_mcp/builders/blueprint/__init__.py pscad_mcp/assets/corpora/moxing_v1/source-spec.json tests/test_blueprint_corpus_schema.py
git commit -m "feat: define PSCAD blueprint corpus contract"
```

### Task 2: Bounded Read-Only PSCX Admission and Privacy Filtering

**Files:**
- Create: `pscad_mcp/builders/blueprint/corpus_extractor.py`
- Create: `tests/fixtures/blueprint_corpus/minimal.pscx`
- Create: `tests/fixtures/blueprint_corpus/privacy.pscx`
- Create: `tests/test_blueprint_corpus_extractor.py`

- [ ] **Step 1: Write failing admission and immutability tests**

```python
def test_extract_project_verifies_hash_size_and_preserves_source_bytes(tmp_path):
    source = copy_fixture(tmp_path, "minimal.pscx")
    before = source.read_bytes()
    admitted = source_contract(source, project_id="minimal")
    graph = extract_project(source.parent, admitted, ExtractionLimits())
    assert graph.source_sha256 == hashlib.sha256(before).hexdigest()
    assert source.read_bytes() == before


@pytest.mark.parametrize("failure", ["hash", "size", "symlink", "malformed", "oversize", "too_many_elements"])
def test_extract_project_fails_closed_before_returning_a_graph(tmp_path, failure):
    source, admitted, limits = arrange_failure(tmp_path, failure)
    with pytest.raises(BackendError) as raised:
        extract_project(source.parent, admitted, limits)
    assert raised.value.code.startswith("CORPUS_SOURCE_") or raised.value.code.startswith("CORPUS_XML_")
```

- [ ] **Step 2: Write failing privacy allowlist tests**

```python
def test_project_settings_drop_identity_paths_and_volatile_fields(tmp_path):
    graph = extract_fixture(tmp_path, "privacy.pscx")
    serialized = canonical_json(graph.to_dict()).decode("ascii")
    assert "creator" not in graph.settings
    assert "revisor" not in graph.settings
    assert "C:\\\\Users" not in serialized
    assert "build_time" not in serialized
    assert graph.settings["time_duration"] == "5"
    assert graph.settings["time_step"] == "50"
```

- [ ] **Step 3: Run focused tests and confirm RED**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_extractor.py -q`

Expected: failures identify the absent extractor.

- [ ] **Step 4: Implement source admission and bounded parsing**

```python
@dataclass(frozen=True)
class ExtractionLimits:
    max_file_bytes: int = 8 * 1024 * 1024
    max_elements: int = 100_000
    max_text_chars: int = 1_000_000
    max_unknown_names: int = 128


def extract_project(source_root: str | Path, source: CorpusSource, limits: ExtractionLimits) -> ProjectGraph:
    root = Path(source_root).resolve(strict=True)
    candidate = root / source.basename
    require_direct_regular_child(root, candidate)
    pre_stat = candidate.stat()
    pre_hash = sha256_file(candidate)
    require_expected_source(pre_stat.st_size, pre_hash, source, limits)
    document = bounded_parse(candidate, limits)  # ElementTree; reject any `<!DOCTYPE` or `<!ENTITY` bytes before parse.
    graph = normalize_project(document.getroot(), source, limits)
    post_stat = candidate.stat()
    post_hash = sha256_file(candidate)
    if (post_stat.st_size, post_hash) != (pre_stat.st_size, pre_hash):
        raise corpus_error("CORPUS_SOURCE_CHANGED", "Source changed during extraction.", project_id=source.project_id)
    return graph
```

`normalize_project` must accept only root tag `project`, retain only the explicitly enumerated settings (`time_duration`, `time_step`, `sample_step`, `chatter_threshold`, `branch_threshold`, `StartType`, `PlotType`, `SnapType`, `SnapTime`, `MrunType`, `Mruns`, `Scenario`, `Advanced`, `Options`, `Build`, `Warn`, `Check`, `description`), and never copy free-form unknown text or exception values.

- [ ] **Step 5: Run focused tests and commit**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_extractor.py -q`

Expected: admission and privacy tests pass.

```powershell
git add pscad_mcp/builders/blueprint/corpus_extractor.py tests/fixtures/blueprint_corpus tests/test_blueprint_corpus_extractor.py
git commit -m "feat: add bounded read-only PSCX extraction"
```

### Task 3: Normalize Definitions, Components, Ports, Wires, and Outputs

**Files:**
- Modify: `pscad_mcp/builders/blueprint/corpus_models.py`
- Modify: `pscad_mcp/builders/blueprint/corpus_extractor.py`
- Modify: `tests/fixtures/blueprint_corpus/minimal.pscx`
- Create: `tests/fixtures/blueprint_corpus/dangling.pscx`
- Modify: `tests/test_blueprint_corpus_extractor.py`

- [ ] **Step 1: Add failing graph-shape and stable-key tests**

```python
def test_extract_project_normalizes_graph_without_runtime_ids(tmp_path):
    graph = extract_fixture(tmp_path, "minimal.pscx")
    assert graph.project_id == "minimal"
    assert graph.definitions[0].key == "definition:user:controller"
    assert graph.definitions[0].parameters[0].to_dict() == {
        "name": "Kp", "type": "real", "dimension": "1", "units": "pu", "minimum": "0", "maximum": "10", "intent": "input"
    }
    assert graph.definitions[0].ports[0].key == "definition:user:controller/port:in:1"
    assert graph.components[0].key == "canvas:main/component:controller@198,270#1"
    assert graph.connections[0].kind == "wire"
    assert "runtime_id" not in json.dumps(graph.to_dict())


def test_logical_keys_are_byte_stable_when_runtime_ids_change(tmp_path):
    first = extract_fixture(tmp_path, "minimal.pscx")
    rewrite_only_runtime_ids(tmp_path / "minimal.pscx")
    second = normalize_without_source_hash(tmp_path / "minimal.pscx")
    assert graph_signature(first) == graph_signature(second)
```

- [ ] **Step 2: Add failing dangling/collision/unknown-element tests**

```python
def test_dangling_definition_reference_blocks_blueprint_quality(tmp_path):
    with pytest.raises(BackendError) as raised:
        extract_fixture(tmp_path, "dangling.pscx")
    assert raised.value.code == "CORPUS_REFERENCE_UNRESOLVED"


def test_unknown_non_topology_element_is_bounded_warning(tmp_path):
    graph = extract_fixture(tmp_path, "unknown-editor-state.pscx")
    assert graph.warnings == (CorpusWarning("unknown_element", "project/editorState", 1, False),)
```

- [ ] **Step 3: Implement the normalized graph**

Use these exact stable inputs:

```python
def definition_key(name: str, class_id: str) -> str:
    namespace = "user" if ":" not in name else name.split(":", 1)[0].lower()
    return f"definition:{namespace}:{slug(name.split(':')[-1])}"


def component_key(canvas_key: str, definition: str, x: int, y: int, ordinal: int) -> str:
    return f"{canvas_key}/component:{slug(definition)}@{x},{y}#{ordinal}"


def wire_key(canvas_key: str, vertices: tuple[tuple[int, int], ...], ordinal: int) -> str:
    digest = sha256_bytes(canonical_json([[x, y] for x, y in vertices]))[:16]
    return f"{canvas_key}/wire:{digest}#{ordinal}"
```

Normalize `Definition` elements and their `parameter`/`port` declarations; normalize each `schematic` as a canvas owned by either the project or its enclosing definition; normalize `User` instances and nested `paramlist/param` values; normalize `Wire/vertex` geometry; represent `Control`, `Graph`, `Curve`, `channel`, `call`, signal labels, and buses through typed component/output/connection records when their schema fields are explicit. Use runtime `id`, `link`, `send`, and `recv` only in an in-memory lookup and reject dangling or ambiguous references. Count all other tags by bounded structural path and mark topology/parameter/connectivity locations as blocking.

- [ ] **Step 4: Verify focused extraction tests**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_extractor.py -q`

Expected: stable-key, graph-shape, unresolved-reference, collision, and warning tests pass.

- [ ] **Step 5: Commit graph normalization**

```powershell
git add pscad_mcp/builders/blueprint/corpus_models.py pscad_mcp/builders/blueprint/corpus_extractor.py tests/fixtures/blueprint_corpus tests/test_blueprint_corpus_extractor.py
git commit -m "feat: normalize PSCAD blueprint corpus graphs"
```

### Task 4: Canonical Records, Manifest, and Atomic Candidate Promotion

**Files:**
- Create: `pscad_mcp/builders/blueprint/corpus_writer.py`
- Create: `tests/test_blueprint_corpus_writer.py`

- [ ] **Step 1: Write failing deterministic record and manifest tests**

```python
def test_records_are_derived_in_stable_kind_and_key_order(tmp_path):
    graph = extract_fixture(tmp_path, "minimal.pscx")
    records = derive_records("moxing_v1", "pscad-xml-v1", graph)
    assert [record.kind for record in records] == [
        "project", "definition", "component", "parameter", "port", "connection", "project_setting", "output_channel"
    ]
    assert all(record.source_sha256 == graph.source_sha256 for record in records)
    assert canonical_jsonl(records) == canonical_jsonl(records)


def test_write_candidate_is_all_or_nothing(tmp_path, monkeypatch):
    destination = tmp_path / "corpus"
    destination.mkdir()
    (destination / "sentinel").write_text("old", encoding="ascii")
    failure = BackendError("CORPUS_MANIFEST_INVALID", "candidate rejected", "corpus", "validate_candidate")
    monkeypatch.setattr(corpus_writer, "validate_candidate", Mock(side_effect=failure))
    with pytest.raises(BackendError):
        write_corpus_candidate(spec, graphs, destination)
    assert (destination / "sentinel").read_text(encoding="ascii") == "old"
```

- [ ] **Step 2: Run writer tests and confirm RED**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_writer.py -q`

Expected: failures identify absent writer APIs.

- [ ] **Step 3: Implement canonical serialization and validation**

```python
def canonical_json(value: Any) -> bytes:
    return (json.dumps(json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def canonical_jsonl(records: Iterable[CorpusRecord]) -> bytes:
    return b"".join(canonical_json(record.to_dict()) for record in sorted(records, key=lambda item: (KIND_ORDER[item.kind], item.record_key)))


def write_corpus_candidate(spec: CorpusSpec, graphs: Sequence[ProjectGraph], destination: Path) -> CorpusManifest:
    sibling = Path(tempfile.mkdtemp(prefix=f".{destination.name}-candidate-", dir=destination.parent))
    try:
        write_all_artifacts(sibling, spec, graphs)
        manifest = validate_candidate(sibling, spec)
        promote_directory(sibling, destination)  # rename existing destination to a sibling backup, rename candidate into place, restore on failure.
        return manifest
    except Exception:
        remove_owned_candidate(sibling)
        raise
```

`validate_candidate` must reparse every graph/record/manifest, verify record counts and SHA-256 values, reject absolute-path patterns and denied field names, and compare two in-memory serializations for byte identity before promotion.

- [ ] **Step 4: Run writer tests and commit**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_writer.py -q`

Expected: canonicalization, manifest, privacy, drift, and rollback tests pass.

```powershell
git add pscad_mcp/builders/blueprint/corpus_writer.py tests/test_blueprint_corpus_writer.py
git commit -m "feat: write deterministic blueprint corpus artifacts"
```

### Task 5: No-Mutation Blueprint Candidates and Corpus Verification

**Files:**
- Create: `pscad_mcp/builders/blueprint/corpus_verifier.py`
- Create: `tests/test_blueprint_corpus_verifier.py`

- [ ] **Step 1: Write failing Blueprint generation and production-schema tests**

```python
def test_blueprint_candidate_is_read_only_empty_and_hash_bound(tmp_path):
    graph = extract_fixture(tmp_path, "minimal.pscx")
    value = generate_blueprint_candidate(spec_source("minimal"), graph)
    parsed = parse_blueprint(value)
    assert parsed.operations == ()
    assert parsed.source_package["handling_policy"] == "read_only"
    assert parsed.source_package["required"][0]["sha256"] == graph.source_sha256
    assert parsed.publication.delivery_package is False
    assert parsed.publication.scope == "evidence_only"


def test_blueprint_graph_signature_mismatch_fails_verification(tmp_path):
    blueprint = generate_blueprint_candidate(source, graph)
    blueprint["acceptance"]["required_structure"].pop()
    with pytest.raises(BackendError) as raised:
        verify_blueprint_candidate(blueprint, graph)
    assert raised.value.code == "CORPUS_BLUEPRINT_MISMATCH"
```

- [ ] **Step 2: Run verifier tests and confirm RED**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_verifier.py -q`

Expected: failures identify absent verifier APIs.

- [ ] **Step 3: Implement candidate generation and offline verification**

```python
def generate_blueprint_candidate(source: CorpusSource, graph: ProjectGraph) -> dict[str, Any]:
    return {
        "identity": {"schema_version": 1, "name": f"{source.project_id}-existing-v1", "supported_pscad_versions": list(source.pscad_versions), "inspection_profile": "corpus-existing-project-v1"},
        "source_package": {"entry_point": source.basename, "required": required_source_entries(source), "handling_policy": "read_only"},
        "operations": [],
        "acceptance": {"required_structure": graph.required_structure(), "required_parameters": graph.required_parameters(), "blocking_messages": ["error", "fatal"], "outputs": graph.required_outputs(), "rules": []},
        "publication": {"delivery_package": False, "evidence_files": ["plan.json", "validation-report.json", "manifest.json"], "scope": "evidence_only"},
    }


def verify_blueprint_candidate(value: Any, graph: ProjectGraph) -> BlueprintVerification:
    blueprint = parse_blueprint(value)
    if blueprint.operations or blueprint.source_package["handling_policy"] != "read_only":
        raise corpus_error("CORPUS_BLUEPRINT_UNSAFE", "Corpus Blueprint must be read-only and contain no operations.")
    compare_graph_contract(blueprint, graph)
    return BlueprintVerification(
        project_id=graph.project_id,
        blueprint_name=blueprint.identity.name,
        graph_signature=graph_signature(graph),
        source_hash_verified=True,
        operations_empty=True,
        status="verified",
    )
```

- [ ] **Step 4: Run verifier tests and commit**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_verifier.py -q`

Expected: production schema, empty-operation, graph-signature, and drift tests pass.

```powershell
git add pscad_mcp/builders/blueprint/corpus_verifier.py tests/test_blueprint_corpus_verifier.py
git commit -m "feat: verify corpus blueprint candidates"
```

### Task 6: Maintainer CLI and Source-Safe Workflow

**Files:**
- Create: `scripts/build_blueprint_corpus.py`
- Create: `tests/test_blueprint_corpus_cli.py`

- [ ] **Step 1: Write failing CLI contract tests**

```python
def test_cli_requires_explicit_source_and_output(tmp_path):
    result = run_cli([])
    assert result.returncode == 2
    assert "--source-root" in result.stderr
    assert "--output" in result.stderr


def test_cli_report_uses_project_ids_not_source_absolute_paths(tmp_path):
    result = run_cli(["generate", "--source-root", str(source_root), "--spec", str(spec), "--output", str(output)])
    assert result.returncode == 0
    assert str(source_root) not in result.stdout
    assert json.loads(result.stdout)["projects"] == ["minimal"]
```

- [ ] **Step 2: Run CLI tests and confirm RED**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_cli.py -q`

Expected: failure because the script is missing.

- [ ] **Step 3: Implement explicit subcommands**

```python
def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("generate", "verify", "compare"):
        command = sub.add_parser(name)
        command.add_argument("--source-root", type=Path, required=True)
        command.add_argument("--spec", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    result = run_command(args)
    print(json.dumps(result.public_summary(), sort_keys=True, ensure_ascii=True))
    return 0
```

`generate` writes only the proposed output; `verify` does not write; `compare` regenerates in a temporary directory and byte-compares with `--output`. No command writes under `--source-root`. Promotion into package assets remains a normal reviewed filesystem/Git action, not a CLI side effect.

- [ ] **Step 4: Run CLI tests and commit**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_cli.py -q`

Expected: all CLI boundary tests pass.

```powershell
git add scripts/build_blueprint_corpus.py tests/test_blueprint_corpus_cli.py
git commit -m "feat: add blueprint corpus maintainer workflow"
```

### Task 7: Generate and Review the Four Derived Corpus Assets

**Files:**
- Create: `pscad_mcp/assets/corpora/moxing_v1/manifest.json`
- Create: `pscad_mcp/assets/corpora/moxing_v1/graphs/*.json`
- Create: `pscad_mcp/assets/corpora/moxing_v1/records/*.jsonl`
- Create: `pscad_mcp/assets/blueprints/hvdc-bipolar-1000mw-500kv-existing-v1/blueprint.json`
- Create: `pscad_mcp/assets/blueprints/hvdc-bipolar-5ka-500kv-test-existing-v1/blueprint.json`
- Create: `pscad_mcp/assets/blueprints/hvdc-bipolar-5ka-500kv-trans-existing-v1/blueprint.json`
- Create: `pscad_mcp/assets/blueprints/ls800zhengque1226-existing-v1/blueprint.json`
- Create: `tests/test_blueprint_corpus_regression.py`

- [ ] **Step 1: Add the opt-in source regression test**

```python
pytestmark = pytest.mark.skipif(
    os.getenv("PSCAD_MCP_CORPUS_SOURCE") is None,
    reason="requires PSCAD_MCP_CORPUS_SOURCE for local read-only corpus regression",
)


def test_moxing_corpus_regenerates_byte_identically(tmp_path):
    source_root = Path(os.environ["PSCAD_MCP_CORPUS_SOURCE"]).resolve(strict=True)
    before = admitted_hashes(source_root, packaged_spec())
    generate_corpus(source_root, packaged_spec(), tmp_path / "generated")
    assert_tree_bytes_equal(tmp_path / "generated", packaged_corpus_root())
    assert admitted_hashes(source_root, packaged_spec()) == before
```

- [ ] **Step 2: Generate a proposed corpus outside the source root**

```powershell
$env:PSCAD_MCP_CORPUS_SOURCE = 'C:\Users\335\Desktop\moxing'
& .\.venv\Scripts\python.exe scripts\build_blueprint_corpus.py generate --source-root $env:PSCAD_MCP_CORPUS_SOURCE --spec pscad_mcp\assets\corpora\moxing_v1\source-spec.json --output .\.corpus-proposed\moxing_v1
```

Expected: four graphs and four JSONL files are generated; source pre/post hashes match; no `.pscx`, `.psmx`, `.bakx`, `.gf46`, absolute path, creator, or revisor content appears in proposed output.

- [ ] **Step 3: Inspect warnings and resolve only schema-backed blocking gaps**

Run:

```powershell
& .\.venv\Scripts\python.exe scripts\build_blueprint_corpus.py verify --source-root $env:PSCAD_MCP_CORPUS_SOURCE --spec pscad_mcp\assets\corpora\moxing_v1\source-spec.json --output .\.corpus-proposed\moxing_v1
rg -n -i 'creator|revisor|[A-Z]:\\|\\\\Users\\|\.pscx|\.bakx|\.gf46' .\.corpus-proposed\moxing_v1
```

Expected: verification passes and `rg` finds no denied metadata or paths. The `.psmx` remains excluded because the admitted PSCX does not reference it.

- [ ] **Step 4: Promote reviewed derived artifacts and Blueprint candidates**

Copy only validated `.json`/`.jsonl` files from the proposed directory into the package asset paths listed above. Reparse all four Blueprint candidates with `parse_blueprint`, require empty operations, and run source audits against the explicit root.

- [ ] **Step 5: Run local regression twice and commit**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_regression.py -q
& .\.venv\Scripts\python.exe scripts\build_blueprint_corpus.py compare --source-root $env:PSCAD_MCP_CORPUS_SOURCE --spec pscad_mcp\assets\corpora\moxing_v1\source-spec.json --output pscad_mcp\assets\corpora\moxing_v1
```

Expected: byte-identical regeneration and unchanged source hashes on both runs.

```powershell
git add pscad_mcp/assets/corpora/moxing_v1 pscad_mcp/assets/blueprints tests/test_blueprint_corpus_regression.py
git commit -m "data: add normalized PSCAD blueprint corpus"
```

### Task 8: Optional Read-Only Live Inventory Verification

**Files:**
- Modify: `pscad_mcp/builders/blueprint/corpus_verifier.py`
- Create: `tests/test_blueprint_corpus_live.py`

- [ ] **Step 1: Write fake-service comparison tests**

```python
@pytest.mark.asyncio
async def test_live_verification_agrees_without_mutating_graph():
    before = canonical_json(graph.to_dict())
    result = await verify_live_inventory(graph, MatchingInspectionService())
    assert result.live_verified is True
    assert all(check.status == "matched" for check in result.checks)
    assert canonical_json(graph.to_dict()) == before


@pytest.mark.asyncio
async def test_live_mismatch_is_explicit_and_never_rewrites_offline_graph():
    result = await verify_live_inventory(graph, MismatchedInspectionService())
    assert result.live_verified is False
    assert result.status == "failed"
    assert result.checks[0].status == "mismatched"
```

- [ ] **Step 2: Implement comparison against `read_live_inventory`**

```python
async def verify_live_inventory(graph: ProjectGraph, service: Any, project_name: str) -> LiveVerification:
    service_status = await service.status()
    snapshot = await read_live_inventory(service, project_name, "corpus-existing-project-v1")
    checks = compare_offline_and_live(graph, snapshot)
    return LiveVerification(
        project_id=graph.project_id,
        source_sha256=graph.source_sha256,
        backend=str(service_status["backend"]),
        pscad_version=snapshot.pscad_version,
        status="verified" if all(item.status == "matched" for item in checks) else "failed",
        live_verified=all(item.status == "matched" for item in checks),
        checks=checks,
    )
```

Compare project/canvas discovery, definition identity, component counts and selector uniqueness, parameters/units, ports, and outputs. Never call save, compile, run, build, publish, or any mutation API.

- [ ] **Step 3: Add opt-in licensed test and verify default skip**

`tests/test_blueprint_corpus_live.py` must require `PSCAD_MCP_CORPUS_LIVE=1`, `PSCAD_MCP_CORPUS_SOURCE`, `PSCAD_MCP_WORKSPACE`, and an explicit PSCAD version. The default run must skip and must never interpret a skip as verification.

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_live.py -q`

Expected: skipped when opt-in variables are absent; fake-service unit tests pass.

- [ ] **Step 4: Commit live verification**

```powershell
git add pscad_mcp/builders/blueprint/corpus_verifier.py tests/test_blueprint_corpus_live.py
git commit -m "feat: verify blueprint corpus against live inventory"
```

### Task 9: Packaging, Documentation, and Full Verification

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/test_packaging_metadata.py`
- Modify: `tests/test_install_smoke.py`
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add failing package-data and installed-resource tests**

```python
def test_project_packages_blueprint_corpus_assets():
    patterns = package_data_patterns()
    assert "assets/corpora/*/*.json" in patterns
    assert "assets/corpora/*/graphs/*.json" in patterns
    assert "assets/corpora/*/records/*.jsonl" in patterns


def test_packaged_corpus_manifest_and_blueprints_load():
    manifest = load_packaged_corpus_manifest("moxing_v1")
    assert manifest.project_count == 4
    assert all(not blueprint.operations for blueprint in load_corpus_blueprints(manifest))
```

- [ ] **Step 2: Update package metadata**

Add exactly these `pscad_mcp` package-data patterns:

```toml
"assets/corpora/*/*.json",
"assets/corpora/*/graphs/*.json",
"assets/corpora/*/records/*.jsonl",
```

- [ ] **Step 3: Document the maintainer workflow and safety boundary**

README sections must show the explicit `generate`, `verify`, and `compare` commands; state that original models/results are never committed; identify the corpus as deterministic derived data; state that live verification is optional and read-only; and explicitly separate it from `pscad_mcp.learning`. Chinese documentation must preserve the same claims. CHANGELOG must report `implemented` and `test_verified` only after the corresponding checks pass, and `live_verified=false` unless the licensed test is actually run.

- [ ] **Step 4: Run focused and full verification**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_blueprint_corpus_schema.py tests/test_blueprint_corpus_extractor.py tests/test_blueprint_corpus_writer.py tests/test_blueprint_corpus_verifier.py tests/test_blueprint_corpus_cli.py tests/test_blueprint_corpus_regression.py tests/test_blueprint_corpus_live.py tests/test_packaging_metadata.py -q
& .\.venv\Scripts\python.exe -m unittest discover tests -v
& .\.venv\Scripts\python.exe -m compileall -q pscad_mcp tests scripts
& .\.venv\Scripts\python.exe -m pip check
git diff --check main...HEAD
```

Expected: all offline tests pass; opt-in licensed tests skip unless configured; compile, dependency, and whitespace checks exit zero.

- [ ] **Step 5: Build and inspect a wheel**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pip wheel --no-deps --wheel-dir .\.dist-verify .
$env:PSCAD_MCP_SMOKE_WHEEL = (Get-ChildItem .\.dist-verify\pscad_mcp-*.whl | Select-Object -First 1).FullName
& .\.venv\Scripts\python.exe -m pytest tests/test_install_smoke.py -q
```

Expected: the isolated wheel smoke test loads the manifest, four graphs, four record files, and four Blueprint assets without source-tree access.

- [ ] **Step 6: Commit documentation and packaging**

```powershell
git add pyproject.toml tests/test_packaging_metadata.py tests/test_install_smoke.py README.md docs/zh-CN/README.md CHANGELOG.md
git commit -m "docs: document PSCAD blueprint corpus workflow"
```

- [ ] **Step 7: Final branch review**

Run:

```powershell
git status --short --branch
git log --oneline --decorate main..HEAD
git diff --stat main...HEAD
```

Expected: clean `codex/pscad-blueprint-builder`; the original four source hashes still equal the values in Task 1; no original PSCAD model or simulation artifact appears in Git.
