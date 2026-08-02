# PSCAD 4.6.2 Simulation Set Management Design

**Date:** 2026-08-02
**Status:** Approved for implementation
**Primary target:** PSCAD 4.6.2 x64 with `mhrc.automation` 1.2.4

## Goal

Complete the simulation-set workflow so an MCP client can create a set, add
loaded projects, inspect and configure tasks, run the set, remove tasks, and
delete the set without using the PSCAD GUI.

The implementation must preserve the existing 53 tool signatures, extend the
public contract to 60 uniquely named tools, retain the service/backend safety
boundary, and verify every PSCAD mutation through a read-back postcondition.

After implementation and verification, the MCP server will also be registered
in the local Codex configuration for use from a new Codex task.

## Scope

This iteration adds these seven MCP tools:

1. `create_simulation_set`
2. `remove_simulation_set`
3. `list_simulation_set_tasks`
4. `remove_tasks_from_set`
5. `get_simulation_task_parameters`
6. `set_simulation_task_parameters`
7. `get_simulation_set_details`

It also strengthens the existing `list_simulation_sets`,
`run_simulation_set`, and `add_task_to_set` implementations with existence,
vendor-response, and postcondition checks where applicable. Their names and
parameters remain unchanged.

## Non-goals

This iteration does not add:

- project clean, unload, or build-modified tools;
- result filtering, statistics, or export;
- scenarios, global substitutions, or parameter sweeps;
- simulation-set rename or dependency mutation;
- external executable tasks;
- task ordering;
- PSCAD 5.x-only task fields such as `rank_snap`, `substitutions`, or layer
  overrides;
- attachment to an already-open PSCAD 4.6.2 GUI.

## Resource Model

Simulation sets belong to the PSCAD workspace, not to an individual project.
The new tools therefore do not accept `project_name`. A task identifies the
loaded project that the simulation set will run.

The existing three tools retain their redundant `project_name` argument for
backward compatibility. It remains a compatibility argument and must not be
presented as ownership of the simulation set.

```text
PSCAD Workspace
|-- CaseA
|-- CaseB
`-- Batch1
    |-- CaseA task
    `-- CaseB task
```

## Architecture

All new operations use the existing boundary:

```text
MCP tool
  -> PscadService validation and confirmation
  -> PscadBackend normalized protocol
  -> LegacyBackend or ModernBackend vendor calls
  -> read-back verification
  -> JSON-safe result
```

Tool modules remain thin. They must not import `mhrc.automation`, import
`mhi.pscad`, access a raw PSCAD proxy, or parse vendor XML. Vendor objects and
version-specific behavior stay inside backend implementations.

The backend protocol will gain normalized records for simulation sets and
tasks. No vendor proxy may cross the backend boundary.

## Public Interfaces

### Create a simulation set

```python
create_simulation_set(sim_set_name: str) -> dict
```

The name must be non-empty. Creation fails with `ALREADY_EXISTS` when the name
is already present. A successful result is the normalized set details after
the set has been found in a fresh workspace listing.

### Remove a simulation set

```python
remove_simulation_set(
    sim_set_name: str,
    confirm: bool = False,
) -> dict
```

Removal requires `confirm=true`. The set must exist before the command. The
result is `{"removed": sim_set_name}` only after a fresh listing confirms the
name is absent.

### List tasks

```python
list_simulation_set_tasks(sim_set_name: str) -> list[str]
```

The set must exist. Task names are returned in PSCAD order.

### Remove tasks

```python
remove_tasks_from_set(
    sim_set_name: str,
    task_names: list[str],
    confirm: bool = False,
) -> dict
```

Removal requires `confirm=true`. Empty input is invalid. Duplicate names are
deduplicated while preserving first occurrence order. Every requested task is
validated before the single vendor batch command. The result is
`{"removed": [...]}` only after all requested names are absent.

### Read task parameters

```python
get_simulation_task_parameters(
    sim_set_name: str,
    task_name: str,
) -> dict
```

The normalized PSCAD 4.6.2 response is:

```json
{
  "name": "CaseA",
  "namespace": "CaseA",
  "controlgroup": "",
  "volley": 1,
  "affinity": 1
}
```

`namespace` is read-only. `controlgroup`, `volley`, and `affinity` are the only
publicly writable fields in this iteration.

### Set task parameters

```python
set_simulation_task_parameters(
    sim_set_name: str,
    task_name: str,
    parameters: dict,
) -> dict
```

`parameters` must be non-empty. The validation rules are:

| Field | Rule |
|---|---|
| `controlgroup` | String; an empty string is allowed |
| `volley` | Integer greater than or equal to 1; booleans are rejected |
| `affinity` | Integer greater than or equal to 1; booleans are rejected |
| `namespace` | Read-only and rejected on write |
| Any other key | Rejected as unsupported |

The successful result is the complete normalized task record after read-back.

### Get simulation-set details

```python
get_simulation_set_details(sim_set_name: str) -> dict
```

The normalized result is:

```json
{
  "name": "Batch1",
  "depends_on": null,
  "tasks": ["CaseA", "CaseB"]
}
```

`depends_on` is informational. A backend that cannot report it returns `null`;
this iteration does not expose dependency mutation.

## Backend Mapping

### PSCAD 4.6.2 legacy backend

The implementation uses the installed Automation Library interfaces:

- `Workspace.list_simulation_sets()`
- `Workspace.create_simulation_set()`
- `Workspace.remove_simulation_set()`
- `Workspace.simulation_set()` or the equivalent application proxy
- `SimulationSet.list_tasks()`
- `SimulationSet.add_tasks()`
- `SimulationSet.remove_tasks()`
- `SimulationSet.task()`
- `Task.namespace()`
- `Task.controlgroup()`
- `Task.volley()`
- `Task.affinity()`

