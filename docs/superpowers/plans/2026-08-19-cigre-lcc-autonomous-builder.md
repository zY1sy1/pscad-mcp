# CIGRE LCC Autonomous Model Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four MCP tools that deterministically plan, construct, validate, compile, simulate, and electrically accept a fixed CIGRE single-pole 12-pulse LCC benchmark in licensed PSCAD 4.6.2 from an empty case.

**Architecture:** A versioned, hash-verified blueprint and original companion library feed a side-effect-free planner. A workspace-locked asynchronous executor applies the immutable plan through `PscadService`, verifies every mutation and the saved PSCX graph, then publishes only after golden-waveform and physical acceptance pass.

**Tech Stack:** Python 3.10+, FastMCP, `dataclasses`, `json`, `hashlib`, `pathlib`, `xml.etree.ElementTree`, `asyncio`, `psutil`, pytest, `mhrc.automation`, PSCAD/EMTDC 4.6.2.

---

## Execution Prerequisites

- Use `superpowers:using-git-worktrees` before Task 1 and create a branch named `codex/cigre-lcc-builder` from commit `82c1f0c` or its descendant.
- Configure the implementation worktree with the repository's `.venv` or a new Windows virtual environment containing the Legacy Automation Library.
- Keep `C:\PSCADFiles\Breaker` and every other user project read-only. They may be inspected for API behavior, but no XML, definition, parameter set, or schematic may be copied into packaged assets.
- Do not claim completion until the licensed acceptance task passes. Mocked tests are necessary but not sufficient.

Run the baseline before editing:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m compileall -q pscad_mcp tests
git diff --check
```

Expected: the default suite passes, compilation exits `0`, and `git diff --check` prints nothing.

## File Map

Create these focused modules:

- `pscad_mcp/hvdc/builders/__init__.py`: builder package marker.
- `pscad_mcp/hvdc/builders/lcc/__init__.py`: supported blueprint name and public service exports.
- `pscad_mcp/hvdc/builders/lcc/models.py`: immutable JSON-safe records and build states.
- `pscad_mcp/hvdc/builders/lcc/schema.py`: strict blueprint/catalog/acceptance parsing.
- `pscad_mcp/hvdc/builders/lcc/assets.py`: packaged asset loading, hashes, and workspace materialization.
- `pscad_mcp/hvdc/builders/lcc/catalog.py`: exact definition/port/parameter contracts.
- `pscad_mcp/hvdc/builders/lcc/routing.py`: orientation transforms and orthogonal routes.
- `pscad_mcp/hvdc/builders/lcc/planner.py`: immutable operation expansion and plan hashing.
- `pscad_mcp/hvdc/builders/lcc/project_graph.py`: structured PSCX graph reader.
- `pscad_mcp/hvdc/builders/lcc/validator.py`: graph-to-blueprint comparison.
- `pscad_mcp/hvdc/builders/lcc/acceptance.py`: golden and physical acceptance.
- `pscad_mcp/hvdc/builders/lcc/journal.py`: atomic journal and cross-process workspace lock.
- `pscad_mcp/hvdc/builders/lcc/executor.py`: staged build execution.
- `pscad_mcp/hvdc/builders/lcc/service.py`: public builder service and async lifecycle.
- `pscad_mcp/tools/lcc_tools.py`: four FastMCP wrappers.
- `scripts/audit_lcc_assets.py`: provenance and package-asset audit.
- `scripts/generate_lcc_golden.py`: explicit maintainer-only golden generator.
- `tests/lcc_builder_fakes.py`: focused service/backend fakes.
- `tests/test_lcc_*.py`: unit, contract, fault, packaging, and licensed acceptance tests.

Modify only these existing integration files:

- `pscad_mcp/main.py`: register the four new tools.
- `pscad_mcp/hvdc/profiles.py`: add the explicit v2 CIGRE result profile.
- `pyproject.toml`: package the recursive LCC asset set.
- `tests/test_tool_inventory.py`: change the exact inventory from 70 to 74.
- `tests/test_hvdc_tools.py`: preserve the existing ten-tool HVDC assertion while expecting 74 total.
- `README.md`, `docs/zh-CN/README.md`, and `CHANGELOG.md`: document the accepted capability and its limits.

## Task 1: Immutable Builder Records And Strict Schema

**Files:**
- Create: `pscad_mcp/hvdc/builders/__init__.py`
- Create: `pscad_mcp/hvdc/builders/lcc/__init__.py`
- Create: `pscad_mcp/hvdc/builders/lcc/models.py`
- Create: `pscad_mcp/hvdc/builders/lcc/schema.py`
- Test: `tests/test_lcc_schema.py`

- [ ] **Step 1: Write the failing valid-blueprint test**

Create a compact in-test blueprint with one source, one converter, one net, fixed settings, and one output. Assert exact parsing and JSON serialization:

```python
def test_blueprint_is_strict_and_json_safe():
    blueprint = parse_blueprint(VALID_BLUEPRINT)
    assert blueprint.name == "cigre_lcc_monopole_v1"
    assert blueprint.topology == "lcc"
    assert blueprint.poles == 1
    assert blueprint.terminals == 2
    assert blueprint.components[0].logical_id == "rectifier_source"
    assert json.loads(json.dumps(blueprint.to_dict()))["schema_version"] == 1
```

- [ ] **Step 2: Write failing rejection tests**

Assert `LCC_BLUEPRINT_INVALID` for an unknown top-level field, duplicate logical ID, missing endpoint, non-integer coordinates, orientation outside `0..7`, diagonal route segment, and non-positive pole count. Assert schema parsing accepts `poles=2`; planner rejection belongs to Task 4.

- [ ] **Step 3: Run the schema tests and verify the import failure**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_schema.py -q
```

Expected: FAIL because `pscad_mcp.hvdc.builders.lcc.schema` does not exist.

- [ ] **Step 4: Add immutable records**

