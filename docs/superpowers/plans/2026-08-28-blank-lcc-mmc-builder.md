# Blank LCC and MMC Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose deterministic blank-project LCC and full-bridge MMC builders with explicit plans, staged lifecycle tools, component-source evidence, and model-specific fault acceptance contracts.

**Architecture:** Reuse the existing fixed LCC and Stage-A MMC planners/executors behind thin blank-builder request adapters. Add shared resolver/factory records for source precedence and workspace containment, and represent full-bridge MMC as a selectable capability contract so half-bridge can be added without reusing its acceptance. Keep all mutating work behind exact plan hashes and confirmation, with existing journal/lease/atomic publication behavior.

**Tech Stack:** Python 3.10+, dataclasses, existing `BackendError`/`PathPolicy`, packaged JSON/PSLX assets, FastMCP registrations, pytest/pytest-asyncio.

---

### Task 1: Add shared blank-builder contracts and resolver

**Files:**
- Create: `pscad_mcp/hvdc/builders/common/blank.py`
- Modify: `pscad_mcp/hvdc/builders/common/__init__.py`
- Test: `tests/test_blank_builder_common.py`

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

import pytest

from pscad_mcp.hvdc.builders.common.blank import (
    BlankProjectFactory,
    ComponentLibraryResolver,
    DefinitionResolution,
)
from pscad_mcp.core.backend.base import BackendError


def test_resolver_prefers_master_and_records_hashes(tmp_path: Path):
    resolver = ComponentLibraryResolver(
        master={"master:source": {"ports": ["A"]}},
        companion={"companion:bridge": {"ports": ["DC_POS"], "sha256": "abc"}},
    )
    master = resolver.resolve("master:source")
    companion = resolver.resolve("companion:bridge")
    assert isinstance(master, DefinitionResolution)
    assert master.source == "master"
    assert companion.source == "companion"
    assert companion.source_hash == "abc"


def test_resolver_fails_closed_for_missing_definition():
    with pytest.raises(BackendError) as raised:
        ComponentLibraryResolver(master={}, companion={}).resolve("missing:item")
    assert raised.value.code == "BLANK_DEFINITION_MISSING"


def test_factory_rejects_existing_destination_and_never_overwrites(tmp_path: Path):
    target = tmp_path / "case.pscx"
    target.write_text("existing", encoding="ascii")
    factory = BlankProjectFactory(tmp_path)
    with pytest.raises(BackendError) as raised:
        factory.plan("case")
    assert raised.value.code == "BLANK_BUILD_CONFLICT"
    assert target.read_text(encoding="ascii") == "existing"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_blank_builder_common.py`
Expected: FAIL with `ModuleNotFoundError` for `pscad_mcp.hvdc.builders.common.blank`.

- [ ] **Step 3: Implement the minimal contracts**

Implement frozen `DefinitionResolution` and `BlankProjectFactory` records. Resolver lookup order is `master` then `companion`, and factory planning resolves a contained `<project>.pscx` path and raises `BLANK_BUILD_CONFLICT` when either the filename or symlink already exists. Export both symbols from `common/__init__.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_blank_builder_common.py`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pscad_mcp/hvdc/builders/common/blank.py pscad_mcp/hvdc/builders/common/__init__.py tests/test_blank_builder_common.py
git commit -m "feat: add blank builder resolver and factory contracts"
```

### Task 2: Add blank LCC request adapter and fault acceptance

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/blank.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/acceptance.py`
- Create: `tests/test_blank_lcc_builder.py`

- [ ] **Step 1: Write failing tests**

```python
import asyncio

from pscad_mcp.hvdc.builders.lcc.blank import BlankLccRequest, plan_blank_lcc
from pscad_mcp.hvdc.builders.lcc.acceptance import evaluate_commutation_fault


def test_blank_lcc_request_reserves_ratings_and_operation_modes(tmp_path):
    request = BlankLccRequest.from_dict({
        "project_name": "LCC_BLANK",
        "folder": str(tmp_path),
        "topology": "single_pole_12_pulse",
        "ratings": {"dc_voltage_kv": 500.0, "power_mw": 1000.0},
        "operation_modes": ["rectifier", "inverter"],
    })
    planned = plan_blank_lcc(request, workspace_root=tmp_path, inventory={"version": "4.6.2"})
    assert planned["request"]["ratings"]["power_mw"] == 1000.0
    assert planned["fault_events"][0]["kind"] == "inverter_ac_disturbance"


def test_lcc_commutation_fault_requires_indication_bounded_response_and_recovery():
    result = evaluate_commutation_fault({
        "disturbance": True,
        "failure_indication": True,
        "dc_current_peak_ka": 2.0,
        "dc_current_limit_ka": 3.0,
        "recovered": True,
    })
    assert result["verdict"] == "PASS"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_blank_lcc_builder.py`
Expected: FAIL because the blank request adapter and fault evaluator do not exist.

- [ ] **Step 3: Implement the adapter and evaluator**

Parse `topology`, `ratings`, `operation_modes`, and future parameterization fields into an immutable request; delegate canonical fixed ratings and component/net/output expansion to `LccPlanRequest`/`create_plan`; append an explicit inverter-side AC disturbance event and include source hashes in the returned plan. Implement `evaluate_commutation_fault` as a pure fail-closed check over disturbance, indication, finite bounded current, and recovery, returning a JSON-safe verdict and per-check results.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_blank_lcc_builder.py tests/test_lcc_acceptance.py`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add pscad_mcp/hvdc/builders/lcc/blank.py pscad_mcp/hvdc/builders/lcc/acceptance.py tests/test_blank_lcc_builder.py
git commit -m "feat: add blank LCC request and commutation fault contract"
```

### Task 3: Add full-bridge MMC topology contract and fault acceptance

**Files:**
- Modify: `pscad_mcp/hvdc/builders/mmc/models.py`
- Modify: `pscad_mcp/hvdc/builders/mmc/planner.py`
- Modify: `pscad_mcp/hvdc/builders/mmc/schema.py`
- Modify: `pscad_mcp/hvdc/builders/mmc/acceptance.py`
- Create: `tests/test_blank_mmc_builder.py`

- [ ] **Step 1: Write failing tests**

```python
from pscad_mcp.hvdc.builders.mmc.acceptance import evaluate_dc_fault_blocking
from pscad_mcp.hvdc.builders.mmc.models import SubmoduleTopology


