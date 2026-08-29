# CI Schema Metadata Compatibility Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve model-facing descriptions for complex tool arguments on Python 3.10 while keeping the existing FastMCP schema contract unchanged.

**Architecture:** Resolve descriptions from the original callable annotations in `register_tool`, pass them into `_register_with_original_result`, and use them only when generated schema metadata is missing. A focused unit test will simulate a generated model with no field metadata; the existing tool-catalog contract remains the end-to-end regression test.

**Tech Stack:** Python 3.10+, FastMCP/MCP 1.29+, Pydantic 2, pytest.

---

### Task 1: Add a failing registration regression test

**Files:**
- Modify: `tests/test_tool_catalog.py` (imports and registration compatibility tests)

- [ ] **Step 1: Write the failing test**

Add the private helper import and this test after the duplicate-registration tests:

```python
from typing import Any

from pscad_mcp.tools.registration import (
    _register_with_original_result,
    register_tool,
)


def test_registration_uses_original_parameter_description_when_model_metadata_is_empty():
    async def bare_set_component_parameters(
        project_name: str,
        component_id: int,
        parameters: dict[str, Any],
    ) -> str:
        return f"{project_name}:{component_id}:{parameters}"

    bare_set_component_parameters.__name__ = "set_component_parameters"
    server = FastMCP("metadata-fallback")
    expected = 'Component parameter_name keys mapped to values; example {"R": 1.0}.'

    _register_with_original_result(
        server,
        bare_set_component_parameters,
        parameter_descriptions={"parameters": expected},
    )

    tool = server._tool_manager.get_tool("set_component_parameters")
    assert tool is not None
    assert tool.parameters["properties"]["parameters"]["description"] == expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest -q tests/test_tool_catalog.py::test_registration_uses_original_parameter_description_when_model_metadata_is_empty
```

Expected: `TypeError` because `_register_with_original_result` does not yet accept `parameter_descriptions`.

### Task 2: Implement explicit annotation description propagation

**Files:**
- Modify: `pscad_mcp/tools/registration.py:163-185, 300-315`

- [ ] **Step 1: Extend schema repair with an explicit description mapping**

Change the helper signature and description selection to:

```python
def _register_with_original_result(
    mcp: FastMCP,
    guarded: Callable[..., Any],
    *,
    parameter_descriptions: Mapping[str, str | None] | None = None,
) -> None:
```

Inside the existing `properties` loop, use the generated model field first,
then the explicit mapping, then the current wrapper-annotation fallback:

```python
                field = tool.fn_metadata.arg_model.model_fields.get(parameter.name)
                description = getattr(field, "description", None)
                if not isinstance(description, str):
                    description = (parameter_descriptions or {}).get(parameter.name)
                if not isinstance(description, str):
                    description = _annotation_description(parameter.annotation)
```

- [ ] **Step 2: Pass descriptions resolved before wrapping the callable**

After `resolved_parameters` is built in `register_tool`, add:

```python
    parameter_descriptions = {
        parameter.name: _annotation_description(parameter.annotation)
        for parameter in resolved_parameters
    }
```

Update the registration call to:

```python
    _register_with_original_result(
        mcp,
        guarded,
        parameter_descriptions=parameter_descriptions,
    )
```

- [ ] **Step 3: Run the focused regression and existing contract tests**

Run:

```powershell
python -m pytest -q tests/test_tool_catalog.py::test_registration_uses_original_parameter_description_when_model_metadata_is_empty tests/test_tool_catalog.py::test_complex_inputs_have_model_facing_shape_examples
```

Expected: both tests pass.

### Task 3: Verify the full CI-equivalent contract

**Files:**
- No additional files.

- [ ] **Step 1: Run the complete pytest suite**

Run `python -m pytest -q`; expected result is zero failures.

- [ ] **Step 2: Run the CI correctness and packaging checks**

Run the following commands from the repository root:

```powershell
python -m ruff check --select E9,F63,F7,F82 pscad_mcp tests
.\scripts\verify_package.ps1
python -m compileall -q pscad_mcp tests
python -m pip check
python -c "from pscad_mcp.main import create_server; tools=create_server()._tool_manager.list_tools(); print(len(tools), len({tool.name for tool in tools})); assert len(tools) == len({tool.name for tool in tools}) == 97"
```

Expected: every command exits with status 0; the inventory command prints `97 97`.

- [ ] **Step 3: Inspect the final diff and status**

Run `git diff --check` and `git status --short`; expected no whitespace errors and only the intended registration/test changes beyond the already committed design and plan documents.