Define frozen dataclasses for `LccEndpoint`, `LccRoute`, `LccNetSpec`, `LccComponentSpec`, `LccOutputSpec`, `LccBlueprint`, `LccPlanOperation`, `LccBuildPlan`, `LccAcceptanceCheck`, and `LccBuildRecord`. Define the exact state enum:

```python
class LccBuildState(str, Enum):
    VALIDATED = "validated"
    STAGING_CREATED = "staging_created"
    COMPONENTS_PLACED = "components_placed"
    PARAMETERS_VERIFIED = "parameters_verified"
    CONNECTIONS_VERIFIED = "connections_verified"
    STRUCTURE_VERIFIED = "structure_verified"
    STAGING_SAVED = "staging_saved"
    COMPILED = "compiled"
    SIMULATED = "simulated"
    ACCEPTANCE_PASSED = "acceptance_passed"
    PUBLISHED = "published"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"
```

Every record exposes `to_dict()` implemented with `dataclasses.asdict()` plus enum normalization. Do not store `Path`, exceptions, tasks, locks, or vendor proxies in serialized records.

- [ ] **Step 5: Implement strict parsing**

Implement `parse_blueprint(data: Mapping[str, Any]) -> LccBlueprint` with explicit allowed-key sets at every nesting level. Use `_invalid(message, **details)` to raise:

```python
BackendError(
    "LCC_BLUEPRINT_INVALID",
    message,
    "hvdc",
    "parse_lcc_blueprint",
    details,
)
```

Reject booleans where integers or floats are required. Normalize no user-provided identifier beyond trimming surrounding whitespace; duplicate checks use exact stored IDs.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_schema.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the schema slice**

```powershell
git add pscad_mcp/hvdc/builders tests/test_lcc_schema.py
git commit -m "feat: define strict LCC builder contracts"
```

## Task 2: Hash-Verified Asset Loader

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/assets.py`
- Test: `tests/test_lcc_assets.py`

- [ ] **Step 1: Write failing manifest tests**

Use `tmp_path` to create `blueprint.json`, `catalog-pscad-4.6.2.json`, `acceptance.json`, `golden.json`, `PROVENANCE.md`, and `library/cigre_lcc_v1.pslx`. Build `manifest.json` from their SHA-256 values. Assert:

```python
asset_set = load_asset_set(tmp_path)
assert asset_set.name == "cigre_lcc_monopole_v1"
assert asset_set.blueprint.name == "cigre_lcc_monopole_v1"
assert asset_set.hashes["library/cigre_lcc_v1.pslx"] == sha256_file(library)
```

Add tests that mutate one byte, remove one file, add `library/unexpected.pslx`, use `../escape.json`, and declare PSCAD `5.0`. Each must raise the exact asset or version error before returning any parsed data.

- [ ] **Step 2: Run the asset tests and verify failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_assets.py -q
```

Expected: FAIL because the asset loader is missing.

- [ ] **Step 3: Implement canonical hashing and manifest validation**

Add:

```python
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
```

Resolve every manifest child with `Path.resolve()` and require it to remain below the resolved asset root. Compare the exact recursive file set, excluding only `manifest.json`, with the manifest keys. Validate hashes before parsing JSON or XML.

Add `load_packaged_asset_set(name)` using `importlib.resources.files("pscad_mcp")`
and `importlib.resources.as_file()`. The returned `LccAssetSet` must own parsed
bytes and records rather than retaining a temporary resource path. Accept only
the exact packaged name `cigre_lcc_monopole_v1` in version 1; unknown names
raise `LCC_BLUEPRINT_NOT_FOUND`.

- [ ] **Step 4: Implement workspace library materialization**

Add `materialize_library(asset_set, workspace_root) -> Path`. It creates `.pscad-mcp/libraries` only after build confirmation has been checked by the caller. Use a same-directory temporary file, verify the copied hash, then `Path.replace()` it into place. Reuse an exact existing file; raise `LCC_ASSET_MISMATCH` without replacement when it differs.

- [ ] **Step 5: Run focused tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_assets.py -q
git add pscad_mcp/hvdc/builders/lcc/assets.py tests/test_lcc_assets.py
git commit -m "feat: verify LCC builder assets"
```

## Task 3: Exact Component Catalog And Routing

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/catalog.py`
- Create: `pscad_mcp/hvdc/builders/lcc/routing.py`
- Test: `tests/test_lcc_catalog.py`
- Test: `tests/test_lcc_routing.py`

- [ ] **Step 1: Write failing catalog tests**

Test exact scoped-name lookup, required parameter type/range/enum validation, exact port kind/dimension matching, missing definitions, unknown parameters, and boolean rejection for numeric parameters. Use catalog records with `master:source3` and `cigre_lcc_v1:LCC12PulseBridge`.

- [ ] **Step 2: Write all eight orientation tests**

Use port offset `(12, 6)` and assert:

```python
EXPECTED = {
    0: (12, 6), 1: (-6, 12), 2: (-12, -6), 3: (6, -12),
    4: (-12, 6), 5: (-6, -12), 6: (12, -6), 7: (6, 12),
}
for orientation, expected in EXPECTED.items():
    assert transform_offset(12, 6, orientation) == expected
```

Add route tests rejecting diagonal and zero-length segments and rejecting routes that cross a declared component rectangle.

- [ ] **Step 3: Run tests and verify failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_catalog.py tests\test_lcc_routing.py -q
```

Expected: FAIL on missing modules.

- [ ] **Step 4: Implement exact catalog parsing**

Expose `parse_catalog`, `require_definition`, `require_port`, and `validate_parameters`. Catalog lookup must use exact `library:name`; do not strip library scopes or use aliases. Parameter validation returns a normalized new dictionary and never mutates the input.

- [ ] **Step 5: Implement routing primitives**

Use the orientation table already proven by `LegacyBackend._absolute_legacy_port_location`. Add `absolute_port(origin, offset, orientation)`, `validate_orthogonal_route(vertices)`, and `route_intersects_rectangles(vertices, rectangles)`. Routes include endpoints and require at least two vertices.

- [ ] **Step 6: Run tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_catalog.py tests\test_lcc_routing.py -q
git add pscad_mcp/hvdc/builders/lcc/catalog.py pscad_mcp/hvdc/builders/lcc/routing.py tests/test_lcc_catalog.py tests/test_lcc_routing.py
git commit -m "feat: validate LCC components and routes"
```

