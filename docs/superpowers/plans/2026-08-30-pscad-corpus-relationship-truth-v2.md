# PSCAD Corpus Relationship Truth v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the offline PSCAD Blueprint corpus to schema v2 with hash-bound definition catalogs, hierarchy-safe instance relationships, canonical confirmed nets, and explicit candidate/unresolved evidence while preserving schema v1 read compatibility.

**Architecture:** Keep the current bounded corpus extractor as the raw evidence stage, add a versioned definition catalog and safe conditional-port evaluator, expand reusable hierarchy templates into stable occurrences, and pass those occurrences through the existing canonical topology engine. Persist raw evidence and derived occurrence/net/membership records separately; v1 readers retain v1 semantics and v2 generation remains atomic and read-only.

**Tech Stack:** Python 3.10+, standard-library XML/JSON/hash/path APIs, immutable dataclasses, existing `pscad_mcp.topology` models/connectivity/inference, pytest, Ruff, PowerShell verification scripts.

---

## Source Specification

Implement against the approved design:

- `docs/superpowers/specs/2026-08-30-pscad-corpus-relationship-truth-v2-design.md`

Do not broaden R1 into MCP query tools, Legacy/Modern backend optimization,
licensed acceptance, or silent-learning candidate remediation.

## Execution Prerequisites

1. Execute in an isolated `codex/` worktree created at execution time.
2. Start from a clean commit after concurrent LCC work has been integrated or
   intentionally excluded.
3. Do not start PSCAD. R1 is offline-only.
4. The four admitted PSCX sources currently exist under
   `C:\Users\335\Desktop\moxing`.
5. The local 4.6.2 Master source currently exists at
   `C:\Program Files (x86)\PSCAD46\master.pslx`, byte length `6742894`, SHA-256
   `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939`.
6. Formal four-project migration additionally requires reviewed, hash-bound
   sources for `master@4.6.3` and `vsc-mmc-lib@4.6.2`. They are not currently
   available in the inspected workspace. Task 12 must stop with
   `needs_evidence` if either remains unavailable; it must not substitute the
   4.6.2 Master for 4.6.3 or promote partial v2 assets.

## Planning Clarifications

The existing corpus stores reusable canvas templates while canonical topology
uses hierarchy occurrences. The admitted projects invoke some definitions up
to six times. R1 therefore needs derived occurrence records so repeated child
definitions cannot share one confirmed net accidentally. These records are a
mechanical consequence of the approved instance-port and hierarchy design:

- `CorpusComponentOccurrence`
- `CorpusConductorOccurrence`
- `CorpusLabelOccurrence`

Schema v2 raw `CorpusConnection` records also gain a `namespace` field. Without
it, electrical and data conductors cannot be projected safely. Schema v1 bytes
and parsing remain unchanged.

PSCX provider keys contain runtime object IDs, while corpus keys intentionally
do not. Canonical parity therefore means exact net membership after a
deterministic structural-identity projection based on hierarchy path,
definition, location, orientation, port name/occurrence, conductor geometry,
label name, namespace, and scope. Tests must never compare an unnormalized
runtime-ID hash to a corpus hash or persist the runtime IDs.

## File Responsibility Map

| File | Responsibility after R1 |
| --- | --- |
| `pscad_mcp/builders/blueprint/corpus_models.py` | Shared v1/v2 spec, graph, manifest, and record containers |
| `pscad_mcp/builders/blueprint/corpus_relation_models.py` | Focused immutable v2 definition, occurrence, port, net, membership, hierarchy, candidate, and unresolved records |
| `pscad_mcp/builders/blueprint/corpus_schema.py` | Strict source-spec v1/v2 dispatch and portable definition-source validation |
| `pscad_mcp/builders/blueprint/corpus_conditions.py` | Closed conditional-port tokenizer, parser, and evaluator |
| `pscad_mcp/builders/blueprint/definition_catalog.py` | Hash/version-bound definition loading, exact lookup, classification, and post-read integrity |
| `pscad_mcp/builders/blueprint/corpus_extractor.py` | Raw bounded PSCX extraction plus v2 port/connection evidence |
| `pscad_mcp/builders/blueprint/corpus_relations.py` | Hierarchy occurrence expansion, topology projection, canonical connectivity, and relation projection |
| `pscad_mcp/builders/blueprint/corpus_writer.py` | Record derivation, canonical writing, v1/v2 dispatch, manifest validation, and atomic promotion |
| `pscad_mcp/builders/blueprint/corpus_verifier.py` | Blueprint v2 contracts, relation drift checks, and source immutability checks |
| `pscad_mcp/builders/blueprint/corpus_assets.py` | Packaged v1/v2 corpus loading and cross-hash verification |
| `scripts/build_blueprint_corpus.py` | Versioned definition-source CLI, preflight, proposal, generation, verify, and compare commands |

## Test Helper Contract

Test snippets below use small test-only arrangement helpers. Define each helper
in the test module that first uses it; do not add production APIs for test
convenience.

- `arrange_definition_source(tmp_path, fixture, version)` copies the named PSLX,
  computes real length/hash, and returns `(CorpusDefinitionSource, absolute Path)`.
- `arrange_catalog_mutation(tmp_path, mutation)` starts from `master-462.pslx`;
  it changes the admitted digest for `wrong_hash`, changes declared version for
  `wrong_version`, or inserts a second exact `gain` Definition for
  `duplicate_definition`.
- `arrange_v2_source(tmp_path, fixture)` copies the PSCX, records its original
  bytes, and returns `(CorpusSource, Path)` using the XML's exact version.
- `extract_v2_fixture(tmp_path, fixture)` calls `arrange_v2_source()` and then
  `extract_project(..., schema_version=2, normalization_profile="pscad-xml-v2")`.
- `graph_with_hierarchy_cycle(tmp_path)` and
  `graph_with_missing_child(tmp_path)` derive from the repeated-module graph by
  changing only hierarchy connection endpoints.
- `relation_graph()` returns the complete two-component v2 graph enumerated in
  Task 4 Step 1; expose it as a pytest fixture in modules that need it.
- `arrange_relation_graph_and_catalog()` combines `relation_graph()` with the
  admitted `master-462.pslx` catalog. `arrange_damaged_relation_input()` applies
  only the named damage from Task 7's parameter table.
- `arrange_topology_fixture()` parses one repository topology fixture with
  `xml.etree.ElementTree`, adds `Target="EMTDC"` to the test-only copy when the
  fixture omits it, writes that copy, creates exact source/spec/catalog
  bindings, and returns all four values named in the parity test.
  `arrange_nearby_dangling_fixture()` does the same for a fixture whose
  conductor endpoint is one grid step from a compatible port.
- `v2_spec`, `v2_source`, and `v2_manifest_value` pytest fixtures are built from
  the Task 1 definition-source contract and Task 4 relation graph. The manifest
  fixture uses `"c" * 64` as its confirmed relation signature because it tests
  parsing, not generation.
- CLI `arrange_v2_cli_input()` and `arrange_complete_v2_cli_args()` extend the
  existing `arrange_source()` helper with fixture definition sources and
  repeated `--definition-source` arguments.

Every helper must use actual fixture bytes, finite values, and Path objects.
None may place an absolute path in expected serialized output or error details.

## Task 1: Add Versioned Source-Spec Parsing Without Breaking v1

**Files:**

- Modify: `pscad_mcp/builders/blueprint/corpus_models.py:13-66`
- Modify: `pscad_mcp/builders/blueprint/corpus_schema.py:1-134`
- Create: `tests/fixtures/blueprint_corpus/v1_compat/source-spec.json`
- Modify: `tests/test_blueprint_corpus_schema.py`

- [ ] **Step 1: Freeze one v1 source-spec fixture**

Create `tests/fixtures/blueprint_corpus/v1_compat/source-spec.json` with this
exact canonical content:

```json
{"entry_points":[{"basename":"minimal.pscx","byte_length":1,"dependencies":[],"project_id":"minimal","pscad_versions":["4.6.2"],"sha256":"0000000000000000000000000000000000000000000000000000000000000000"}],"exclusion_policy":"no-backups-builds-results-v1","inclusion_policy":"explicit-entry-points-v1","name":"fixture_v1","normalization_profile":"pscad-xml-v1","schema_version":1}
```

- [ ] **Step 2: Write failing v2 and passing v1 parser tests**

Append to `tests/test_blueprint_corpus_schema.py`:

```python
def test_parse_v2_spec_binds_definition_sources_by_namespace_and_version():
    value = {
        "schema_version": 2,
        "normalization_profile": "pscad-xml-v2",
        "name": "fixture_v2",
        "inclusion_policy": "explicit-entry-points-v1",
        "exclusion_policy": "no-backups-builds-results-v1",
        "definition_sources": [
            {
                "namespace": "master",
                "basename": "master.pslx",
                "byte_length": 12,
                "sha256": "a" * 64,
                "pscad_versions": ["4.6.2"],
                "policy": "ports-and-classification-v1",
            }
        ],
        "entry_points": [
            {
                "project_id": "minimal",
                "basename": "minimal.pscx",
                "byte_length": 1,
                "sha256": "b" * 64,
                "pscad_versions": ["4.6.2"],
                "dependencies": [],
            }
        ],
    }

    parsed = parse_corpus_spec(value)

    assert parsed.schema_version == 2
    assert parsed.normalization_profile == "pscad-xml-v2"
    assert parsed.definition_sources[0].keys == (("master", "4.6.2"),)
    assert parsed.to_dict() == value


def test_frozen_v1_spec_keeps_v1_shape():
    path = FIXTURES / "v1_compat" / "source-spec.json"
    value = json.loads(path.read_text(encoding="ascii"))

    parsed = parse_corpus_spec(value)

    assert parsed.schema_version == 1
    assert parsed.definition_sources == ()
    assert parsed.to_dict() == value
```