def test_full_bridge_declares_intrinsic_dc_fault_blocking():
    assert SubmoduleTopology.FULL_BRIDGE.value == "full_bridge"
    assert SubmoduleTopology.capabilities(SubmoduleTopology.FULL_BRIDGE)["intrinsic_dc_fault_blocking"] is True
    assert SubmoduleTopology.capabilities(SubmoduleTopology.HALF_BRIDGE)["intrinsic_dc_fault_blocking"] is False


def test_mmc_dc_fault_acceptance_requires_negative_insertion_block_and_recovery():
    result = evaluate_dc_fault_blocking({
        "fault_applied": True,
        "negative_voltage_inserted": True,
        "fault_current_peak_ka": 1.5,
        "fault_current_limit_ka": 2.0,
        "blocked": True,
        "recovered": True,
    }, topology=SubmoduleTopology.FULL_BRIDGE)
    assert result["verdict"] == "PASS"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_blank_mmc_builder.py`
Expected: FAIL because `SubmoduleTopology` and `evaluate_dc_fault_blocking` are undefined.

- [ ] **Step 3: Implement the topology contract**

Add `SubmoduleTopology` with `FULL_BRIDGE` and `HALF_BRIDGE`, a capability map, and request parsing that defaults to full bridge while preserving the existing AVM planner API. Include the selected topology and capability declaration in `MmcBlueprint.provenance`/plan metadata. Implement pure DC-fault acceptance; reject full-bridge-only acceptance when topology is half bridge with a structured `NOT_APPLICABLE` verdict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_blank_mmc_builder.py tests/test_mmc_acceptance.py tests/test_mmc_schema.py`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add pscad_mcp/hvdc/builders/mmc/models.py pscad_mcp/hvdc/builders/mmc/planner.py pscad_mcp/hvdc/builders/mmc/schema.py pscad_mcp/hvdc/builders/mmc/acceptance.py tests/test_blank_mmc_builder.py
git commit -m "feat: add MMC submodule topology capability contract"
```

### Task 4: Register blank lifecycle MCP tools and catalog metadata

**Files:**
- Create: `pscad_mcp/tools/blank_builder_tools.py`
- Modify: `pscad_mcp/main.py`
- Modify: `pscad_mcp/tools/catalog.py`
- Create: `tests/test_blank_builder_tools.py`

- [ ] **Step 1: Write failing tests**

```python
from pscad_mcp.main import create_server


def test_blank_lifecycle_tools_are_registered():
    names = {tool.name for tool in create_server(environ={})._tool_manager.list_tools()}
    assert {
        "plan_blank_lcc_model", "build_blank_lcc_model", "get_blank_lcc_build_status", "validate_blank_lcc_model",
        "plan_blank_mmc_model", "build_blank_mmc_model", "get_blank_mmc_build_status", "validate_blank_mmc_model",
    } <= names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_blank_builder_tools.py`
Expected: FAIL because the new tool names are not registered.

- [ ] **Step 3: Implement wrappers and metadata**

Expose request-dict wrappers with exact plan/build/status/validate lifecycle names. LCC wrappers use `LccBuilderService`; MMC wrappers use `MmcBuilderService`; both require `confirm=true` for builds and pass the exact plan hash. Add all eight tools to `TOOL_SPECS` with read-only/idempotent flags on plan/status/validate and legacy-only build support where the current backend requires it. Register the module in `create_server`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_blank_builder_tools.py tests/test_lcc_tools.py tests/test_mmc_parametric_tools.py tests/test_tool_catalog.py`
Expected: all tests pass and existing tool-name equality remains intact.

- [ ] **Step 5: Commit**

```bash
git add pscad_mcp/tools/blank_builder_tools.py pscad_mcp/main.py pscad_mcp/tools/catalog.py tests/test_blank_builder_tools.py
git commit -m "feat: register blank LCC and MMC lifecycle tools"
```

### Task 5: Full verification and branch handoff

**Files:**
- Modify: `CHANGELOG.md` if the repository release policy requires an entry
- Test: existing full test suite

- [ ] **Step 1: Run focused regression tests**

Run: `pytest -q tests/test_blank_builder_common.py tests/test_blank_lcc_builder.py tests/test_blank_mmc_builder.py tests/test_blank_builder_tools.py`
Expected: 0 failures.

- [ ] **Step 2: Run the complete suite and static checks**

Run: `pytest -q; ruff check pscad_mcp tests`
Expected: pytest exits 0 and Ruff reports no errors.

- [ ] **Step 3: Inspect the final diff and branch state**

Run: `git diff --check; git status --short --branch; git diff main...HEAD --stat`
Expected: no whitespace errors, changes are confined to the blank-builder implementation and tests, and the branch is `codex/blank-lcc-mmc-builder`.

- [ ] **Step 4: Commit any required documentation update**

```bash
git add CHANGELOG.md
git commit -m "docs: record blank builder lifecycle tools"
```