## Task 4: Deterministic Side-Effect-Free Planner

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/planner.py`
- Test: `tests/test_lcc_planner.py`

- [ ] **Step 1: Write the failing determinism test**

Construct the same asset set and inventory twice, then assert identical dictionaries and hashes:

```python
first = create_plan(request, asset_set, inventory, workspace)
second = create_plan(request, asset_set, inventory, workspace)
assert first.to_dict() == second.to_dict()
assert first.plan_hash == second.plan_hash
assert list(workspace.iterdir()) == []
```

The fixture request is `project_name="CIGRE_LCC"`, `simulation_duration_s=None`, and blueprint `cigre_lcc_monopole_v1`.

- [ ] **Step 2: Add failing planner boundary tests**

Assert exact failures for an existing final destination, missing Master definition, missing companion port, duration shorter than the packaged default, PSCAD version other than 4.6.2, `poles=2`, route collision, and an output selector not backed by a declared measurement.

- [ ] **Step 3: Run planner tests and verify failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_planner.py -q
```

Expected: FAIL because `create_plan` is missing.

- [ ] **Step 4: Implement normalized request and operation expansion**

Define `LccPlanRequest` with `project_name`, `folder`, `simulation_duration_s`, and `blueprint`. Resolve the final path through `PathPolicy`; reject an existing path regardless of confirmation. Expand operations in this exact phase order:

```python
PHASES = (
    "materialize_library", "create_staging", "set_settings",
    "place_power", "place_control", "place_measurement",
    "verify_parameters", "connect_electrical", "connect_data",
    "create_outputs", "save_and_validate", "compile", "simulate",
    "accept", "publish",
)
```

Give every operation a stable ID formed from phase, logical object, and a zero-padded phase-local index.

- [ ] **Step 5: Implement canonical plan hashing**

Serialize the plan without `plan_hash`, timestamps, warnings produced by the live backend, or display text. Hash `canonical_json(payload)`. Include normalized target paths, PSCAD version, asset hashes, catalog identity, project settings, expanded operations, and acceptance contract.

- [ ] **Step 6: Run tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_planner.py -q
git add pscad_mcp/hvdc/builders/lcc/planner.py tests/test_lcc_planner.py
git commit -m "feat: plan deterministic LCC builds"
```

## Task 5: Structured PSCX Project Graph Reader

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/project_graph.py`
- Test: `tests/test_lcc_project_graph.py`
- Test fixture: `tests/fixtures/lcc/graph_case.pscx`

- [ ] **Step 1: Add a minimal real-shape PSCX fixture**

The fixture must include a `Main` user definition, three components with explicit IDs/definitions/locations/orientations, one multi-vertex electrical wire, two matching data labels, and parameter lists. Keep it synthetic and repository-authored.

- [ ] **Step 2: Write the failing graph test**

Assert normalized component keys, exact parameters, wire vertices, orientation-aware port endpoints, and two connected nets. Assert unrelated PSCAD-generated `id`, `crc`, `link`, `date`, and hierarchy call order do not change the normalized graph.

- [ ] **Step 3: Run the graph tests and verify failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_project_graph.py -q
```

Expected: FAIL because `read_project_graph` is missing.

- [ ] **Step 4: Implement structured XML parsing**

Use `xml.etree.ElementTree.parse`; do not search or rewrite XML with regular expressions. Resolve the `Main` definition/schematic shape used by PSCAD 4.6.2 and the simplified fixture shape used by existing scanner tests. Return frozen records for components, wires, labels, and normalized nets.

- [ ] **Step 5: Implement connectivity reduction**

Create graph points from wire vertices and catalog-derived absolute ports. Union points joined by wire segments and matching labels of the same declared kind. Keep electrical and data namespaces separate. Sort normalized output by canvas, definition, location, and route vertices.

- [ ] **Step 6: Run tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_project_graph.py -q
git add pscad_mcp/hvdc/builders/lcc/project_graph.py tests/test_lcc_project_graph.py tests/fixtures/lcc/graph_case.pscx
git commit -m "feat: read normalized PSCX connectivity"
```

## Task 6: Independent Structural Validator

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/validator.py`
- Test: `tests/test_lcc_validator.py`

- [ ] **Step 1: Write failing exact-match and mismatch tests**

Create an expected graph from the unit blueprint and compare it with a parsed fixture. Assert `valid=True` only for exact blueprint-owned structure. Parameterize one-at-a-time mutations for missing component, unexpected definition, wrong orientation, parameter drift, missing wire, extra electrical connection, duplicated signal label, unconnected required port, and electrical/data net mixing.

- [ ] **Step 2: Run tests and verify failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_validator.py -q
```

Expected: FAIL because `validate_project_graph` is missing.

- [ ] **Step 3: Implement stable validation findings**

Return:

```python
{
    "valid": False,
    "blueprint": blueprint.name,
    "components": {"expected": 3, "observed": 2},
    "nets": {"expected": 2, "observed": 1},
    "errors": [
        {
            "code": "LCC_STRUCTURE_INVALID",
            "logical_id": "dc_line",
            "reason": "missing_component",
            "expected": {"definition": "master:line"},
            "observed": None,
        }
    ],
    "warnings": [],
}
```

Match components by blueprint logical ID mapped to exact definition, location, and orientation. Do not infer identity from display-name substrings. Sort findings by code, logical ID, and reason.

