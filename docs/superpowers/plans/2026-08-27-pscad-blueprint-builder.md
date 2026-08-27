# PSCAD Blueprint Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generic, profile-driven PSCAD builder that plans from audited blueprints, mutates only an isolated staging package, independently validates evidence, and publishes only accepted results.

**Architecture:** Add a domain-neutral `pscad_mcp.builders.blueprint` package whose pure schema, planner, acceptance, and output modules do not depend on vendor APIs. `executor.py` is the only mutation coordinator, `validator.py` independently re-reads persisted evidence, and `service.py` owns exact-plan confirmation, asynchronous records, leases, quarantine, and publication.

**Tech Stack:** Python 3.10+, frozen dataclasses, `asyncio`, standard-library JSON/XML/hash/path APIs, existing `PscadService`, `PathPolicy`, FastMCP registration, pytest/pytest-asyncio.

---

### Task 1: Immutable Records and Strict Blueprint Schema

**Files:**
- Create: `pscad_mcp/builders/__init__.py`
- Create: `pscad_mcp/builders/blueprint/__init__.py`
- Create: `pscad_mcp/builders/blueprint/models.py`
- Create: `pscad_mcp/builders/blueprint/schema.py`
- Test: `tests/test_blueprint_schema.py`

- [ ] **Step 1: Write failing schema and immutability tests**

```python
def test_parse_blueprint_returns_an_immutable_json_safe_record(valid_blueprint):
    parsed = parse_blueprint(valid_blueprint)
    assert parsed.identity.name == "breaker-copy-v1"
    assert parsed.operations[0].operation_id == "op-001"
    assert parsed.to_dict() == valid_blueprint
    with pytest.raises(TypeError):
        parsed.publication["delivery_package"] = False


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(extra={}),
    lambda value: value["identity"].update(schema_version=2),
    lambda value: value["operations"].append({"sequence": 1}),
])
def test_parse_blueprint_rejects_unknown_or_invalid_contracts(valid_blueprint, mutation):
    mutation(valid_blueprint)
    with pytest.raises(BackendError) as raised:
        parse_blueprint(valid_blueprint)
    assert raised.value.code == "BLUEPRINT_SCHEMA_INVALID"
```

- [ ] **Step 2: Run the schema tests and verify import failure**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_schema.py`

Expected: FAIL because `pscad_mcp.builders.blueprint` does not exist.

- [ ] **Step 3: Implement exact top-level validation and frozen JSON records**

```python
@dataclass(frozen=True)
class Blueprint:
    identity: BlueprintIdentity
    source_package: Mapping[str, Any]
    operations: tuple[BlueprintOperation, ...]
    acceptance: Mapping[str, Any]
    publication: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))


def parse_blueprint(value: Any) -> Blueprint:
    require_exact_keys(value, {"identity", "source_package", "operations", "acceptance", "publication"}, "blueprint")
    identity = parse_identity(value["identity"])
    operations = parse_operations(value["operations"])
    return Blueprint(identity, freeze(value["source_package"]), operations, freeze(value["acceptance"]), freeze(value["publication"]))
```

- [ ] **Step 4: Run schema tests and confirm they pass**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_schema.py`

Expected: PASS.

- [ ] **Step 5: Commit the schema slice**

```powershell
git add pscad_mcp/builders tests/test_blueprint_schema.py
git commit -m "feat: add strict PSCAD blueprint schema"
```

### Task 2: Asset Loading, Source Audit, Live Inventory, and Deterministic Planning

**Files:**
- Create: `pscad_mcp/builders/blueprint/assets.py`
- Create: `pscad_mcp/builders/blueprint/inventory.py`
- Create: `pscad_mcp/builders/blueprint/planner.py`
- Test: `tests/test_blueprint_assets.py`
- Test: `tests/test_blueprint_planner.py`

- [ ] **Step 1: Write failing tests for containment, package hashes, selector resolution, and plan stability**