- [ ] **Step 3: Run the v2 test and observe the failure**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_schema.py::test_parse_v2_spec_binds_definition_sources_by_namespace_and_version -v
```

Expected: FAIL with `CORPUS_SPEC_UNSUPPORTED` because only schema v1 is
accepted.

- [ ] **Step 4: Add the immutable definition-source contract**

Add to `corpus_models.py`:

```python
@dataclass(frozen=True)
class CorpusDefinitionSource:
    namespace: str
    basename: str
    byte_length: int
    sha256: str
    pscad_versions: tuple[str, ...]
    policy: str

    @property
    def keys(self) -> tuple[tuple[str, str], ...]:
        return tuple((self.namespace, version) for version in self.pscad_versions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "basename": self.basename,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "pscad_versions": list(self.pscad_versions),
            "policy": self.policy,
        }
```

Extend `CorpusSpec` with
`definition_sources: tuple[CorpusDefinitionSource, ...] = ()`. Its `to_dict()`
must include `definition_sources` only for schema v2 so v1 bytes remain stable.

- [ ] **Step 5: Dispatch strict v1 and v2 shapes**

Refactor `parse_corpus_spec()` into exact schema branches:

```python
_SPEC_V1_FIELDS = {
    "schema_version", "normalization_profile", "name",
    "inclusion_policy", "exclusion_policy", "entry_points",
}
_SPEC_V2_FIELDS = _SPEC_V1_FIELDS | {"definition_sources"}
_DEFINITION_POLICY = "ports-and-classification-v1"


def _definition_source(value: Any, index: int) -> CorpusDefinitionSource:
    path = f"corpus_spec.definition_sources[{index}]"
    record = _exact(
        value,
        {"namespace", "basename", "byte_length", "sha256", "pscad_versions", "policy"},
        path,
    )
    policy = _portable_name(record["policy"], f"{path}.policy")
    if policy != _DEFINITION_POLICY:
        raise _error("CORPUS_SPEC_INVALID", "Definition-source policy is unsupported.", f"{path}.policy")
    return CorpusDefinitionSource(
        namespace=_portable_name(record["namespace"], f"{path}.namespace"),
        basename=_basename(record["basename"], f"{path}.basename", {".pscx", ".pslx"}),
        byte_length=_positive_int(record["byte_length"], f"{path}.byte_length"),
        sha256=_sha256(record["sha256"], f"{path}.sha256"),
        pscad_versions=_versions(record["pscad_versions"], f"{path}.pscad_versions"),
        policy=policy,
    )
```

Reject duplicate `(namespace, version)` keys and require
`normalization_profile == "pscad-xml-v2"` for schema v2. Preserve the existing
schema v1 parser and error contracts.

- [ ] **Step 6: Run schema tests**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_schema.py -q
```

Expected: PASS with no failures.

- [ ] **Step 7: Commit**

```powershell
git add pscad_mcp/builders/blueprint/corpus_models.py
git add pscad_mcp/builders/blueprint/corpus_schema.py
git add tests/fixtures/blueprint_corpus/v1_compat/source-spec.json
git add tests/test_blueprint_corpus_schema.py
git commit -m "feat: add corpus v2 source specification"
```

## Task 2: Build the Hash- and Version-Bound Definition Catalog

**Files:**

- Create: `pscad_mcp/builders/blueprint/definition_catalog.py`
- Modify: `pscad_mcp/core/definition_metadata.py:26-245`
- Create: `tests/fixtures/blueprint_corpus/master-462.pslx`
- Create: `tests/fixtures/blueprint_corpus/master-463.pslx`
- Create: `tests/test_blueprint_definition_catalog.py`

- [ ] **Step 1: Create minimal definition-source fixtures**

Both fixtures use this structure; `master-463.pslx` changes `version` to
`4.6.3` and definition name to `gain463`:

```xml
<project name="master" version="4.6.2">
  <definitions>
    <Definition name="gain" classid="UserCmpDefn">
      <form><parameter name="View" type="Integer"><value>0</value></parameter></form>
      <svg>
        <port name="IN" x="-18" y="0" dim="1" model="Transfer">true</port>
        <port name="OUT" x="18" y="0" dim="1" model="Transfer">View==0</port>
      </svg>
    </Definition>
    <Definition name="annotation" classid="UserCmpDefn"><svg /></Definition>
  </definitions>
</project>
```

- [ ] **Step 2: Write catalog loading and privacy tests**

Create `tests/test_blueprint_definition_catalog.py`:

```python
def test_catalog_selects_exact_namespace_and_version(tmp_path):
    source, binding = arrange_definition_source(tmp_path, "master-462.pslx", "4.6.2")

    catalog = load_definition_catalog((source,), {source.keys[0]: binding})

    definition = catalog.require("master", "4.6.2", "gain")
    assert definition.source_sha256 == source.sha256
    assert [port.name for port in definition.metadata.ports] == ["IN", "OUT"]
    assert catalog.source_read_counts == (("master", "4.6.2", 1),)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("wrong_hash", "CORPUS_DEFINITION_SOURCE_MISMATCH"),
        ("wrong_version", "CORPUS_DEFINITION_SOURCE_MISMATCH"),
        ("duplicate_definition", "CORPUS_DEFINITION_AMBIGUOUS"),
    ],
)
def test_catalog_fails_closed_without_leaking_absolute_paths(tmp_path, mutation, code):
    source, binding = arrange_catalog_mutation(tmp_path, mutation)

    with pytest.raises(BackendError) as raised:
        catalog = load_definition_catalog((source,), {source.keys[0]: binding})
        if mutation == "duplicate_definition":
            catalog.require("master", "4.6.2", "gain")

    assert raised.value.code == code
    assert str(tmp_path) not in str(raised.value.details)
```

Use test helpers that copy the fixture, calculate its real byte length/hash,
and create `CorpusDefinitionSource`; do not hard-code temporary paths in
expected details.

- [ ] **Step 3: Run the catalog test and observe the import failure**

Run:

```powershell
python -m pytest tests/test_blueprint_definition_catalog.py -v
```

Expected: collection ERROR because `definition_catalog` does not exist.

- [ ] **Step 4: Implement immutable catalog loading**

First add a single-parse wrapper to `definition_metadata.py` while preserving
the existing public dictionary helper:

```python
@dataclass(frozen=True)
class DefinitionMetadataSource:
    name: str
    version: str
    definitions: dict[str, tuple[DefinitionMetadata, ...]]


def parse_definition_metadata_source(payload: bytes) -> DefinitionMetadataSource:
    root = ET.fromstring(payload)
    grouped: dict[str, list[DefinitionMetadata]] = {}
    for definition in root.findall(".//Definition"):
        name = definition.get("name")
        if name:
            grouped.setdefault(name, []).append(_metadata_from_definition(definition))
    return DefinitionMetadataSource(
        name=str(root.get("name", "")),
        version=str(root.get("version", "")),
        definitions={name: tuple(values) for name, values in grouped.items()},
    )


def read_definition_metadata_document(payload: bytes) -> dict[str, tuple[DefinitionMetadata, ...]]:
    return parse_definition_metadata_source(payload).definitions
```

Create these public types and APIs:

```python
def _catalog_error(
    code: str,
    message: str,
    namespace: str | None = None,
    version: str | None = None,
    definition: str | None = None,
) -> BackendError:
    details = {
        key: value
        for key, value in {
            "namespace": namespace,
            "pscad_version": version,
            "definition": definition,
        }.items()
        if value is not None
    }
    return BackendError(code, message, "corpus", "definition_catalog", details)


@dataclass(frozen=True)
class CatalogDefinition:
    namespace: str
    pscad_version: str
    physical_name: str
    source_sha256: str
    metadata: DefinitionMetadata


@dataclass(frozen=True)
class DefinitionCatalog:
    definitions: Mapping[tuple[str, str, str], tuple[CatalogDefinition, ...]]
    source_fingerprints: tuple[tuple[str, str, str], ...]
    source_read_counts: tuple[tuple[str, str, int], ...]
    catalog_signature: str
    _bindings: Mapping[tuple[str, str], Path] = field(compare=False, repr=False)
    _integrity_sources: tuple[tuple[Path, str], ...] = field(compare=False, repr=False)

    def require(self, namespace: str, version: str, name: str) -> CatalogDefinition:
        matches = self.definitions.get((namespace, version, name), ())
        if not matches:
            raise _catalog_error("CORPUS_DEFINITION_UNRESOLVED", "Exact definition is absent.", namespace, version, name)
        if len(matches) != 1:
            raise _catalog_error("CORPUS_DEFINITION_AMBIGUOUS", "Exact definition is duplicated.", namespace, version, name)
        return matches[0]

    def verify_unchanged(self) -> None:
        for path, expected in self._integrity_sources:
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise _catalog_error(
                    "CORPUS_DEFINITION_SOURCE_MISMATCH",
                    "Definition source changed during generation.",
                )


def load_definition_catalog(
    sources: Sequence[CorpusDefinitionSource],
    bindings: Mapping[tuple[str, str], Path],
) -> DefinitionCatalog:
    expected = {key for source in sources for key in source.keys}
    if set(bindings) != expected:
        raise _catalog_error(
            "CORPUS_DEFINITION_SOURCE_MISMATCH",
            "Definition-source bindings do not match the specification.",
        )
    definitions: dict[tuple[str, str, str], tuple[CatalogDefinition, ...]] = {}
    fingerprints = []
    normalized_bindings = {}
    integrity_sources = []
    for source in sources:
        source_paths = {Path(bindings[key]).resolve() for key in source.keys}
        if len(source_paths) != 1:
            raise _catalog_error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "One definition declaration must resolve to one file.",
                source.namespace,
            )
        path = source_paths.pop()
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise _catalog_error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition source is missing or unsafe.",
                source.namespace,
            )
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if len(payload) != source.byte_length or digest != source.sha256:
            raise _catalog_error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition source does not match its admitted bytes.",
                source.namespace,
            )
        parsed = parse_definition_metadata_source(payload)
        if parsed.version not in source.pscad_versions:
            raise _catalog_error(
                "CORPUS_DEFINITION_SOURCE_MISMATCH",
                "Definition source PSCAD version is not admitted.",
                source.namespace,
            )
        for namespace, version in source.keys:
            for name, matches in parsed.definitions.items():
                definitions[(namespace, version, name)] = tuple(
                    CatalogDefinition(namespace, version, name, digest, metadata)
                    for metadata in matches
                )
            fingerprints.append((namespace, version, digest))
            normalized_bindings[(namespace, version)] = path
        integrity_sources.append((path, digest))
    return DefinitionCatalog(
        definitions=MappingProxyType(definitions),
        source_fingerprints=tuple(sorted(fingerprints)),
        source_read_counts=tuple(
            (namespace, version, 1) for namespace, version in sorted(expected)
        ),
        catalog_signature=canonical_sha256(tuple(sorted(fingerprints))),
        _bindings=MappingProxyType(normalized_bindings),
        _integrity_sources=tuple(integrity_sources),
    )
```