- [ ] **Step 4: Add companion-library internal validation**

Parse the companion `.pslx` and require exact declared custom definitions and external ports. For `LCC12PulseBridge`, verify two declared six-pulse groups, twelve valve instances, separated AC port groups, common declared DC series path, and gate interface dimensions. The production asset supplies exact component IDs through its internal audit contract; unit tests use synthetic definitions.

- [ ] **Step 5: Run tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_validator.py -q
git add pscad_mcp/hvdc/builders/lcc/validator.py tests/test_lcc_validator.py
git commit -m "feat: validate generated LCC topology"
```

## Task 7: Golden And Physical Acceptance Engine

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/acceptance.py`
- Test: `tests/test_lcc_acceptance.py`

- [ ] **Step 1: Write failing waveform tests**

Use deterministic 50 Hz samples with a known one-sample phase shift. Assert positive-going zero-crossing alignment, bounded one-cycle shift, linear interpolation, NRMSE, normalized maximum error, and rejection of extrapolation. Include the exact formula from the design in the expected values.

- [ ] **Step 2: Write failing data-quality tests**

Assert `INCOMPLETE_ANALYSIS` for missing channel, empty samples, non-finite value, duplicate/non-monotonic time, unit mismatch, failed alignment, or inconsistent domains. Verify no missing value becomes zero.

- [ ] **Step 3: Write failing physical checks**

Use a fixed sample payload in kV, kA, MW, MVAr, and degrees. Assert pass/fail behavior for DC voltage/current magnitude and polarity, `Pdc=Vdc*Idc`, terminal power balance, firing angle, extinction angle, overlap angle, ripple, and steady-state control error.

- [ ] **Step 4: Run tests and verify failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_acceptance.py -q
```

Expected: FAIL because the acceptance engine is missing.

- [ ] **Step 5: Implement bounded normalization and comparison**

Limit each channel to one million samples and golden channels to the manifest-declared set. Implement:

```python
def normalized_errors(actual: list[float], golden: list[float], scale_floor: float) -> tuple[float, float]:
    scale = max(percentile95([abs(value) for value in golden]), scale_floor)
    squared = [(left - right) ** 2 for left, right in zip(actual, golden)]
    nrmse = math.sqrt(sum(squared) / len(squared)) / scale
    maximum = max(abs(left - right) for left, right in zip(actual, golden)) / scale
    return nrmse, maximum
```

Reject unequal or empty aligned vectors before calling this function.

- [ ] **Step 6: Implement the final verdict**

Expose `evaluate_acceptance(samples, golden, contract)`. Every result is `observed`, `derived`, `missing`, or `invalid`. Return `PASS` only when every required golden comparison and every required physical check passes; otherwise return `FAIL` or `INCOMPLETE_ANALYSIS` according to whether evidence exists but violates a bound or is unusable/missing.

- [ ] **Step 7: Run tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_acceptance.py -q
git add pscad_mcp/hvdc/builders/lcc/acceptance.py tests/test_lcc_acceptance.py
git commit -m "feat: accept LCC electrical behavior"
```

## Task 8: Atomic Journal And Cross-Process Workspace Lease

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/journal.py`
- Test: `tests/test_lcc_journal.py`

- [ ] **Step 1: Write failing atomic-journal tests**

Assert journal writes use a same-directory temporary file, leave valid JSON after replacement, preserve the previous journal when serialization fails, and contain no `Path`, exception, task, or proxy objects.

- [ ] **Step 2: Write failing lease tests**

Assert the first `WorkspaceBuildLease.acquire()` succeeds, a second live owner raises `LCC_BUILD_CONFLICT`, releasing removes only the matching token, a mismatched token cannot release, and a dead PID is marked interrupted before replacement. Patch `psutil.pid_exists` rather than terminating processes.

- [ ] **Step 3: Run tests and verify failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_journal.py -q
```

Expected: FAIL because journal and lease classes are missing.

- [ ] **Step 4: Implement atomic journal writes**

Use `tempfile.NamedTemporaryFile(delete=False, dir=journal.parent)` followed by `os.replace`. Flush and `os.fsync` before replacement. The journal path is `.pscad-mcp/lcc-builds/<build_id>/journal.json`.

- [ ] **Step 5: Implement atomic lease acquisition**

Acquire `.pscad-mcp/lcc-build.lock` with `os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)`. Store `build_id`, PID, token, UTC creation time, and journal path. On an existing lock, read and validate it; only a non-existent PID permits stale-lock recovery. Corrupt lock metadata fails closed with `LCC_BUILD_CONFLICT`.

- [ ] **Step 6: Run tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_journal.py -q
git add pscad_mcp/hvdc/builders/lcc/journal.py tests/test_lcc_journal.py
git commit -m "feat: journal and lock LCC builds"
```

## Task 9: Staged Executor With Verified Postconditions

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/executor.py`
- Create: `tests/lcc_builder_fakes.py`
- Test: `tests/test_lcc_executor.py`

- [ ] **Step 1: Build a recording fake service**

Implement async fake methods matching the used `PscadService` surface: `create_project`, `load_projects`, `set_project_settings`, `get_project_settings`, `add_canvas_component`, `get_component_location`, `get_component_parameters`, `get_component_ports`, `create_wire`, `create_connection`, `save_project`, `build_project`, `run_project`, `get_run_status`, `get_project_output`, and `save_project_as`. Every method appends a normalized call tuple and supports failure injection by call name.

- [ ] **Step 2: Write the failing happy-path order test**

Run `execute_build` with a two-component plan and assert exact state history from `validated` through `published`. Assert every mutation is followed by the corresponding read-back before the next phase and the final path is created only after acceptance reports `PASS`.

- [ ] **Step 3: Write parameterized failure-containment tests**