```python
def test_plan_is_side_effect_free_and_hashes_the_complete_contract(tmp_path, valid_blueprint, live_inventory):
    source = write_source_package(tmp_path)
    before = hash_tree(source)
    first = create_plan(valid_blueprint, source, "BuiltCase", live_inventory, PathPolicy(str(tmp_path)))
    second = create_plan(valid_blueprint, source, "BuiltCase", live_inventory, PathPolicy(str(tmp_path)))
    assert first.plan_hash == second.plan_hash
    assert first.to_dict() == second.to_dict()
    assert hash_tree(source) == before


def test_plan_rejects_ambiguous_or_unresolved_mutation_targets(tmp_path, valid_blueprint, live_inventory):
    source = write_source_package(tmp_path)
    live_inventory["components"].append(dict(live_inventory["components"][0]))
    with pytest.raises(BackendError) as raised:
        create_plan(valid_blueprint, source, "BuiltCase", live_inventory, PathPolicy(str(tmp_path)))
    assert raised.value.code in {"BLUEPRINT_SELECTOR_AMBIGUOUS", "BLUEPRINT_TARGET_UNRESOLVED"}
```

- [ ] **Step 2: Run planning tests and verify missing implementations fail**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_assets.py tests\test_blueprint_planner.py`

Expected: FAIL on missing asset/planner imports.

- [ ] **Step 3: Implement canonical hashing and resolved operation planning**

```python
def canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_plan(blueprint_value, source_path, target_name, inventory, path_policy, overrides=None):
    blueprint = parse_blueprint(blueprint_value)
    source = audit_source_package(blueprint, source_path, path_policy)
    resolved = resolve_operations(blueprint.operations, inventory, overrides or {})
    unsigned = plan_payload(blueprint, source, target_name, inventory, resolved)
    return BlueprintPlan.from_payload(unsigned, canonical_hash(unsigned))
```

- [ ] **Step 4: Run planning tests and the existing path safety suite**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_assets.py tests\test_blueprint_planner.py tests\test_path_safety.py`

Expected: PASS.

- [ ] **Step 5: Commit deterministic planning**

```powershell
git add pscad_mcp/builders/blueprint tests/test_blueprint_assets.py tests/test_blueprint_planner.py
git commit -m "feat: plan audited PSCAD blueprint builds"
```

### Task 3: Generic Output Parsing and Acceptance Rules

**Files:**
- Create: `pscad_mcp/builders/blueprint/output.py`
- Create: `pscad_mcp/builders/blueprint/acceptance.py`
- Test: `tests/test_blueprint_output.py`
- Test: `tests/test_blueprint_acceptance.py`

- [ ] **Step 1: Write failing table-driven rule and segmented-output tests**

```python
@pytest.mark.parametrize(("rule", "values", "passed"), [
    ({"kind": "all_finite"}, [1.0, 2.0], True),
    ({"kind": "inclusive_range", "minimum": 0.0, "maximum": 2.0}, [0.0, 2.0], True),
    ({"kind": "allowed_states", "values": [0, 1]}, [0, 1, 1], True),
    ({"kind": "transition_count", "count": 2}, [0, 1, 0], True),
    ({"kind": "monotonic", "direction": "increasing"}, [1, 3, 2], False),
])
def test_acceptance_rules_are_deterministic(rule, values, passed):
    assert evaluate_rule(rule, values)["passed"] is passed


def test_read_outputs_combines_numbered_segments_and_rejects_metadata_drift(tmp_path):
    write_inf_and_segments(tmp_path)
    channels = read_output_dataset(tmp_path / "case.inf")
    assert channels["Main/VDC"]["values"] == [1.0, 2.0, 3.0]
```