The function body must perform these exact operations for every source:

1. require one absolute, existing, regular, non-symlink binding;
2. read bytes once;
3. verify byte length and SHA-256;
4. parse `parse_definition_metadata_source(payload)` once;
5. require root/source version compatibility from the XML identity;
6. index every exact definition name without collapsing duplicates; and
7. store only namespace/version/name/hash in public errors.

- [ ] **Step 5: Run catalog and definition-metadata tests**

Run:

```powershell
python -m pytest tests/test_blueprint_definition_catalog.py tests/test_definition_metadata.py -q
```

Expected: PASS with no failures.

- [ ] **Step 6: Commit**

```powershell
git add pscad_mcp/builders/blueprint/definition_catalog.py
git add pscad_mcp/core/definition_metadata.py
git add tests/fixtures/blueprint_corpus/master-462.pslx
git add tests/fixtures/blueprint_corpus/master-463.pslx
git add tests/test_blueprint_definition_catalog.py
git commit -m "feat: add hash-bound corpus definition catalog"
```

## Task 3: Implement the Closed Conditional-Port Evaluator

**Files:**

- Create: `pscad_mcp/builders/blueprint/corpus_conditions.py`
- Create: `tests/test_blueprint_corpus_conditions.py`

- [ ] **Step 1: Write expression behavior tests**

Create `tests/test_blueprint_corpus_conditions.py`:

```python
@pytest.mark.parametrize(
    ("expression", "instance", "defaults", "expected"),
    [
        ("true", {}, {}, True),
        ("false", {}, {}, False),
        ("View==0", {"View": "0"}, {}, True),
        ("!(DPath==1)", {"DPath": "0"}, {}, True),
        ("(Size==2) && ((Type==4)||(Type==6))", {"Size": "2", "Type": "6"}, {}, True),
        ("MeasV+MeasP+MeasQ==0", {"MeasV": "0", "MeasP": "0", "MeasQ": "0"}, {}, True),
        ("View==1", {}, {"View": 1}, True),
        ("DPath", {"DPath": "2"}, {}, True),
    ],
)
def test_evaluate_condition_uses_closed_precedence(expression, instance, defaults, expected):
    assert evaluate_condition(expression, instance, defaults) is expected


@pytest.mark.parametrize(
    "expression",
    ["A-1", "A*2", "A/2", "func(A)", "A[0]", "A=1", "A<B"],
)
def test_evaluate_condition_rejects_operators_outside_the_contract(expression):
    with pytest.raises(ConditionUnresolved):
        evaluate_condition(expression, {"A": "1", "B": "2"}, {})


def test_evaluate_condition_rejects_missing_duplicate_nonfinite_and_string_values():
    with pytest.raises(ConditionUnresolved):
        evaluate_condition("Missing==1", {}, {})
    with pytest.raises(ConditionUnresolved):
        evaluate_condition("A==1", {"A": ("1", "2")}, {})
    with pytest.raises(ConditionUnresolved):
        evaluate_condition("A>1", {"A": "nan"}, {})
    with pytest.raises(ConditionUnresolved):
        evaluate_condition("A==1", {"A": "closed"}, {})
```

- [ ] **Step 2: Run and observe the missing-module failure**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_conditions.py -v
```

Expected: collection ERROR because `corpus_conditions` does not exist.

- [ ] **Step 3: Implement tokenizer and recursive-descent parser**

Use this exact token contract:

```python
_TOKEN = re.compile(
    r"\s*(?:(?P<op>&&|\|\||==|!=|>|[!+()])|"
    r"(?P<identifier>[A-Za-z_][A-Za-z0-9_]*)|"
    r"(?P<number>[0-9]+(?:\.[0-9]+)?))"
)


class ConditionUnresolved(ValueError):
    pass


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str


def _tokens(expression: str) -> tuple[_Token, ...]:
    result = []
    position = 0
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        if match is None or match.end() == position:
            raise ConditionUnresolved("unsupported conditional-port syntax")
        kind = "op" if match.group("op") else "identifier" if match.group("identifier") else "number"
        result.append(_Token(kind, match.group(kind)))
        position = match.end()
    return tuple(result)
```

Implement `_Parser` with methods `parse_or`, `parse_and`, `parse_comparison`,
`parse_addition`, `parse_unary`, and `parse_primary` in that precedence order.
Reject chained comparisons by permitting at most one comparison operator in
`parse_comparison`. Resolve identifiers case-sensitively from instance values
first and definition defaults second. Convert finite numeric strings with
`decimal.Decimal`, preserve booleans, and implement the Boolean/numeric rules
from design section 8. Do not call `eval`, `ast.parse`, a shell, or a vendor
macro engine.

Expose only:

```python
def evaluate_condition(
    expression: str | None,
    instance_values: Mapping[str, object],
    definition_defaults: Mapping[str, object],
) -> bool:
    if expression is None or not expression.strip():
        return True
    parser = _Parser(_tokens(expression.strip()), instance_values, definition_defaults)
    result = parser.parse_or()
    parser.require_end()
    return parser.as_boolean(result)
```

- [ ] **Step 4: Run condition tests**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_conditions.py -q
```

Expected: PASS with no failures.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/builders/blueprint/corpus_conditions.py
git add tests/test_blueprint_corpus_conditions.py
git commit -m "feat: evaluate corpus conditional ports safely"
```

## Task 4: Add Immutable Schema v2 Relation and Occurrence Records

**Files:**

- Create: `pscad_mcp/builders/blueprint/corpus_relation_models.py`
- Modify: `pscad_mcp/builders/blueprint/corpus_models.py:90-375`
- Modify: `pscad_mcp/builders/blueprint/corpus_writer.py:337-585`
- Create: `tests/test_blueprint_corpus_v2_models.py`

- [ ] **Step 1: Write v2 graph round-trip tests**

Create a `relation_graph()` fixture containing two component occurrences, two
ports, one conductor occurrence, one confirmed net, two memberships, one
hierarchy relation, one candidate, and one engineering unresolved record.
Then add:

```python
def test_v2_graph_round_trips_every_relation_record():
    graph = relation_graph()

    reparsed = parse_project_graph(graph.to_dict())

    assert reparsed == graph
    assert reparsed.schema_version == 2
    assert reparsed.confirmed_nets[0].port_keys == (
        "occurrence:left/port:out#0",
        "occurrence:right/port:in#0",
    )


def test_v1_graph_round_trip_omits_v2_fields(v1_graph):
    value = v1_graph.to_dict()

    reparsed = parse_project_graph(value)

    assert "schema_version" not in value
    assert reparsed.schema_version == 1
    assert reparsed.component_occurrences == ()
    assert reparsed.to_dict() == value
```

- [ ] **Step 2: Run and observe missing relation types**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_v2_models.py -v
```

Expected: collection ERROR because `corpus_relation_models` does not exist.

- [ ] **Step 3: Define the v2 relation records**

Create frozen dataclasses with exact `to_dict()` field names:

```python
@dataclass(frozen=True)
class CorpusDefinitionClassification:
    key: str
    namespace: str
    pscad_version: str
    physical_name: str
    classification: str
    port_contract_keys: tuple[str, ...]
    source_sha256: str


@dataclass(frozen=True)
class CorpusComponentOccurrence:
    key: str
    source_component_key: str
    canvas_key: str
    source_canvas_key: str
    definition_key: str
    hierarchy_path: tuple[str, ...]
    name: str
    location: tuple[int, int]
    orientation: int
    parameters: FrozenDict


@dataclass(frozen=True)
class CorpusConductorOccurrence:
    key: str
    source_connection_key: str
    canvas_key: str
    kind: str
    namespace: str
    vertices: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class CorpusLabelOccurrence:
    key: str
    source_component_key: str
    canvas_key: str
    name: str
    namespace: str
    scope: str
    location: tuple[int, int]


@dataclass(frozen=True)
class CorpusInstancePort:
    key: str
    component_key: str
    source_component_key: str
    definition_port_key: str
    name: str
    occurrence: int
    relative: tuple[int, int]
    absolute: tuple[int, int]
    namespace: str
    dimension: int | None
    active: bool
    source_sha256: str


@dataclass(frozen=True)
class CorpusConfirmedNet:
    key: str
    namespace: str
    port_keys: tuple[str, ...]
    conductor_keys: tuple[str, ...]
    label_keys: tuple[str, ...]
    junctions: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class CorpusPortNetMembership:
    key: str
    component_key: str
    port_key: str
    net_key: str
    namespace: str


@dataclass(frozen=True)
class CorpusHierarchyRelation:
    key: str
    parent_component_key: str
    child_canvas_key: str
    outer_port_key: str
    inner_port_key: str
    namespace: str
    dimension: int | None


@dataclass(frozen=True)
class CorpusCandidateEdge:
    left: str
    right: str
    confidence: float
    reasons: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    status: str = "candidate_only"


@dataclass(frozen=True)
class CorpusUnresolvedEvidence:
    code: str
    object_keys: tuple[str, ...]
    evidence: tuple[str, ...]
    classification: str
```