Inject failure at component creation, parameter read-back, connection creation, graph validation, compile, run, output read, acceptance, save-as, final validation, and final compile. For every case assert: no later planned call occurs, state is terminal, final destination is absent, the staging directory remains, and the journal names the failed operation.

- [ ] **Step 4: Run executor tests and verify failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_executor.py -q
```

Expected: FAIL because `execute_build` is missing.

- [ ] **Step 5: Implement the operation dispatcher**

Dispatch only the known `PHASES` and operation kinds emitted by Task 4. Unknown kinds raise `LCC_BLUEPRINT_INVALID`. Use the returned PSCAD component ID map keyed by logical ID. For each component, compare definition/location/orientation, parameters, and port contract with observed service values.

- [ ] **Step 6: Implement compile/run waiting**

Use bounded monotonic-time polling. Treat `completed`, `complete`, `finished`, `done`, `idle`, and `stopped` as terminal success only after a run was observed; treat `failed`, `error`, and `aborted` as failure. Never use wall-clock time as EMTDC simulation time. Store polling diagnostics in the journal.

- [ ] **Step 7: Implement transactional publication**

After staging acceptance, call the service save-as boundary for the planned final identity, parse and validate the candidate final file, then compile it. If either check fails, close/unload when available and move every builder-created candidate artifact into the build evidence directory. Verify the final path is absent before returning failure.

- [ ] **Step 8: Run focused and service-boundary tests**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_executor.py tests\test_project_tool_service_boundary.py tests\test_canvas_service_boundary.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit the executor slice**

```powershell
git add pscad_mcp/hvdc/builders/lcc/executor.py tests/lcc_builder_fakes.py tests/test_lcc_executor.py
git commit -m "feat: execute verified LCC builds"
```

## Task 10: Builder Service And Asynchronous Lifecycle

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/service.py`
- Test: `tests/test_lcc_builder_service.py`

- [ ] **Step 1: Write failing public-service contract tests**

Assert `plan_model` is side-effect free, `build_model` requires confirmation, stale plan hashes fail before lease acquisition, the valid call returns a build ID without waiting for simulation, status is JSON safe, unknown IDs raise `NOT_FOUND`, and validation never calls run/save/mutation methods.

- [ ] **Step 2: Write failing lifecycle tests**

Assert only one task is active per workspace, task completion releases the matching lease, cancellation becomes `interrupted`, timeout becomes `timed_out`, exceptions become structured `failed` records, and journal-backed interrupted status survives constructing a new service instance.

Add a table-driven error-contract test covering every stable design code:
`LCC_BLUEPRINT_NOT_FOUND`, `LCC_BLUEPRINT_INVALID`,
`LCC_BLUEPRINT_UNSUPPORTED`, `LCC_ASSET_MISMATCH`,
`LCC_VERSION_UNSUPPORTED`, `LCC_DEFINITION_MISSING`, `LCC_PORT_MISMATCH`,
`LCC_PARAMETER_MISMATCH`, `LCC_LAYOUT_INVALID`, `LCC_PLAN_STALE`,
`LCC_BUILD_CONFLICT`, `LCC_POSTCONDITION_FAILED`, `LCC_BUILD_FAILED`,
`LCC_BUILD_TIMED_OUT`, `LCC_STRUCTURE_INVALID`, `LCC_OUTPUT_INCOMPLETE`, and
`LCC_ACCEPTANCE_FAILED`. Assert backend `hvdc`, the relevant operation,
JSON-safe details, retryability evidence, and a non-empty suggested action.