- [ ] **Step 2: Run the output and acceptance tests to verify RED**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_output.py tests\test_blueprint_acceptance.py`

Expected: FAIL because the modules are absent.

- [ ] **Step 3: Implement finite parsing, rule validation, source-class boundaries, and explicit flags**

```python
def evaluate_acceptance(contract, channels, *, trusted_source_classes):
    results = tuple(evaluate_rule(rule, select_values(rule, channels)) for rule in contract.rules)
    run_through = all(item["passed"] for item in results if item["required"])
    physical = run_through and all(
        item["source_class"] in trusted_source_classes
        for item in results
        if item["physical"]
    )
    return {"rules": list(results), "run_through_acceptance": run_through, "physical_acceptance": physical}
```

- [ ] **Step 4: Run focused acceptance/output tests**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_output.py tests\test_blueprint_acceptance.py`

Expected: PASS with non-finite values and provisional physical thresholds rejected.

- [ ] **Step 5: Commit evidence evaluation**

```powershell
git add pscad_mcp/builders/blueprint/output.py pscad_mcp/builders/blueprint/acceptance.py tests/test_blueprint_output.py tests/test_blueprint_acceptance.py
git commit -m "feat: evaluate generic blueprint outputs"
```

### Task 4: Journal, State Machine, and Independent Validation

**Files:**
- Create: `pscad_mcp/builders/blueprint/journal.py`
- Create: `pscad_mcp/builders/blueprint/validator.py`
- Test: `tests/test_blueprint_journal.py`
- Test: `tests/test_blueprint_validator.py`

- [ ] **Step 1: Write failing tests for state transitions, atomic evidence, source integrity, and graph drift**

```python
def test_terminal_failure_cannot_transition_to_acceptance():
    with pytest.raises(BackendError) as raised:
        next_state(BlueprintBuildState.FAILED, BlueprintBuildState.ACCEPTANCE_PASSED)
    assert raised.value.code == "BLUEPRINT_STATE_INVALID"


def test_validator_does_not_trust_executor_flags(tmp_path, planned_build):
    tamper_with_saved_component(tmp_path)
    report = validate_staging(planned_build, tmp_path)
    assert report["structure_acceptance"] is False
    assert report["run_through_acceptance"] is False
```

- [ ] **Step 2: Run journal and validator tests to verify RED**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_journal.py tests\test_blueprint_validator.py`

Expected: FAIL on missing journal and validator APIs.

- [ ] **Step 3: Implement append-only JSONL, atomic reports, legal transitions, and independent checks**

```python
def append_event(path: Path, event: Mapping[str, Any]) -> None:
    line = json.dumps(json_safe(event), sort_keys=True, allow_nan=False) + "\n"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def validate_staging(plan, staging_root, inspector, output_reader):
    source = verify_source_hashes(plan.source_manifest)
    graph = inspector.read_graph(staging_root / plan.entry_point)
    structure = compare_graph(plan, graph)
    outputs = output_reader.discover(staging_root)
    return build_validation_report(source, structure, outputs, plan.acceptance)
```

- [ ] **Step 4: Run validator tests with existing project graph tests**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_journal.py tests\test_blueprint_validator.py tests\test_lcc_project_graph.py`

Expected: PASS.

- [ ] **Step 5: Commit independent validation**

```powershell
git add pscad_mcp/builders/blueprint/journal.py pscad_mcp/builders/blueprint/validator.py tests/test_blueprint_journal.py tests/test_blueprint_validator.py
git commit -m "feat: validate blueprint build evidence"
```

### Task 5: Isolated Mutation Executor

**Files:**
- Create: `pscad_mcp/builders/blueprint/executor.py`
- Create: `tests/blueprint_builder_fakes.py`
- Test: `tests/test_blueprint_executor.py`

- [ ] **Step 1: Write failing tests for copy-before-write, ordered operations, immediate read-back, reload, lifecycle, and quarantine**