XML command responses are checked with the existing legacy response helpers.
A response with `success=false`, missing success metadata where success is
required, or malformed XML cannot be treated as success.

### Modern backend

The modern backend implements the same protocol through `mhi.pscad`. Modern
task parameters are normalized to the public record. If a public legacy field
cannot be represented by the installed modern API, reads return `null` and a
write returns `CAPABILITY_UNAVAILABLE` rather than silently ignoring the
field. PSCAD 5.x remains contract-tested only and is not part of this
iteration's real acceptance claim.

## Mutation Safety and Recovery

`remove_simulation_set` and `remove_tasks_from_set` require explicit
confirmation. All batch targets are validated before the first mutation.

Task parameter updates use a bounded restore strategy:

1. Read and retain the original values of all requested fields.
2. Validate every requested field and value before mutation.
3. Apply fields in deterministic key order.
4. Read back all requested fields.
5. If application or verification fails, restore every field already applied.
6. Read back again and report the actual state.

If restoration succeeds, the original operation error is returned with
rollback details. If restoration fails or the final state differs from the
original state, the operation returns `PARTIAL_COMPLETION` with requested,
original, observed, restored, and failed fields. The service never claims
atomicity that the vendor API does not provide.

## Errors

The stable error envelope remains unchanged. The new operations use these
codes:

- `ALREADY_EXISTS`: a create target is already present;
- `NOT_FOUND`: a set, task, or task project is absent;
- `CONFIRMATION_REQUIRED`: a destructive operation lacks `confirm=true`;
- `INVALID_ARGUMENT`: empty names, empty task lists, invalid types, read-only
  writes, or unsupported fields;
- `PSCAD_COMMAND_FAILED`: PSCAD explicitly rejected a command;
- `POSTCONDITION_FAILED`: the command returned but the expected state was not
  observed;
- `PARTIAL_COMPLETION`: a multi-field update could not be fully restored;
- `CAPABILITY_UNAVAILABLE`: the selected backend cannot represent an operation
  safely.

Errors include the operation, backend, set name, task name when relevant, and
bounded JSON-safe diagnostics. Raw XML, proxies, tracebacks, and unbounded
vendor values do not cross the MCP boundary.

## Automated Tests

The implementation follows test-driven development. Tests cover:

- exact registration of 60 unique tools;
- complete protocol conformance by both backends;
- tool-to-service routing without vendor access;
- workspace semantics of all new tools;
- create, duplicate create, delete, missing set, and failed postconditions;
- task listing, add verification, batch prevalidation, removal, and failed
  postconditions;
- strict task parameter allowlist, integer validation, boolean rejection, and
  read-only namespace rejection;
- successful parameter read-back;
- failed write with successful restoration;
- failed restoration with `PARTIAL_COMPLETION` details;
- legacy `success=false` response handling;
- modern contract normalization and capability errors;
- no regressions in the existing 53 tool signatures and behaviors.

The full non-live suite, `compileall`, `pip check`, and `git diff --check` must
pass before real acceptance.

## PSCAD 4.6.2 Acceptance

Acceptance is opt-in and uses a timestamped copy under
`D:\PSCAD-Workspace\acceptance`. It never modifies a public PSCAD example.

The new real workflow is:

1. Refuse to start when an unrelated PSCAD process is already running.
2. Launch one owned PSCAD 4.6.2 x64 instance.
3. Load a timestamped project copy.
4. Create a timestamped simulation set.
5. Add the copied project as a task.
6. Verify task listing and set details.
7. Read the task parameters.
8. Change supported parameters and verify read-back.
9. Restore the original parameters and verify restoration.
10. Remove the task and verify absence.
11. Remove the temporary set and verify absence.
12. Quit the owned PSCAD instance and require zero owned residual processes.

A `finally` path attempts to remove the temporary set and close the owned
instance after any failure. Evidence records the copied project, temporary set
name, PSCAD PID, mutation results, cleanup result, and final process count.

## Codex Registration

After implementation and verification, append a `pscad` MCP server entry to
`C:\Users\335\.codex\config.toml` without changing other MCP servers:

```toml
[mcp_servers.pscad]
type = "stdio"
command = 'D:\pscad-mcp\.venv\Scripts\python.exe'
args = ["-m", "pscad_mcp.main"]
startup_timeout_sec = 120
tool_timeout_sec = 600

[mcp_servers.pscad.env]
PSCAD_MCP_BACKEND = "legacy"
PSCAD_MCP_VERSION = "4.6.2"
PSCAD_MCP_X64 = "true"
PSCAD_MCP_LAUNCH_TIMEOUT = "30"
PSCAD_MCP_WORKSPACE = 'D:\PSCAD-Workspace'
```

The configuration is considered installed only after the file is parsed and
the configured Python interpreter imports `pscad_mcp`. A new Codex task is
required to load the server. The new task must show the 60 registered PSCAD
tools before installation is considered verified.

## Completion Criteria

The iteration is complete only when all of the following hold:

- seven new tools are implemented and the exact total is 60;
- existing tool signatures remain compatible;
- both backends satisfy the expanded protocol;
- every mutation checks the vendor response and a read-back postcondition;
- destructive operations require confirmation;
- automatic tests and static verification pass;
- the new PSCAD 4.6.2 real acceptance workflow passes;
- acceptance cleanup leaves no owned PSCAD process or temporary simulation
  set;
- documentation describes the new tools and Workspace ownership;
- Codex configuration contains the verified `pscad` entry;
- a new Codex task can load and expose the 60 PSCAD tools.