Every `to_dict()` must emit lists for tuple collections and finite JSON-safe
values. Validate classification/status enums in the strict codec, not in
dataclass `__post_init__`, matching existing repository patterns.

- [ ] **Step 4: Extend `ProjectGraph` compatibly**

Append defaulted fields so existing positional construction remains valid:

```python
schema_version: int = 1
normalization_profile: str = "pscad-xml-v1"
definition_classifications: tuple[CorpusDefinitionClassification, ...] = ()
component_occurrences: tuple[CorpusComponentOccurrence, ...] = ()
conductor_occurrences: tuple[CorpusConductorOccurrence, ...] = ()
label_occurrences: tuple[CorpusLabelOccurrence, ...] = ()
instance_ports: tuple[CorpusInstancePort, ...] = ()
confirmed_nets: tuple[CorpusConfirmedNet, ...] = ()
port_net_memberships: tuple[CorpusPortNetMembership, ...] = ()
hierarchy_relations: tuple[CorpusHierarchyRelation, ...] = ()
candidate_edges: tuple[CorpusCandidateEdge, ...] = ()
unresolved_evidence: tuple[CorpusUnresolvedEvidence, ...] = ()
confirmed_relation_signature: str | None = None
definition_catalog_signature: str | None = None
```

`ProjectGraph.to_dict()` must emit the old exact shape for `schema_version == 1`
and add all version/profile/relation fields for schema v2.

- [ ] **Step 5: Add strict v2 graph parsing dispatch**

Keep the current `_parse_graph_v1()` logic byte-compatible. Dispatch with:

```python
def parse_project_graph(value: Any) -> ProjectGraph:
    if not isinstance(value, Mapping):
        raise _error("Artifact graph must be an object.", path="graph")
    version = value.get("schema_version", 1)
    if version == 1:
        return _parse_graph_v1(value)
    if version == 2:
        return _parse_graph_v2(value)
    raise _error("Graph schema version is unsupported.", path="graph.schema_version")
```

`_parse_graph_v2()` must use exact fields, stable enum sets, `_point`, `_digest`,
`_boolean`, and finite-number checks. It must reject relation keys that refer to
missing occurrences, ports, nets, conductors, labels, or hierarchy objects.

- [ ] **Step 6: Run model and writer compatibility tests**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_v2_models.py tests/test_blueprint_corpus_writer.py -q
```

Expected: PASS with no v1 byte-shape regression.

- [ ] **Step 7: Commit**

```powershell
git add pscad_mcp/builders/blueprint/corpus_relation_models.py
git add pscad_mcp/builders/blueprint/corpus_models.py
git add pscad_mcp/builders/blueprint/corpus_writer.py
git add tests/test_blueprint_corpus_v2_models.py
git commit -m "feat: model corpus v2 relationship records"
```

## Task 5: Preserve v2 Port and Conductor Evidence During Extraction

**Files:**

- Modify: `pscad_mcp/builders/blueprint/corpus_models.py:70-175`
- Modify: `pscad_mcp/builders/blueprint/corpus_extractor.py:314-589`
- Modify: `tests/test_blueprint_corpus_extractor.py`
- Create: `tests/fixtures/blueprint_corpus/mixed-signal-v2.pscx`

- [ ] **Step 1: Add a mixed-signal extraction fixture**

Create `mixed-signal-v2.pscx` with this exact XML:

```xml
<project name="MixedV2" version="4.6.2" Target="EMTDC">
  <definitions>
    <Definition name="Controller" classid="UserCmpDefn">
      <form><parameter name="View" type="Integer"><value>0</value></parameter></form>
      <svg>
        <port name="IN" x="-18" y="0" dim="1" model="Transfer">true</port>
        <port name="IN" x="0" y="-18" dim="1" model="Transfer">View==1</port>
      </svg>
      <schematic classid="UserCanvas" />
    </Definition>
    <Definition name="Main" classid="UserCmpDefn">
      <svg />
      <schematic classid="UserCanvas">
        <User id="101" name="CTRL" defn="MixedV2:Controller" x="18" y="18" orient="0" />
        <User id="102" name="NODE" defn="master:nodelabel" x="0" y="0">
          <paramlist><param name="Name" value="BUS" /></paramlist>
        </User>
        <User id="103" name="DATA" defn="master:datalabel" x="0" y="36">
          <paramlist><param name="Name" value="ENABLE" /></paramlist>
        </User>
        <Wire id="201" classid="WireOrthogonal" kind="electrical" x="0" y="0">
          <vertex x="0" y="0" /><vertex x="36" y="0" />
        </Wire>
        <Wire id="202" classid="Connection" kind="data" x="0" y="36">
          <vertex x="0" y="0" /><vertex x="36" y="0" />
        </Wire>
      </schematic>
    </Definition>
  </definitions>
  <hierarchy>
    <call link="999" name="MixedV2:Station" view="false" instance="0">
      <call link="101" name="MixedV2:Controller" view="true" instance="0" />
    </call>
  </hierarchy>
</project>
```

- [ ] **Step 2: Write failing evidence-preservation tests**

```python
def test_v2_extraction_preserves_port_occurrence_condition_kind_and_conductor_namespace(tmp_path):
    source, project = arrange_v2_source(tmp_path, "mixed-signal-v2.pscx")
    before = project.read_bytes()

    graph = extract_project(
        tmp_path,
        source,
        schema_version=2,
        normalization_profile="pscad-xml-v2",
    )

    ports = graph.definitions[0].ports
    assert [(port.name, port.occurrence, port.condition) for port in ports] == [
        ("IN", 0, "true"),
        ("IN", 1, "View==1"),
    ]
    assert {connection.namespace for connection in graph.connections if connection.canvas_key} == {
        "data",
        "electrical",
    }
    assert project.read_bytes() == before
```

- [ ] **Step 3: Run and observe missing fields/signature failure**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_extractor.py::test_v2_extraction_preserves_port_occurrence_condition_kind_and_conductor_namespace -v
```

Expected: FAIL because `DefinitionPort` and `CorpusConnection` do not expose the
v2 evidence fields and `extract_project()` lacks version arguments.

- [ ] **Step 4: Extend raw records with v1-aware serialization**

Add defaulted `DefinitionPort` fields:

```python
occurrence: int = 0
kind: str = ""
condition: str | None = None
page: bool = False
required: bool | None = None
```

Add `namespace: str = "unknown"` to `CorpusConnection`. Change their
`to_dict(schema_version: int = 1)` methods to omit new fields in v1 and require
them in v2. Update `ProjectGraph.to_dict()` to pass its schema version.

- [ ] **Step 5: Extract exact v2 evidence**

In `_definition_ports()`, track duplicate occurrences by exact port name and
iterate port elements by case-insensitive local tag name so `<port>` and
`<Port>` normalize identically, then preserve:

```python
condition = (port.text or "").strip() or None
kind = (port.get("kind") or port.get("model") or port.get("type") or "").strip()
page = (port.get("page") or "").strip().casefold() in {"1", "true", "yes", "on"}
```

In `_wire_connections()`, normalize namespace with the same rules as
`PscxSnapshotProvider`: explicit data/signal/digital is data; explicit
electrical/power/analog/node is electrical; `Wire` and `Bus` default to
electrical; anything else is unknown. Do not import the provider's private
helper.

Extend `extract_project()`:

```python
def extract_project(
    root: str | Path,
    source: CorpusSource,
    limits: ExtractionLimits | None = None,
    *,
    schema_version: int = 1,
    normalization_profile: str = "pscad-xml-v1",
) -> ProjectGraph:
```

Pass version/profile into `_normalize_graph()` and return them on the graph.
Reject any combination other than `(1, pscad-xml-v1)` or
`(2, pscad-xml-v2)`.

- [ ] **Step 6: Run extraction and existing corpus tests**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_extractor.py tests/test_blueprint_corpus_schema.py -q
```

Expected: PASS; existing v1 graph signatures remain unchanged.

- [ ] **Step 7: Commit**

```powershell
git add pscad_mcp/builders/blueprint/corpus_models.py
git add pscad_mcp/builders/blueprint/corpus_extractor.py
git add tests/test_blueprint_corpus_extractor.py
git add tests/fixtures/blueprint_corpus/mixed-signal-v2.pscx
git commit -m "feat: preserve corpus v2 topology evidence"
```

## Task 6: Expand Reusable Hierarchy Templates Into Distinct Occurrences

**Files:**

- Create: `pscad_mcp/builders/blueprint/corpus_relations.py`
- Create: `tests/fixtures/blueprint_corpus/repeated-module-v2.pscx`
- Create: `tests/test_blueprint_corpus_relations.py`

- [ ] **Step 1: Create a repeated-module fixture**

Create `repeated-module-v2.pscx` with this exact XML:

```xml
<project name="Repeated" version="4.6.2" Target="EMTDC">
  <definitions>
    <Definition name="Leaf" classid="UserCmpDefn">
      <svg><port name="P" x="0" y="0" dim="1" kind="electrical">true</port></svg>
      <schematic classid="UserCanvas" />
    </Definition>
    <Definition name="GainBlock" classid="UserCmpDefn">
      <svg>
        <port name="IN" x="-18" y="0" dim="1" kind="electrical" page="true">true</port>
        <port name="OUT" x="18" y="0" dim="1" kind="electrical" page="true">true</port>
      </svg>
      <schematic classid="UserCanvas">
        <User id="301" name="LEAF" defn="Repeated:Leaf" x="0" y="0" orient="0" />
        <Wire id="401" classid="WireOrthogonal" kind="electrical" x="-18" y="0">
          <vertex x="0" y="0" /><vertex x="36" y="0" />
        </Wire>
      </schematic>
    </Definition>
    <Definition name="Main" classid="UserCmpDefn">
      <svg />
      <schematic classid="UserCanvas">
        <User id="101" name="LEFT" defn="Repeated:GainBlock" x="72" y="0" orient="0" />
        <User id="102" name="RIGHT" defn="Repeated:GainBlock" x="144" y="0" orient="0" />
      </schematic>
    </Definition>
  </definitions>
  <hierarchy>
    <call link="999" name="Repeated:Station" view="false" instance="0">
      <call link="101" name="Repeated:GainBlock" view="true" instance="0">
        <call link="301" name="Repeated:Leaf" view="true" instance="0" />
      </call>
      <call link="102" name="Repeated:GainBlock" view="true" instance="1">
        <call link="301" name="Repeated:Leaf" view="true" instance="0" />
      </call>
    </call>
  </hierarchy>