```python
@pytest.mark.asyncio
async def test_executor_mutates_only_the_build_staging_copy(tmp_path, plan):
    before = hash_tree(Path(plan.source_path))
    service = RecordingBlueprintPscadService()
    record = await execute_build(plan, service, tmp_path, build_id="build-001", poll_interval_s=0)
    assert hash_tree(Path(plan.source_path)) == before
    assert record.state is BlueprintBuildState.ACCEPTANCE_PASSED
    assert call_names(service) == expected_lifecycle_calls()


@pytest.mark.asyncio
async def test_executor_stops_on_a_readback_mismatch_and_quarantines(tmp_path, plan):
    service = RecordingBlueprintPscadService(location_drift=True)
    record = await execute_build(plan, service, tmp_path, build_id="build-drift", poll_interval_s=0)
    assert record.state is BlueprintBuildState.QUARANTINED
    assert record.error["code"] == "BLUEPRINT_READBACK_MISMATCH"
```

- [ ] **Step 2: Run executor tests and verify RED**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_executor.py`

Expected: FAIL because `execute_build` is absent.

- [ ] **Step 3: Implement operation dispatch and fail-closed lifecycle**

```python
async def execute_operation(context, operation):
    handler = OPERATION_HANDLERS[operation.kind]
    requested = operation.to_dict()
    observed = await handler(context, operation)
    verify_readback(operation, observed)
    context.journal.operation(operation.operation_id, requested, observed)


async def execute_build(plan, service, workspace_root, *, build_id, journal=None, poll_interval_s=0.1):
    staging = copy_source_package(plan, workspace_root, build_id)
    for operation in plan.operations:
        await execute_operation(BuildContext(service, staging, plan), operation)
    evidence = await save_reload_compile_simulate_and_validate(service, plan, staging, journal, poll_interval_s)
    return accepted_record(build_id, plan, staging, evidence)
```

- [ ] **Step 4: Run executor, service-boundary, and concurrency tests**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_executor.py tests\test_canvas_service_boundary.py tests\test_component_service_boundary.py tests\test_concurrency.py`

Expected: PASS.

- [ ] **Step 5: Commit isolated execution**

```powershell
git add pscad_mcp/builders/blueprint/executor.py tests/blueprint_builder_fakes.py tests/test_blueprint_executor.py
git commit -m "feat: execute isolated PSCAD blueprint builds"
```

### Task 6: Asynchronous Builder Service and Publication Gate

**Files:**
- Create: `pscad_mcp/builders/blueprint/service.py`
- Test: `tests/test_blueprint_service.py`

- [ ] **Step 1: Write failing tests for exact confirmation, stale plans, async status, lease conflict, independent validation, and publication scope**

```python
@pytest.mark.asyncio
async def test_build_requires_confirmation_of_the_exact_current_plan(tmp_path, service):
    source = write_source_package(tmp_path)
    plan = service.plan_project(valid_blueprint(), str(source), "BuiltCase")
    with pytest.raises(ConfirmationRequired):
        await service.build_project(plan["plan_hash"], valid_blueprint(), str(source), "BuiltCase", confirm=False)
    with pytest.raises(BackendError) as raised:
        await service.build_project("0" * 64, valid_blueprint(), str(source), "BuiltCase", confirm=True)
    assert raised.value.code == "BLUEPRINT_PLAN_STALE"


@pytest.mark.asyncio
async def test_publication_copies_only_declared_evidence_after_acceptance(tmp_path, service):
    source = write_source_package(tmp_path)
    plan = service.plan_project(valid_blueprint(), str(source), "BuiltCase")
    started = await service.build_project(plan["plan_hash"], valid_blueprint(), str(source), "BuiltCase", confirm=True)
    await service.wait_for_build(started["build_id"])
    status = service.get_build_status(started["build_id"])
    assert status["published"] is True
    assert status["publication_scope"] == "model_run_through_only"
```