- [ ] **Step 3: Run service tests and verify failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_builder_service.py -q
```

Expected: FAIL because `LccBuilderService` is missing.

- [ ] **Step 4: Implement the public service**

Expose these exact public methods and implement them only by composing the
planner, validator, journal, lease, and executor from Tasks 1-9:

```python
class LccBuilderService:
    def plan_model(self, project_name: str, folder: str | None = None,
                   simulation_duration_s: float | None = None,
                   blueprint: str = "cigre_lcc_monopole_v1") -> dict[str, Any]:
        request = LccPlanRequest(project_name, folder, simulation_duration_s, blueprint)
        return self._create_plan(request).to_dict()

    async def build_model(self, project_name: str, expected_plan_hash: str,
                          folder: str | None = None,
                          simulation_duration_s: float | None = None,
                          blueprint: str = "cigre_lcc_monopole_v1",
                          confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise ConfirmationRequired("build_lcc_model")
        request = LccPlanRequest(project_name, folder, simulation_duration_s, blueprint)
        plan = self._create_plan(request)
        if not secrets.compare_digest(plan.plan_hash, expected_plan_hash):
            raise self._plan_stale(expected_plan_hash, plan.plan_hash)
        return await self._start_build(plan)

    def get_build_status(self, build_id: str) -> dict[str, Any]:
        return self._load_record(build_id).to_dict()

    def validate_model(self, project_name: str,
                       blueprint: str = "cigre_lcc_monopole_v1",
                       output_file: str | None = None) -> dict[str, Any]:
        return self._validate_saved_model(project_name, blueprint, output_file)
```

The implementation may format signatures over multiple lines but must preserve
names, defaults, and semantics. `_create_plan`, `_start_build`, `_load_record`,
`_plan_stale`, and `_validate_saved_model` are private service helpers
implemented in this task; they must not duplicate schema, planner, executor,
or validator logic.

- [ ] **Step 5: Implement task ownership and retention**

Keep live `asyncio.Task` objects in a private, nonserialized map. Keep terminal JSON-safe records in memory and on disk. Add a done callback that consumes task exceptions, persists the terminal record, and releases only the task's lease token.

- [ ] **Step 6: Run tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_builder_service.py -q
git add pscad_mcp/hvdc/builders/lcc/service.py tests/test_lcc_builder_service.py
git commit -m "feat: orchestrate asynchronous LCC builds"
```

## Task 11: Explicit CIGRE v2 Result Profile

**Files:**
- Modify: `pscad_mcp/hvdc/profiles.py:16-126`
- Test: `tests/test_lcc_profile.py`

- [ ] **Step 1: Write the failing profile test**

Assert `load_profile("cigre_lcc_monopole_v1")` returns version 2, no command bindings, and exact required roles for rectifier/inverter DC voltage, DC current, terminal P/Q, firing angle, extinction angle, overlap angle, and AC alignment. Assert every result selector has path, units, and location; call IDs are positive when present.

- [ ] **Step 2: Run the test and verify profile-not-found**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_profile.py -q
```

Expected: FAIL with `HVDC_PROFILE_NOT_FOUND`.

- [ ] **Step 3: Add the read-only profile**

Add `cigre_lcc_monopole_v1` to `_BUILTIN_PROFILES` with
`profile_version=2`, required assets `rectifier`, `inverter`, `controller`,
`pole`, and `dc_line`, an empty `command_bindings`, explicit mappings, result
channels, metric roles, and no sequences. Define these exact canonical paths
and units; Task 14 must create them without aliases:

```text
Main/VDC_RECT kV       Main/VDC_INV kV        Main/IDC kA
Main/P_RECT MW         Main/Q_RECT MVAr       Main/P_INV MW
Main/Q_INV MVAr        Main/ALPHA_RECT deg    Main/GAMMA_INV deg
Main/MU_RECT deg       Main/VAC_RECT_A kV
```

Omit a call ID when PSCAD has not yet produced and verified one, because path
and units remain mandatory and the schema already treats call IDs as optional.
Do not infer aliases for results.

- [ ] **Step 4: Run profile and HVDC tests, then commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_profile.py tests\test_hvdc_profiles_v2.py tests\test_hvdc_preflight.py -q
git add pscad_mcp/hvdc/profiles.py tests/test_lcc_profile.py
git commit -m "feat: define CIGRE LCC result semantics"
```

## Task 12: Four MCP Tools And Inventory Integration

**Files:**
- Create: `pscad_mcp/tools/lcc_tools.py`
- Modify: `pscad_mcp/main.py:3-34`
- Modify: `tests/test_tool_inventory.py:1-24`
- Modify: `tests/test_hvdc_tools.py:12-26`
- Test: `tests/test_lcc_tools.py`

- [ ] **Step 1: Write failing registration and routing tests**

Assert the exact four names are registered and total tool count is 74. Patch `pscad_manager.service` and the builder-service factory to prove tool wrappers never access vendor proxies and forward exact argument values.

- [ ] **Step 2: Run tool tests and verify failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_tools.py tests\test_tool_inventory.py tests\test_hvdc_tools.py -q
```

Expected: FAIL with missing tools and count mismatch.

- [ ] **Step 3: Implement wrappers and registration**

Use the same backend-identity cache pattern as `hvdc_tools.py`. Define `plan_lcc_model`, `build_lcc_model`, `get_lcc_build_status`, and `validate_lcc_model` with the service signatures from Task 10. Register them in `register_lcc_tools(mcp)` and call that function after `register_hvdc_tools(mcp)` in `create_server()`.

- [ ] **Step 4: Run contract tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_tools.py tests\test_tool_inventory.py tests\test_hvdc_tools.py tests\test_tools.py -q
git add pscad_mcp/tools/lcc_tools.py pscad_mcp/main.py tests/test_lcc_tools.py tests/test_tool_inventory.py tests/test_hvdc_tools.py
git commit -m "feat: expose autonomous LCC builder tools"
```

## Task 13: Author And Audit The Original PSCAD 4.6.2 Companion Library

**Files:**
- Create: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/library/cigre_lcc_v1.pslx`
- Create: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/PROVENANCE.md`
- Create: `scripts/audit_lcc_assets.py`
- Test: `tests/test_lcc_asset_audit.py`

- [ ] **Step 1: Write the failing provenance audit test**

Assert the audit rejects a library containing an unapproved non-Master scoped definition, a missing custom definition, a missing required external port, fewer or more than twelve valve instances, embedded absolute paths, or missing provenance entries.

- [ ] **Step 2: Implement the audit script**

The script accepts `--asset-root`, parses the `.pslx` structurally, and emits JSON. Require these original definitions and external contracts:

```text
cigre_lcc_v1:LCC12PulseBridge
  ACY_A ACY_B ACY_C ACD_A ACD_B ACD_C DC_POS DC_NEG GATES
cigre_lcc_v1:RectifierControl
  VDC IDC IORDER ENABLE GATES ALPHA
cigre_lcc_v1:InverterControl
  VDC IDC GAMMA_ORDER ENABLE GATES GAMMA
cigre_lcc_v1:SignalInterface
cigre_lcc_v1:Initialization
```

Require `GATES` to have dimension 12. Require internal Master references to be listed in `PROVENANCE.md`; reject references to local project/library scopes.

- [ ] **Step 3: Characterize exact installed Master definitions**

In licensed PSCAD 4.6.2, create a temporary library outside packaged assets, call `get_project_definitions("master")`, inspect candidate definition metadata with the existing structured metadata reader, and record only exact scoped names, ports, ranges, and enums needed by the authored library. Commit no vendor definition body or screenshot.

- [ ] **Step 4: Author the companion library in PSCAD 4.6.2**

Start from the repository's empty library template through the normal `create_library` service path. In the PSCAD definition editor, create the five definitions and external ports listed in Step 2. Construct `LCC12PulseBridge` from twelve Master thyristor valve instances arranged as two six-pulse groups with separate Y/Y and Y/delta AC interfaces and the declared DC series path. Construct the controllers from Master control blocks according to the public CIGRE control diagrams. Save as `cigre_lcc_v1.pslx` only after PSCAD compiles the library with zero errors.

- [ ] **Step 5: Write provenance from the public benchmark source**

`PROVENANCE.md` must cite M. Szechtman, T. Wess, and C. V. Thio, "A benchmark model for HVDC system studies," Electra, no. 135, April 1991, pp. 54-73. Map each fixed bridge, transformer-interface, control, initialization, and limit parameter to its table, figure, or equation location. State that local Breaker projects were not sources for packaged content.

- [ ] **Step 6: Run the audit and library compilation check**

```powershell
& .\.venv\Scripts\python.exe scripts\audit_lcc_assets.py --asset-root pscad_mcp\assets\lcc\cigre_lcc_monopole_v1
```

Expected: JSON with `"valid": true`, five approved custom definitions, twelve valves, no foreign scopes, and no absolute paths. Also load and build the library in PSCAD 4.6.2; expected result is zero compile errors.

- [ ] **Step 7: Run tests and commit the original library**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_asset_audit.py tests\test_definition_metadata.py -q
git add pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/library/cigre_lcc_v1.pslx pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/PROVENANCE.md scripts/audit_lcc_assets.py tests/test_lcc_asset_audit.py
git commit -m "feat: add original CIGRE LCC library"
```

## Task 14: Production Blueprint, Catalog, Acceptance Contract, And Golden Baseline

**Files:**
- Create: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/blueprint.json`
- Create: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/catalog-pscad-4.6.2.json`
- Create: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/acceptance.json`
- Create: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/golden.json`
- Create: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/manifest.json`
- Create: `scripts/generate_lcc_golden.py`
- Test: `tests/test_lcc_production_assets.py`

- [ ] **Step 1: Write failing production-asset tests**

Load the packaged asset set and assert its fixed identity, PSCAD 4.6.2 target, one pole, two terminals, two six-pulse groups, required power components, exact output selectors, complete acceptance thresholds, complete hashes, and provenance for every electrical parameter.

- [ ] **Step 2: Build the exact catalog**

Populate the catalog only from Task 13 characterization and the authored `.pslx`. Include all eight orientation values, exact port coordinates/kinds/dimensions, legal parameter ranges, enum values, and component bounding boxes. Verify catalog metadata against the loaded Master and companion libraries with a read-only characterization script before committing.

- [ ] **Step 3: Encode the fixed CIGRE blueprint**

Transcribe the public benchmark values cited in `PROVENANCE.md`. Place equivalent AC sources, converter transformers, filter branches, smoothing reactors, DC line sections, meters, labels, the bridge, and the two controllers with stable logical IDs. Use explicit orthogonal routes and exact output selectors. Set `topology="lcc"`, `poles=1`, `terminals=2`, and reject electrical overrides through the public request schema.

- [ ] **Step 4: Encode acceptance thresholds with rationale**

For each golden and physical threshold, record units, comparison window, severity, required flag, and either a public-source citation or an engineering rationale. Include DC voltage/current/power, power balance, alpha, gamma, overlap, ripple, and control-error bounds. The Python engine must contain no profile-specific numeric tolerance.

- [ ] **Step 5: Implement the confirmed golden generator**

The script requires `--reference-output`, `--blueprint`, `--library`, `--compiler`, and literal `--confirm`. Without confirmation it exits nonzero before writing. It resolves selectors exactly, validates units/time domains, down-samples only the declared comparison window, writes to a temporary sibling, prints the proposed source hashes and statistics, then atomically replaces `golden.json`.

- [ ] **Step 6: Generate the golden file from an independently reviewed reference run**

Manually construct and review the fixed benchmark in a separate acceptance workspace using the authored companion library and public parameter ledger. Compile and run it in PSCAD 4.6.2. Two reviewers, or one reviewer plus a second independent script comparison against the published ratings, must sign the provenance record before running the confirmed generator. Do not generate golden data from the builder under test.

- [ ] **Step 7: Create the final manifest and run production-asset tests**

Compute SHA-256 for every packaged child and write the exact recursive set into `manifest.json`. Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_production_assets.py tests\test_lcc_assets.py tests\test_lcc_planner.py -q
& .\.venv\Scripts\python.exe scripts\audit_lcc_assets.py --asset-root pscad_mcp\assets\lcc\cigre_lcc_monopole_v1
```

Expected: all tests pass and the audit reports `valid=true`.

- [ ] **Step 8: Commit the complete trusted asset set**

```powershell
git add pscad_mcp/assets/lcc/cigre_lcc_monopole_v1 scripts/generate_lcc_golden.py tests/test_lcc_production_assets.py
git commit -m "feat: define fixed CIGRE LCC blueprint"
```

## Task 15: Package Assets And Installation Verification

**Files:**
- Modify: `pyproject.toml:28-29`
- Modify: `scripts/verify_package.ps1`
- Modify: `tests/test_packaging_metadata.py`
- Modify: `tests/test_install_smoke.py`

- [ ] **Step 1: Write failing wheel-content assertions**

Assert the installed package contains every manifest child, recomputes matching hashes, loads the production asset set without repository-relative paths, and exposes no absolute author-machine path.

- [ ] **Step 2: Run packaging tests and verify failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_packaging_metadata.py tests\test_install_smoke.py -q
```

Expected: FAIL because recursive LCC assets are absent from the wheel.

- [ ] **Step 3: Add explicit recursive package-data patterns**

Extend `[tool.setuptools.package-data]` to include JSON, Markdown, and PSLX
files below `assets/lcc/*` and `assets/lcc/*/library`. Change both installed
wheel tool-count assertions in `scripts/verify_package.ps1` from 70 to 74.
Extend package verification to load and audit the asset set from the installed
wheel, not the checkout.

- [ ] **Step 4: Build and verify the wheel**

```powershell
& .\scripts\verify_package.ps1
```

Expected: build and isolated installation smoke tests pass; the report lists the complete CIGRE asset manifest.

- [ ] **Step 5: Commit packaging support**

```powershell
git add pyproject.toml scripts/verify_package.ps1 tests/test_packaging_metadata.py tests/test_install_smoke.py
git commit -m "build: package verified LCC assets"
```

## Task 16: Licensed PSCAD 4.6.2 End-To-End Acceptance

**Files:**
- Create: `tests/test_lcc_real_acceptance.py`
- Create: `tests/test_lcc_real_acceptance_contract.py`
- Modify: `config.example.toml`

- [ ] **Step 1: Write the nonlicensed harness contract tests**

Test environment parsing, absolute workspace enforcement, timestamped output directory naming, service-boundary construction, logical project identity use, hash preservation, report schema, cleanup ownership, and the skip reason when `PSCAD_MCP_LCC_ACCEPTANCE` is not `1`.

- [ ] **Step 2: Run harness tests and verify failure**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_real_acceptance_contract.py -q
```

Expected: FAIL because the harness is missing.

- [ ] **Step 3: Implement the licensed test through public boundaries**

The test must create a new timestamped workspace, construct `PscadService` with the real Legacy backend, call `LccBuilderService.plan_model`, call confirmed `build_model` with the exact hash, poll status to a bounded terminal state, independently call `validate_model` with the produced output, verify final compile smoke, and persist `lcc-acceptance-report.json`.

- [ ] **Step 4: Add strict cleanup and preservation evidence**

Hash all packaged assets and pre-existing workspace files before the run and verify them afterward. In `finally`, terminate only a PSCAD process owned by the test and remove only test-owned transient process artifacts. Retain the timestamped project and acceptance report as evidence.

- [ ] **Step 5: Run the nonlicensed harness tests**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_real_acceptance_contract.py tests\test_lcc_real_acceptance.py -q
```

Expected: contract tests pass; the real test skips with the documented opt-in reason.

- [ ] **Step 6: Run the licensed acceptance**

```powershell
$env:PSCAD_MCP_LCC_ACCEPTANCE='1'
$env:PSCAD_MCP_BACKEND='legacy'
$env:PSCAD_MCP_VERSION='4.6.2'
$env:PSCAD_MCP_X64='true'
$env:PSCAD_MCP_WORKSPACE='C:\PSCAD-MCP-Acceptance'
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_real_acceptance.py -q -s
```

Expected: the test creates a case from empty, reaches `published`, independently validates `PASS`, compiles the final identity, and records unchanged input hashes. A skip, safe rejection, compile-only result, or `INCOMPLETE_ANALYSIS` is not success.

- [ ] **Step 7: Commit the acceptance harness and evidence schema**

```powershell
git add tests/test_lcc_real_acceptance.py tests/test_lcc_real_acceptance_contract.py config.example.toml
git commit -m "test: accept autonomous CIGRE LCC builds"
```

Do not commit generated licensed workspace projects, compiler output, logs containing local paths, or the acceptance report itself.

## Task 17: Documentation, Release Claims, And Complete Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_changelog.py`
- Modify: `tests/test_tool_inventory.py`

- [ ] **Step 1: Write failing documentation assertions**

Assert README text contains all four tool names, PSCAD 4.6.2, fixed parameters, one-pole limitation, confirmation and plan-hash requirements, original companion library, workspace writes, and the four capability levels `planned`, `built`, `simulated`, and `accepted`.

- [ ] **Step 2: Update English and Chinese documentation**

Document one concise end-to-end invocation sequence. State explicitly that `poles=2`, user-rated design, PSCAD 5.x, fault acceptance, and MMC construction are unavailable. Do not describe the feature as autonomous until the licensed test from Task 16 has passed on the implementation commit.

- [ ] **Step 3: Run all focused LCC tests**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_lcc_schema.py tests\test_lcc_assets.py tests\test_lcc_catalog.py tests\test_lcc_routing.py tests\test_lcc_planner.py tests\test_lcc_project_graph.py tests\test_lcc_validator.py tests\test_lcc_acceptance.py tests\test_lcc_journal.py tests\test_lcc_executor.py tests\test_lcc_builder_service.py tests\test_lcc_profile.py tests\test_lcc_tools.py tests\test_lcc_asset_audit.py tests\test_lcc_production_assets.py tests\test_lcc_real_acceptance_contract.py -q
```

Expected: all focused nonlicensed tests pass.

- [ ] **Step 4: Run the complete default suite and static verification**

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m compileall -q pscad_mcp tests scripts
& .\scripts\verify_package.ps1
git diff --check
git status --short
```

Expected: all tests and package verification pass, compilation exits `0`, `git diff --check` is silent, and status lists only intentional documentation edits before the final commit.

- [ ] **Step 5: Review the implementation against every design completion criterion**

Open `docs/superpowers/specs/2026-08-18-cigre-lcc-autonomous-builder-design.md` and record evidence for each completion criterion in the pull-request or branch summary. Treat any criterion without command output or licensed evidence as incomplete.

- [ ] **Step 6: Commit documentation**

```powershell
git add README.md docs/zh-CN/README.md CHANGELOG.md tests/test_changelog.py tests/test_tool_inventory.py
git commit -m "docs: document accepted CIGRE LCC builder"
```

- [ ] **Step 7: Request final code review**

Use `superpowers:requesting-code-review` against the complete branch. Address any correctness, safety, provenance, or missing-test finding before integration. Re-run Step 4 after every review-driven code change.

## Execution Checkpoints

- **Checkpoint A, after Task 6:** The repository can validate blueprints, assets, routes, PSCX graphs, and structure without PSCAD.
- **Checkpoint B, after Task 12:** The four MCP tools work end to end against a recording fake service with deterministic plans and contained failures.
- **Checkpoint C, after Task 15:** The original library, production blueprint, golden data, and all hashes survive wheel installation.
- **Checkpoint D, after Task 16:** A licensed PSCAD 4.6.2 run has created and accepted the model from an empty case.
- **Checkpoint E, after Task 17:** Full tests, packaging, documentation, and review are complete.