</project>
```

- [ ] **Step 2: Write occurrence isolation and cycle tests**

```python
def test_repeated_child_definitions_expand_to_distinct_occurrences(tmp_path):
    graph = extract_v2_fixture(tmp_path, "repeated-module-v2.pscx")

    expanded = expand_hierarchy_occurrences(graph)

    child_components = [
        item for item in expanded.components
        if item.source_component_key.endswith("/component:leaf@0,0#1")
    ]
    assert len(child_components) == 2
    assert child_components[0].key != child_components[1].key
    assert child_components[0].canvas_key != child_components[1].canvas_key
    assert child_components[0].hierarchy_path != child_components[1].hierarchy_path


def test_hierarchy_cycle_and_missing_child_fail_closed(tmp_path):
    with pytest.raises(BackendError) as cycle:
        expand_hierarchy_occurrences(graph_with_hierarchy_cycle(tmp_path))
    assert cycle.value.code == "CORPUS_RELATION_INCOMPLETE"

    with pytest.raises(BackendError) as missing:
        expand_hierarchy_occurrences(graph_with_missing_child(tmp_path))
    assert missing.value.code == "CORPUS_RELATION_INCOMPLETE"
```

- [ ] **Step 3: Run and observe the missing API**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_relations.py::test_repeated_child_definitions_expand_to_distinct_occurrences -v
```

Expected: collection ERROR because `corpus_relations` does not exist.

- [ ] **Step 4: Implement stable hierarchy occurrence expansion**

Define:

```python
@dataclass(frozen=True)
class PendingHierarchyBoundary:
    key: str
    parent_component_key: str
    child_canvas_key: str
    page_port_names: tuple[str, ...]
    hierarchy_path: tuple[str, ...]


@dataclass(frozen=True)
class ExpandedHierarchy:
    components: tuple[CorpusComponentOccurrence, ...]
    conductors: tuple[CorpusConductorOccurrence, ...]
    labels: tuple[CorpusLabelOccurrence, ...]
    boundaries: tuple[PendingHierarchyBoundary, ...]
    source_to_occurrences: FrozenDict


def _occurrence_key(kind: str, hierarchy_path: tuple[str, ...], source_key: str) -> str:
    digest = canonical_sha256(
        {"kind": kind, "hierarchy_path": hierarchy_path, "source_key": source_key}
    )
    return f"occurrence:{kind}:{digest}"
```

Expose
`expand_hierarchy_occurrences(graph: ProjectGraph) -> ExpandedHierarchy` and
implement the traversal below.

The implementation must:

1. index canvas templates by owner definition;
2. index hierarchy edges by exact parent and child component key;
3. start from the explicit project/virtual-station roots;
4. clone template components, conductors, and labels per hierarchy path;
5. preserve source keys as evidence fields;
6. qualify all occurrence canvases and objects with `_occurrence_key`;
7. detect recursion using the active definition stack;
8. permit repeated sibling calls but never reuse their occurrence objects; and
9. sort every emitted collection by stable key.

- [ ] **Step 5: Run hierarchy tests**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_relations.py -k "hierarchy or repeated" -q
```

Expected: PASS with two distinct child occurrence subgraphs.

- [ ] **Step 6: Commit**

```powershell
git add pscad_mcp/builders/blueprint/corpus_relations.py
git add tests/fixtures/blueprint_corpus/repeated-module-v2.pscx
git add tests/test_blueprint_corpus_relations.py
git commit -m "feat: expand corpus hierarchy occurrences"
```

## Task 7: Classify Definitions and Materialize Exact Instance Ports

**Files:**

- Modify: `pscad_mcp/builders/blueprint/definition_catalog.py`
- Modify: `pscad_mcp/builders/blueprint/corpus_relations.py`
- Modify: `tests/test_blueprint_definition_catalog.py`
- Modify: `tests/test_blueprint_corpus_relations.py`

- [ ] **Step 1: Write classification and port-materialization tests**

```python
def test_classification_and_ports_use_exact_contracts_conditions_and_orientation(tmp_path):
    graph, catalog = arrange_relation_graph_and_catalog(tmp_path)

    result = materialize_instance_ports(graph, catalog)

    assert {item.classification for item in result.classifications} == {
        "non_connective",
        "port_bearing",
    }
    output = next(port for port in result.ports if port.name == "OUT")
    assert output.active is True
    assert output.relative == (18, 0)
    assert output.absolute == (72, 36)
    assert output.namespace == "data"
    assert output.dimension == 1


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        ("missing_definition", "CORPUS_DEFINITION_UNRESOLVED"),
        ("ambiguous_definition", "CORPUS_DEFINITION_AMBIGUOUS"),
        ("unsupported_condition", "CORPUS_PORT_CONDITION_UNRESOLVED"),
        ("invalid_orientation", "CORPUS_PORT_GEOMETRY_UNRESOLVED"),
        ("unknown_namespace", "CORPUS_RELATION_INCOMPLETE"),
    ],
)
def test_port_materialization_blocks_incomplete_truth(tmp_path, damage, code):
    graph, catalog = arrange_damaged_relation_input(tmp_path, damage)
    with pytest.raises(BackendError) as raised:
        materialize_instance_ports(graph, catalog)
    assert raised.value.code == code
    assert str(tmp_path) not in str(raised.value.details)
```

- [ ] **Step 2: Run and observe the missing materializer**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_relations.py::test_classification_and_ports_use_exact_contracts_conditions_and_orientation -v
```

Expected: FAIL because `materialize_instance_ports` is not defined.

- [ ] **Step 3: Add exact classification**

Expose from `definition_catalog.py`:

```python
def classify_definition(definition: CatalogDefinition) -> str:
    return "port_bearing" if definition.metadata.ports else "non_connective"
```

Project-local definitions must be normalized into the same `CatalogDefinition`
shape before lookup. Label definitions `nodelabel` and `datalabel` remain
port-bearing evidence but are projected as labels, not ordinary component
ports, matching `PscxSnapshotProvider` semantics.

- [ ] **Step 4: Materialize ports**

Implement:

```python
@dataclass(frozen=True)
class MaterializedPorts:
    classifications: tuple[CorpusDefinitionClassification, ...]
    ports: tuple[CorpusInstancePort, ...]
```

Expose `materialize_instance_ports(graph: ProjectGraph,
catalog: DefinitionCatalog, expanded: ExpandedHierarchy | None = None) ->
MaterializedPorts` and implement the rules below.

For each non-label component occurrence:

1. resolve exact scope/name/version;
2. classify it;
3. combine exact instance parameters over definition defaults;
4. evaluate each condition with `evaluate_condition()`;
5. retain active ports only in canonical topology while persisting inactive
   ports with `active=False` in v2 evidence;
6. normalize namespace and dimension with documented rules;
7. compute absolute geometry with `absolute_port()`; and
8. use `component occurrence + port name + occurrence` for the stable key.

Any unresolved classification or active-port property raises the stable error
before a promoted graph is returned.

- [ ] **Step 5: Run relation/catalog tests**

Run:

```powershell
python -m pytest tests/test_blueprint_definition_catalog.py tests/test_blueprint_corpus_conditions.py tests/test_blueprint_corpus_relations.py -q
```

Expected: PASS with no unresolved truth silently downgraded.

- [ ] **Step 6: Commit**

```powershell
git add pscad_mcp/builders/blueprint/definition_catalog.py
git add pscad_mcp/builders/blueprint/corpus_relations.py
git add tests/test_blueprint_definition_catalog.py
git add tests/test_blueprint_corpus_relations.py
git commit -m "feat: materialize exact corpus instance ports"
```

## Task 8: Project Canonical Connectivity and Confirmed Relationship Truth

**Files:**

- Modify: `pscad_mcp/builders/blueprint/corpus_relations.py`
- Modify: `pscad_mcp/builders/blueprint/corpus_extractor.py:751-758`
- Modify: `tests/test_blueprint_corpus_relations.py`
- Create: `tests/test_blueprint_corpus_topology_parity.py`

- [ ] **Step 1: Write canonical parity and candidate-isolation tests**