- [ ] **Step 2: Run service tests and verify RED**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_service.py`

Expected: FAIL because `BlueprintBuilderService` does not exist.

- [ ] **Step 3: Implement cached plans, constant-time hash comparison, tasks, leases, records, quarantine, validation, and publication**

```python
async def build_project(self, expected_plan_hash, request, *, confirm=False):
    if not confirm:
        raise ConfirmationRequired("build_pscad_project")
    plan = self._create_plan(request)
    if not secrets.compare_digest(plan.plan_hash, expected_plan_hash):
        raise self._plan_stale(expected_plan_hash, plan.plan_hash)
    return await self._start_build(plan)


def validate_project_build(self, *, build_id=None, staging_path=None):
    plan, staging = self._resolve_validation_target(build_id, staging_path)
    report = self.validator(plan, staging, self.pscad_service)
    self._write_validation_report(staging, report)
    return report
```

- [ ] **Step 4: Run service and existing LCC service tests**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_service.py tests\test_lcc_builder_service.py tests\test_lcc_journal.py`

Expected: PASS without changing existing LCC behavior.

- [ ] **Step 5: Commit orchestration and publication**

```powershell
git add pscad_mcp/builders/blueprint/service.py tests/test_blueprint_service.py
git commit -m "feat: orchestrate PSCAD blueprint builds"
```

### Task 7: MCP Tools, Licensed Contract, Packaging, and Documentation

**Files:**
- Create: `pscad_mcp/tools/blueprint_tools.py`
- Modify: `pscad_mcp/main.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_tool_inventory.py`
- Modify: `tests/test_tool_backend_matrix.py`
- Create: `tests/test_blueprint_tools.py`
- Create: `tests/test_blueprint_real_acceptance.py`
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `docs/zh-CN/2026-08-25-breaker-engineering-package-auto-modeling-workdoc.md`
- Modify: `docs/acceptance-status.json`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write failing registration, wrapper, package-data, and opt-in licensed tests**

```python
BLUEPRINT_TOOLS = {
    "plan_pscad_project_build",
    "build_pscad_project",
    "get_pscad_project_build_status",
    "validate_pscad_project_build",
}


def test_blueprint_tools_are_registered():
    names = {tool.name for tool in create_server()._tool_manager.list_tools()}
    assert BLUEPRINT_TOOLS <= names
    assert len(names) == 87


@pytest.mark.skipif(os.getenv("PSCAD_BLUEPRINT_LIVE") != "1", reason="requires explicit licensed PSCAD opt-in")
def test_blueprint_builder_live_acceptance():
    run_live_acceptance_from_environment()
```

- [ ] **Step 2: Run registration and package tests to verify RED**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_tools.py tests\test_tool_inventory.py tests\test_tool_backend_matrix.py tests\test_packaging_metadata.py`

Expected: FAIL because the four tools and blueprint package data are not registered.

- [ ] **Step 3: Add thin wrappers, registration, package data, documentation, and acceptance status**

```python
async def plan_pscad_project_build(blueprint, source_package_path, target_name, parameter_overrides=None):
    return _service().plan_project(blueprint, source_package_path, target_name, parameter_overrides)


def register_blueprint_tools(mcp: FastMCP) -> None:
    for function in (plan_pscad_project_build, build_pscad_project, get_pscad_project_build_status, validate_pscad_project_build):
        register_tool(mcp, function)
```

- [ ] **Step 4: Run focused tests, then the complete default suite**

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q tests\test_blueprint_tools.py tests\test_tool_inventory.py tests\test_tool_backend_matrix.py tests\test_packaging_metadata.py tests\test_blueprint_real_acceptance.py`

Expected: PASS with the licensed test skipped unless explicitly enabled.

Run: `$env:PYTHONPATH='.;tests'; .\.venv\Scripts\python.exe -m pytest -q`

Expected: all default tests pass; licensed acceptance remains explicitly skipped.

- [ ] **Step 5: Audit changes and commit the integrated feature**

```powershell
git diff --check
git status --short
git add pscad_mcp/main.py pscad_mcp/tools/blueprint_tools.py pyproject.toml tests README.md docs CHANGELOG.md
git commit -m "feat: expose generic PSCAD blueprint builder"
```