```python
@pytest.mark.parametrize(
    "fixture",
    ["ordinary.pscx", "mixed_signal.pscx", "custom_library.pscx", "hierarchy.pscx"],
)
def test_corpus_projection_matches_canonical_confirmed_topology(tmp_path, fixture):
    source_path, source, spec, bindings = arrange_topology_fixture(tmp_path, fixture)
    snapshot = PscxSnapshotProvider().read(source_path, "Main")
    canonical = build_connectivity(project_topology_from_snapshot(snapshot)).topology

    raw = extract_project(
        tmp_path,
        source,
        schema_version=2,
        normalization_profile="pscad-xml-v2",
    )
    projected = build_relationship_truth(raw, spec, bindings)

    expected = structural_topology_projection(canonical)
    observed = structural_topology_projection(projected.topology)
    assert observed == expected
    assert projected.confirmed_topology_hash == topology_sha256(projected.topology)


def test_candidate_edges_change_full_graph_but_not_confirmed_relation_signature(tmp_path):
    raw, spec, bindings = arrange_nearby_dangling_fixture(tmp_path)
    conservative = build_relationship_truth(raw, spec, bindings, infer=False).graph
    inferred = build_relationship_truth(raw, spec, bindings, infer=True).graph

    assert conservative.candidate_edges == ()
    assert inferred.candidate_edges
    assert conservative.confirmed_relation_signature == inferred.confirmed_relation_signature
    assert graph_signature(conservative) != graph_signature(inferred)
```

Define `project_topology_from_snapshot()` in the test module by copying the
snapshot fields into `ProjectTopology`. Define `structural_topology_projection()`
in that module to replace every runtime key with the structural identity listed
in Planning Clarifications, then return sorted complete net memberships. Do not
add a production convenience API solely for parity testing.

- [ ] **Step 2: Run and observe missing relationship projection**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_topology_parity.py -v
```

Expected: collection ERROR because `build_relationship_truth` does not exist.

- [ ] **Step 3: Convert expanded evidence into canonical topology records**

Implement exact adapters for:

- `CorpusComponentOccurrence -> TopologyComponent`;
- `CorpusConductorOccurrence -> TopologyConductor`;
- `CorpusLabelOccurrence -> TopologyLabel`;
- `CorpusInstancePort -> TopologyPort`; and
- pending hierarchy boundaries -> `TopologyBoundaryLink`.

Use `EvidenceRef(source="corpus", reference=<stable source key>,
fingerprint=<source sha256>)`. Unknown conductor namespace, malformed vertices,
missing boundary ports, or incompatible dimensions remain bounded unresolved
evidence and block formal promotion when they prevent relationship truth.

- [ ] **Step 4: Build and project relations**

Expose:

```python
@dataclass(frozen=True)
class RelationshipBuild:
    graph: ProjectGraph
    topology: ProjectTopology = field(compare=False, repr=False)
    confirmed_topology_hash: str
    phase_timings_ms: tuple[tuple[str, float], ...]
```

Expose `build_relationship_truth(raw_graph: ProjectGraph, spec: CorpusSpec,
definition_bindings: Mapping[tuple[str, str], Path], *, infer: bool = True) ->
RelationshipBuild` and implement the orchestration below.

The function must load one definition catalog, expand hierarchy occurrences,
materialize ports, create canonical topology, call `build_connectivity()` once,
optionally call `infer_candidate_edges()` after confirmed nets exist, and
project sorted v2 records. Create one membership per confirmed `(port, net)`;
never create pairwise component adjacency. Set
`graph.definition_catalog_signature` from `catalog.catalog_signature`, set
`graph.confirmed_relation_signature` only after every confirmed collection is
final, and return the canonical `ProjectTopology` on `RelationshipBuild` for
verification without serializing it.

Calculate:

```python
def confirmed_relation_signature(graph: ProjectGraph) -> str:
    return canonical_sha256(
        {
            "definition_classifications": [item.to_dict() for item in graph.definition_classifications],
            "component_occurrences": [item.to_dict() for item in graph.component_occurrences],
            "instance_ports": [item.to_dict() for item in graph.instance_ports],
            "confirmed_nets": [item.to_dict() for item in graph.confirmed_nets],
            "port_net_memberships": [item.to_dict() for item in graph.port_net_memberships],
            "hierarchy_relations": [item.to_dict() for item in graph.hierarchy_relations],
        }
    )
```

Candidates, unresolved observation metadata, timings, and local paths are
excluded from this signature.

- [ ] **Step 5: Run topology parity and canonical topology tests**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_topology_parity.py tests/test_topology_connectivity.py tests/test_topology_diagnostics.py -q
```

Expected: PASS; existing canonical topology behavior is unchanged.

- [ ] **Step 6: Commit**

```powershell
git add pscad_mcp/builders/blueprint/corpus_relations.py
git add pscad_mcp/builders/blueprint/corpus_extractor.py
git add tests/test_blueprint_corpus_relations.py
git add tests/test_blueprint_corpus_topology_parity.py
git commit -m "feat: project canonical corpus relationships"
```

## Task 9: Write and Validate v2 JSONL and Manifests Atomically

**Files:**

- Modify: `pscad_mcp/builders/blueprint/corpus_models.py:270-350`
- Modify: `pscad_mcp/builders/blueprint/corpus_writer.py:28-800`
- Modify: `tests/test_blueprint_corpus_writer.py`
- Create: `tests/fixtures/blueprint_corpus/v1_compat/graph.json`
- Create: `tests/fixtures/blueprint_corpus/v1_compat/records.jsonl`
- Create: `tests/fixtures/blueprint_corpus/v1_compat/manifest.json`

- [ ] **Step 1: Freeze a small canonical v1 graph/record/manifest bundle**

Generate it once from the existing minimal fixture before changing writer
semantics, then verify its hashes manually with `Get-FileHash`. Store only the
small fixture bundle under `tests/fixtures/blueprint_corpus/v1_compat/`.

- [ ] **Step 2: Write failing v2 record and manifest tests**

```python
def test_v2_records_cover_every_relation_kind_in_stable_order(relation_graph):
    records = derive_records("fixture_v2", "pscad-xml-v2", relation_graph)

    assert [record.kind for record in records] == sorted(
        [record.kind for record in records], key=KIND_ORDER_V2.__getitem__
    )
    assert {
        "component_occurrence",
        "conductor_occurrence",
        "label_occurrence",
        "instance_port",
        "confirmed_net",
        "port_net_membership",
        "hierarchy_relation",
        "candidate_edge",
        "unresolved_evidence",
    } <= {record.kind for record in records}
    assert all(record.schema_version == 2 for record in records)


def test_v2_manifest_cross_checks_confirmed_relation_signature(tmp_path, v2_spec, relation_graph):
    manifest = write_corpus_candidate(v2_spec, (relation_graph,), tmp_path / "candidate")
    project = manifest.projects[0]
    assert project.confirmed_relation_signature == relation_graph.confirmed_relation_signature
    assert validate_candidate(tmp_path / "candidate", v2_spec) == manifest
```

- [ ] **Step 3: Run and observe unsupported v2 kinds/manifest fields**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_writer.py -k "v2_records or v2_manifest" -v
```

Expected: FAIL because `KIND_ORDER`, record schema, and manifest schema support
only v1.

- [ ] **Step 4: Add versioned record derivation**

Retain `KIND_ORDER_V1` unchanged and define:

```python
KIND_ORDER_V2 = {
    **KIND_ORDER_V1,
    "definition_classification": 8,
    "component_occurrence": 9,
    "conductor_occurrence": 10,
    "label_occurrence": 11,
    "instance_port": 12,
    "confirmed_net": 13,
    "port_net_membership": 14,
    "hierarchy_relation": 15,
    "candidate_edge": 16,
    "unresolved_evidence": 17,
}
```

`derive_records()` dispatches by `graph.schema_version`. V2 resolved statuses are:

- confirmed/classified records: `offline_confirmed`;
- candidate edges: `candidate_only`, `resolved=False`;
- engineering unresolved records: `unresolved`, `resolved=False`.

- [ ] **Step 5: Add v2 manifest fields and strict cross-checks**

Extend `CorpusProjectManifest` with defaulted optional fields:

```python
confirmed_relation_signature: str | None = None
definition_catalog_signature: str | None = None
```

V1 serialization omits them. V2 requires both. `validate_candidate()` must
reparse every graph and JSONL record, verify exact kind counts, verify both
signatures, scan privacy, reject extra files, and prove every candidate edge is
absent from confirmed nets/memberships/signature input.

- [ ] **Step 6: Prove atomic failure leaves the destination unchanged**

Add a test that mutates one membership net key, calls
`write_corpus_candidate()`, expects `CORPUS_MANIFEST_INVALID`, and byte-compares
the pre-existing destination tree before/after.

- [ ] **Step 7: Run writer, privacy, and v1 compatibility tests**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_writer.py tests/test_blueprint_corpus_v2_models.py -q
```

Expected: PASS; frozen v1 bundle bytes and parsing remain unchanged.

- [ ] **Step 8: Commit**

```powershell
git add pscad_mcp/builders/blueprint/corpus_models.py
git add pscad_mcp/builders/blueprint/corpus_writer.py
git add tests/test_blueprint_corpus_writer.py
git add tests/fixtures/blueprint_corpus/v1_compat
git commit -m "feat: serialize corpus v2 relationship truth"
```

## Task 10: Update Blueprint Verification and Packaged Asset Loading

**Files:**

- Modify: `pscad_mcp/builders/blueprint/corpus_models.py:350-375`
- Modify: `pscad_mcp/builders/blueprint/corpus_verifier.py:28-200`
- Modify: `pscad_mcp/builders/blueprint/corpus_assets.py:72-165`
- Modify: `tests/test_blueprint_corpus_verifier.py`
- Modify: `tests/test_blueprint_corpus_assets.py`
- Create: `tests/fixtures/blueprint_corpus/v1_compat/blueprint.json`

- [ ] **Step 1: Freeze the minimal v1 Blueprint fixture**

Generate it from the current minimal v1 graph and store the canonical ASCII JSON
under `v1_compat/blueprint.json`. The fixture retains Blueprint schema version 1
and `corpus-existing-project-v1`.

- [ ] **Step 2: Write v2 Blueprint and packaged-loader tests**

```python
def test_v2_blueprint_remains_read_only_and_relation_bound(v2_source, relation_graph):
    value = generate_blueprint_candidate(v2_source, relation_graph)
    parsed = parse_blueprint(value)
    verification = verify_blueprint_candidate(value, relation_graph, v2_source)

    assert parsed.identity.schema_version == 1
    assert parsed.identity.name.endswith("-existing-v2")
    assert parsed.identity.inspection_profile == "corpus-existing-project-v2"
    assert parsed.operations == ()
    assert parsed.source_package["handling_policy"] == "read_only"
    assert verification.graph_signature == graph_signature(relation_graph)
    assert verification.confirmed_relation_signature == relation_graph.confirmed_relation_signature


def test_frozen_v1_bundle_has_no_fabricated_v2_relationship_claim():
    root = FIXTURES / "v1_compat"
    graph = parse_project_graph(json.loads((root / "graph.json").read_text(encoding="ascii")))
    manifest = parse_corpus_manifest(json.loads((root / "manifest.json").read_text(encoding="ascii")))
    blueprint = parse_blueprint(json.loads((root / "blueprint.json").read_text(encoding="ascii")))

    assert graph.schema_version == manifest.schema_version == 1
    assert graph.confirmed_relation_signature is None
    assert blueprint.identity.inspection_profile == "corpus-existing-project-v1"


def test_v2_manifest_parser_preserves_confirmed_relation_signature(v2_manifest_value):
    manifest = parse_corpus_manifest(v2_manifest_value)
    assert manifest.schema_version == 2
    assert manifest.projects[0].confirmed_relation_signature == "c" * 64
```

- [ ] **Step 3: Run and observe v1-only identity failures**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_verifier.py tests/test_blueprint_corpus_assets.py -k "v2 or frozen_v1" -v
```

Expected: FAIL because generation requires `existing-v1`, v1 inspection profile,
and `BlueprintVerification` has no confirmed relation signature.

- [ ] **Step 4: Version the evidence-only Blueprint identity**

Keep generic Blueprint schema version 1. Dispatch corpus asset identity only:

```python
def _blueprint_name(source: CorpusSource, graph: ProjectGraph) -> str:
    return f"{source.project_id}-existing-v{graph.schema_version}"


def _inspection_profile(graph: ProjectGraph) -> str:
    return f"corpus-existing-project-v{graph.schema_version}"
```

Extend `BlueprintVerification` with
`confirmed_relation_signature: str | None = None`. V2 verification requires it
to equal the graph; v1 keeps `None`. Do not add relation fields to the generic
Blueprint acceptance schema because runtime validation does not consume them.

- [ ] **Step 5: Version packaged loading**

`corpus_assets.py` must dispatch v1/v2 manifest/graph/record parsing, check graph
and confirmed-relation signatures, load the matching `existing-v1` or
`existing-v2` directory, and reject mixed-version bundles.

- [ ] **Step 6: Run verifier/assets tests**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_verifier.py tests/test_blueprint_corpus_assets.py -q
```

Expected: PASS; every Blueprint remains read-only and operations-empty.

- [ ] **Step 7: Commit**

```powershell
git add pscad_mcp/builders/blueprint/corpus_models.py
git add pscad_mcp/builders/blueprint/corpus_verifier.py
git add pscad_mcp/builders/blueprint/corpus_assets.py
git add tests/test_blueprint_corpus_verifier.py
git add tests/test_blueprint_corpus_assets.py
git add tests/fixtures/blueprint_corpus/v1_compat/blueprint.json
git commit -m "feat: bind corpus v2 Blueprints to relationship truth"
```

## Task 11: Add Definition-Source Preflight and v2 CLI Flow

**Files:**

- Modify: `scripts/build_blueprint_corpus.py:39-360`
- Modify: `tests/test_blueprint_corpus_cli.py`
- Modify: `tests/test_blueprint_corpus_regression.py`

- [ ] **Step 1: Write CLI parsing, privacy, and atomic-stop tests**

```python
def test_v2_preflight_requires_every_versioned_definition_source(tmp_path):
    source_root, spec_path, output, master_462 = arrange_v2_cli_input(tmp_path)

    result = run_cli([
        "preflight",
        "--source-root", str(source_root),
        "--spec", str(spec_path),
        "--output", str(output),
        "--definition-source", f"master@4.6.2={master_462}",
    ])

    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "code": "CORPUS_DEFINITION_SOURCE_MISMATCH",
        "status": "failed",
    }
    assert str(tmp_path) not in result.stdout
    assert not output.exists()


def test_v2_generate_verify_compare_use_the_same_relation_graph(tmp_path):
    args = arrange_complete_v2_cli_args(tmp_path)
    generated = run_cli(["generate", *args])
    verified = run_cli(["verify", *args])
    compared = run_cli(["compare", *args])

    assert generated.returncode == verified.returncode == compared.returncode == 0
    assert json.loads(generated.stdout)["schema_version"] == 2
    assert json.loads(verified.stdout)["status"] == "verified"
    assert json.loads(compared.stdout)["status"] == "identical"
```

- [ ] **Step 2: Run and observe unsupported command/argument failures**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_cli.py -k "v2_preflight or v2_generate" -v
```

Expected: FAIL because `preflight` and `--definition-source` are unsupported.

- [ ] **Step 3: Add strict binding parsing**

Add repeatable CLI syntax:

```text
--definition-source namespace@version=ABSOLUTE_PATH
```

Parse with:

```python
def _definition_bindings(values: Sequence[str]) -> dict[tuple[str, str], Path]:
    result = {}
    for value in values:
        identity, separator, raw_path = value.partition("=")
        namespace, marker, version = identity.partition("@")
        if not separator or not marker or not namespace or not version:
            raise _error("CORPUS_DEFINITION_SOURCE_MISMATCH", "Definition-source binding is invalid.")
        path = Path(raw_path)
        key = (namespace, version)
        if not path.is_absolute() or key in result:
            raise _error("CORPUS_DEFINITION_SOURCE_MISMATCH", "Definition-source binding is invalid.")
        result[key] = path
    return result
```

Never return the raw path in stdout or `BackendError.details`.

- [ ] **Step 4: Add `preflight` and integrate v2 generation**

`preflight` must parse the spec, load and validate all definition sources,
extract every raw graph, build relationship truth, verify source/catalog
post-hashes, and return only portable counts/signatures. It writes no output.

For schema v2, `_extract_graphs()` becomes:

```python
def _extract_graphs(
    source_root: Path,
    spec: CorpusSpec,
    definition_bindings: Mapping[tuple[str, str], Path],
) -> tuple[ProjectGraph, ...]:
    raw = tuple(
        extract_project(
            source_root,
            source,
            schema_version=spec.schema_version,
            normalization_profile=spec.normalization_profile,
        )
        for source in spec.entry_points
    )
    if spec.schema_version == 1:
        return raw
    return tuple(
        build_relationship_truth(graph, spec, definition_bindings).graph
        for graph in raw
    )
```

`generate`, `verify`, and `compare` must call the same function. A failure before
or during relationship projection must leave corpus and Blueprint destinations
byte-identical.

- [ ] **Step 5: Add a portable `propose-spec` command**

`propose-spec` accepts a v1 spec plus complete definition bindings and an
explicit `--proposal` destination outside the source root. It writes a schema
v2 candidate spec with observed basename/length/hash/version/policy values,
then reparses it with `parse_corpus_spec()`. It never updates the packaged spec
or corpus automatically. Reject an existing proposal path to avoid overwrite.

- [ ] **Step 6: Run CLI and regression tests**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_cli.py tests/test_blueprint_corpus_regression.py -q
```

Expected: PASS. The real corpus regression may skip when its explicit source
environment is absent; fixture tests must not skip.

- [ ] **Step 7: Commit**

```powershell
git add scripts/build_blueprint_corpus.py
git add tests/test_blueprint_corpus_cli.py
git add tests/test_blueprint_corpus_regression.py
git commit -m "feat: add corpus v2 definition preflight"
```

## Task 12: Pass the External Definition-Evidence Gate and Migrate Assets

**Files:**

- Modify after PASS only: `pscad_mcp/assets/corpora/moxing_v1/source-spec.json`
- Replace after PASS only: `pscad_mcp/assets/corpora/moxing_v1/manifest.json`
- Replace after PASS only: `pscad_mcp/assets/corpora/moxing_v1/graphs/*.json`
- Replace after PASS only: `pscad_mcp/assets/corpora/moxing_v1/records/*.jsonl`
- Replace after PASS only: four directories under `pscad_mcp/assets/blueprints/*-existing-v2/`
- Remove after PASS only: the four corresponding `*-existing-v1/` production directories

- [ ] **Step 1: Define explicit local evidence variables**

Before running commands, the operator must set all four absolute paths:

```powershell
$env:PSCAD_MCP_CORPUS_SOURCE = 'C:\Users\335\Desktop\moxing'
$env:PSCAD_MCP_MASTER_462 = 'C:\Program Files (x86)\PSCAD46\master.pslx'
if (-not $env:PSCAD_MCP_MASTER_463) { throw 'PSCAD_MCP_MASTER_463 is required' }
if (-not $env:PSCAD_MCP_VSC_MMC_LIB_462) { throw 'PSCAD_MCP_VSC_MMC_LIB_462 is required' }
$master463 = [System.IO.Path]::GetFullPath($env:PSCAD_MCP_MASTER_463)
$vscMmc462 = [System.IO.Path]::GetFullPath($env:PSCAD_MCP_VSC_MMC_LIB_462)
if (-not (Test-Path -LiteralPath $master463 -PathType Leaf)) { throw 'PSCAD 4.6.3 Master source is unavailable' }
if (-not (Test-Path -LiteralPath $vscMmc462 -PathType Leaf)) { throw 'PSCAD 4.6.2 VSC-MMC source is unavailable' }
$reparsePoint = [System.IO.FileAttributes]::ReparsePoint
if (((Get-Item -LiteralPath $master463).Attributes -band $reparsePoint) -ne 0) { throw 'PSCAD 4.6.3 Master source cannot be a link' }
if (((Get-Item -LiteralPath $vscMmc462).Attributes -band $reparsePoint) -ne 0) { throw 'PSCAD 4.6.2 VSC-MMC source cannot be a link' }
```

The operator supplies the two missing environment variables before execution.
If either is unavailable, stop Task 12 and report exactly:

```text
action: needs_evidence
missing: master@4.6.3 and/or vsc-mmc-lib@4.6.2
assets_changed: false
```

This stop is an explicit evidence gate, not permission to weaken the spec.

- [ ] **Step 2: Propose and review the v2 source specification**

Run:

```powershell
python scripts/build_blueprint_corpus.py propose-spec `
  --source-root $env:PSCAD_MCP_CORPUS_SOURCE `
  --spec pscad_mcp/assets/corpora/moxing_v1/source-spec.json `
  --proposal D:\PSCAD-Workspace\corpus-v2-source-spec-proposal.json `
  --definition-source "master@4.6.2=$env:PSCAD_MCP_MASTER_462" `
  --definition-source "master@4.6.3=$env:PSCAD_MCP_MASTER_463" `
  --definition-source "vsc-mmc-lib@4.6.2=$env:PSCAD_MCP_VSC_MMC_LIB_462"
```

Expected: exit 0 and portable JSON summary with `status=proposed`. Review the
proposal to confirm only schema/profile/definition-source declarations changed;
it must contain no absolute path.

- [ ] **Step 3: Run read-only relationship preflight**

Run:

```powershell
python scripts/build_blueprint_corpus.py preflight `
  --source-root $env:PSCAD_MCP_CORPUS_SOURCE `
  --spec D:\PSCAD-Workspace\corpus-v2-source-spec-proposal.json `
  --output D:\PSCAD-Workspace\corpus-v2-preflight-unused `
  --definition-source "master@4.6.2=$env:PSCAD_MCP_MASTER_462" `
  --definition-source "master@4.6.3=$env:PSCAD_MCP_MASTER_463" `
  --definition-source "vsc-mmc-lib@4.6.2=$env:PSCAD_MCP_VSC_MMC_LIB_462"
```

Expected: exit 0, zero unclassified definitions, no blocking port condition or
geometry evidence, stable confirmed relation signatures for four projects, and
unchanged input hashes. On any failure, leave production assets unchanged and
stop with the returned stable code.

- [ ] **Step 4: Generate into an isolated proposed destination**

Run:

```powershell
python scripts/build_blueprint_corpus.py generate `
  --source-root $env:PSCAD_MCP_CORPUS_SOURCE `
  --spec D:\PSCAD-Workspace\corpus-v2-source-spec-proposal.json `
  --output D:\PSCAD-Workspace\moxing_v2-proposed `
  --definition-source "master@4.6.2=$env:PSCAD_MCP_MASTER_462" `
  --definition-source "master@4.6.3=$env:PSCAD_MCP_MASTER_463" `
  --definition-source "vsc-mmc-lib@4.6.2=$env:PSCAD_MCP_VSC_MMC_LIB_462"
```

Expected: exit 0, four schema v2 graphs/record files and four `existing-v2`
Blueprint candidates.

- [ ] **Step 5: Verify and compare proposed output before promotion**

Run `verify` and `compare` with the same arguments, replacing the command name.
Both must exit 0; `compare` must report `identical` on a second generation.
Re-hash all PSCX/PSLX inputs and require exact preflight hashes.

- [ ] **Step 6: Promote through repository edits only after PASS**

Use `apply_patch` for the reviewed source-spec change. Use the production
generator's validated atomic output for the bulk JSON/JSONL asset replacement;
do not hand-edit generated graph, record, or manifest files. Move the four
reviewed v2 Blueprint candidate directories into the package and remove the
four v1 production directories only after packaged-loader tests pass against
the staged package tree.

- [ ] **Step 7: Run packaged asset and corpus drift tests**

Run:

```powershell
python -m pytest tests/test_blueprint_corpus_assets.py tests/test_blueprint_corpus_regression.py tests/test_packaging_metadata.py -q
```

Expected: PASS with `PSCAD_MCP_CORPUS_SOURCE` set; no corpus-regression skip.

- [ ] **Step 8: Commit the reviewed migration**

```powershell
git add pscad_mcp/assets/corpora/moxing_v1
git add pscad_mcp/assets/blueprints
git commit -m "data: migrate PSCAD corpus relationship truth to v2"
```

Do not commit a partial asset migration. If Step 1 or Step 3 blocks, this task
has no commit and remains `needs_evidence`.

## Task 13: Document, Verify, and Close R1

**Files:**

- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `CHANGELOG.md`
- Modify if package patterns require it: `pyproject.toml`
- Modify: `tests/test_changelog.py`
- Test: all focused and non-licensed repository tests

- [ ] **Step 1: Write documentation contract tests first**

Extend existing documentation tests to require these facts in English and
Chinese documentation:

```python
def test_readme_describes_corpus_v2_relationship_boundaries():
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (ROOT / "docs" / "zh-CN" / "README.md").read_text(encoding="utf-8")
    for text in (english, chinese):
        assert "pscad-xml-v2" in text
        assert "confirmed" in text.casefold()
        assert "candidate" in text.casefold()
        assert "definition" in text.casefold()
    assert "does not require PSCAD" in english
    assert "不需要启动 PSCAD" in chinese
```

- [ ] **Step 2: Run and observe missing documentation**

Run:

```powershell
python -m pytest tests/test_changelog.py tests/test_packaging_metadata.py -v
```

Expected: FAIL on the new corpus v2 documentation assertions.

- [ ] **Step 3: Update user and maintainer documentation**

Document:

- schema v2 relationship fields and v1 read compatibility;
- hash-bound versioned definition-source CLI syntax;
- zero-unclassified-definition promotion gate;
- confirmed/candidate/unresolved separation;
- offline-only safety and input immutability;
- `preflight`, `propose-spec`, `generate`, `verify`, and `compare` examples;
- the fact that R1 makes no licensed acceptance claim; and
- the exact `needs_evidence` behavior for unavailable proprietary inputs.

Update `CHANGELOG.md` with one concise R1 entry. Update package-data patterns
only if the new generated filenames are not already covered by the existing
wildcards.

- [ ] **Step 4: Run focused R1 tests**

Run:

```powershell
python -m pytest `
  tests/test_blueprint_corpus_schema.py `
  tests/test_blueprint_definition_catalog.py `
  tests/test_blueprint_corpus_conditions.py `
  tests/test_blueprint_corpus_v2_models.py `
  tests/test_blueprint_corpus_extractor.py `
  tests/test_blueprint_corpus_relations.py `
  tests/test_blueprint_corpus_topology_parity.py `
  tests/test_blueprint_corpus_writer.py `
  tests/test_blueprint_corpus_verifier.py `
  tests/test_blueprint_corpus_assets.py `
  tests/test_blueprint_corpus_cli.py `
  tests/test_blueprint_corpus_regression.py `
  -q
```

Expected: exit 0, no failures, and no corpus-regression skip when Task 12 has
the required environment.

- [ ] **Step 5: Run canonical topology regression**

Run:

```powershell
python -m pytest tests/test_topology_models.py tests/test_topology_geometry.py tests/test_topology_connectivity.py tests/test_topology_diagnostics.py tests/test_topology_pscx_provider.py -q
```

Expected: exit 0 with no changes to canonical topology behavior.

- [ ] **Step 6: Run lint**

Run:

```powershell
python -m ruff check pscad_mcp scripts tests
```

Expected: exit 0 with no Ruff findings.

- [ ] **Step 7: Run the full non-licensed suite**

Run:

```powershell
python -m pytest -q
```

Expected: exit 0 with no failures. Licensed tests may skip according to their
existing explicit opt-in gates; R1 must not set those opt-ins.

- [ ] **Step 8: Verify package construction**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify_package.ps1
```

Expected: exit 0; built package contains the v2 corpus and v2 Blueprint assets,
and the install smoke test loads them.

- [ ] **Step 9: Verify source and definition inputs remain unchanged**

Re-run `preflight` with the reviewed definition bindings and compare every
reported hash to Task 12. Expected: exact match. Also run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only intended R1 documentation changes remain
unstaged before the final commit.

- [ ] **Step 10: Commit documentation and R1 closure**

```powershell
git add README.md docs/zh-CN/README.md CHANGELOG.md
git add tests/test_changelog.py
git add pyproject.toml
git commit -m "docs: document corpus relationship truth v2"
```

Stage `pyproject.toml` only when Step 3 required an actual package-data change.

## Final R1 Evidence Record

Before claiming R1 complete, record all of these values in the implementation
summary:

- implementation commit;
- source-spec SHA-256;
- each entry-point and definition-source SHA-256;
- four graph, record, full graph signature, and confirmed relation signature
  values;
- definition classification counts with zero unresolved;
- component/conductor/label occurrence, instance-port, confirmed-net,
  membership, hierarchy, candidate, and unresolved counts;
- focused/full/lint/package command outcomes;
- source pre/post hash equality; and
- explicit statement that no PSCAD process was started and no licensed claim
  was added.

If Task 12 lacks either proprietary definition source, report the completed
code/test tasks separately and use the fixed action `needs_evidence`. Do not
describe the corpus migration or R1 as complete.
