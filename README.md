# PSCAD MCP for Codex and GitHub Copilot CLI

`pscad-mcp` is a Windows Model Context Protocol (MCP) server for PSCAD automation. It uses `mhrc.automation` for PSCAD 4.6.x and `mhi.pscad` for PSCAD 5.x behind one stable 60-tool generic service contract, plus read-only topology diagnostics, HVDC, silent-learning, fixed CIGRE LCC, parametric LCC, and parametric MMC domain layers. The current inventory is 93 tools: 92 compatibility/domain tools plus one always-on capability tool.

中文安装、配置、安全和验收说明：[docs/zh-CN/README.md](docs/zh-CN/README.md)

Release notes are tracked in [CHANGELOG.md](CHANGELOG.md). A portable stdio
configuration template is available at [config.example.toml](config.example.toml).

The server is designed for Windows-based power-system workflows where you want Copilot to do more than explain code: it can connect to a live PSCAD session, open projects, edit parameters, build cases, run simulations, inspect outputs, and manipulate the canvas.

## Why this repo exists

PSCAD automation is powerful, but the raw API is not especially friendly for conversational workflows. This project packages that API into structured MCP tools so Copilot CLI can:

- launch a visible, owned PSCAD 4.6.x automation instance, or attach/launch through the modern backend
- inspect projects, simulation status, and output messages
- update project settings and component parameters
- create, place, wire, move, and delete components on the canvas
- run builds, simulation sets, and output file reads
- read synced PSCAD API documentation when it needs extra context

The legacy PSCAD 4.6.2 backend is launch-only: it starts a visible managed
automation instance and does not attach to an ordinary already-open GUI. By
default, an existing PSCAD process produces `EXTERNAL_PSCAD_PRESENT` before a
second instance is launched. `repair_connection` quits an instance only when
the backend reports that the MCP server owns it; it never terminates an
external process.

### Verified PSCAD 4.6.2 behavior and limits

- Blank case and library creation uses bundled PSCAD-saved templates. Creation
  and save-as rewrite the project identity and exact self-namespace references,
  then require PSCAD to load the expected name and type. New save-as targets
  try the native command and fall back to save plus an atomic copy when it does
  not produce a verified target. Existing targets always use the atomic-copy
  path; the operated source may therefore be saved before copying.
- Project settings read and write the selected project's parameters. They do
  not mutate application-global settings.
- Run is non-blocking. PSCAD 4.6.2 pause and stop remain application-wide
  vendor commands, so the backend sends them only when the requested case is
  the sole active case. An inactive target returns `RUN_NOT_ACTIVE`; another
  active case returns `RUN_CONTROL_SCOPE_CONFLICT` without sending the command.
  Stop is reported only after a terminal state is read back. The legacy status
  API continues to report `running` while the GUI is visibly paused, so a
  successfully dispatched Pause is exposed as a command-tracked `paused` state;
  resume, stop, terminal status, and disconnect clear that state.
- The shipped PSCAD 4.6.2 Automation Library rejects `create-layer` and
  `add-to-layer`, including membership in an existing valid layer. Component
  disable therefore returns `PSCAD_COMMAND_FAILED` instead of claiming a state
  change; dedicated disabled-layer membership is not available on this tested
  installation.
- Connected batch deletion prevalidates targets, translates relative wire
  vertices, checks for conflicting objects in the required selection area,
  executes one native canvas deletion, and verifies that planned IDs vanished.
  It returns `CAPABILITY_UNAVAILABLE` before mutation when a safe selection
  cannot be formed.
- Empty-space search uses the 18-unit PSCAD grid and collision margin. Sparse
  live canvas XML is enriched from the saved project XML and live locations;
  a conservative 36-by-36 rectangle is used only when neither has dimensions.

## Tool coverage

The complete inventory is 93 = 60 generic tools, 2 topology tools, 10 HVDC
tools, 3 learning tools, 4 fixed CIGRE LCC tools, 6 parametric LCC tools,
7 parametric MMC tools, and one always-on `get_pscad_capabilities` tool.
The generic 60-tool contract keeps its existing names and default return
shapes.

The server currently exposes tool groups for:

- application lifecycle and documentation access
- project loading, simulation control, and settings
- component search, parameter reads, and updates
- canvas creation and editing
- component transforms and port inspection
- simulation-set operations
- project creation, save, and build tasks
- simulation output capture and file parsing

### Compatible discovery, profiles, pagination, and documentation

`full` remains the unchanged default for `PSCAD_MCP_TOOL_PROFILE`, so existing
clients receive all compatibility/domain tools plus the always-on
`get_pscad_capabilities` tool. Selecting a comma-separated subset of `core`,
`hvdc`, `lcc`, `parametric_lcc`, and `learning` is opt-in. Empty, unknown, or
otherwise invalid profile values fail server startup instead of silently
changing the exposed inventory. `get_pscad_capabilities` reports the active
profile, registered tools, backend support, and explicit limitations.

Pagination is optional and does not change existing default results. The
bounded list operations accept `offset` and `limit`; `read_documentation`
accepts `offset` and `max_chars`. Synced modules are also available as MCP
resources under `pscad-docs://modules/`, including bounded URI variants.

Generated API documentation lives in local state and is created only when
`sync_documentation` is called. On Windows the default root is
`%LOCALAPPDATA%\\pscad-mcp\\docs`; `PSCAD_MCP_DOCUMENTATION_DIR` may override
the root, but it must be an absolute path.

The topology layer adds `inspect_project_topology` and
`diagnose_project_topology`. Both tools are read-only. Diagnosis now defaults
to `generic+hvdc-auto`: generic rules run first, then deterministic HVDC rules
consume the same canonical confirmed topology. Use `ruleset="generic"` to run
only the structural rules. `mode="conservative"` reports confirmed topology,
while `mode="infer"` may add explicit candidate edges; candidates are never
promoted to confirmed nets, included in the confirmed topology hash, or passed
to HVDC/LCC validation. Loaded HVDC projects use live canonical evidence;
absolute `.pscx` paths remain file-only compatible, and the LCC `ProjectGraph`
API is now adapted from the same canonical records. Licensed PSCAD 4.6.2
Legacy is the primary live target. PSCAD 5.x has contract coverage only and no
real topology acceptance claim.

The licensed topology gate is opt-in and runs only against timestamped project
copies prepared from an approved absolute truth manifest:

```powershell
& .\scripts\run_topology_acceptance.ps1 `
  -Workspace 'D:\PSCAD-Workspace\topology-acceptance' `
  -Manifest 'D:\PSCAD-Workspace\topology-truth.json' `
  -Version '4.6.2' -X64
```

The runner refuses source projects inside the acceptance workspace and refuses
to start while PSCAD is open. A `PASS` report must preserve project and object
inventory hashes, match complete confirmed-net and diagnostic truth, remain
deterministic, and satisfy the 500/2,000-object performance gates. The named
`unified_topology_462` scope passed the final `generic+hvdc-v1` gate on licensed
PSCAD 4.6.2, including exact canonical HVDC/LCC diagnostic codes. Its report,
truth manifest and review hashes, SHA-256, and tested commit are recorded in
`docs/acceptance-status.json`. This read-only diagnostic result does not imply
mutating HVDC workflows, fixed or parametric LCC builders, MMC, PSCAD 5.x, or
later-commit acceptance, and no acceptance status is inferred from the
non-licensed contract suite.

The HVDC domain layer adds ten tools without changing the original generic
inventory: `inspect_hvdc_project`, `get_hvdc_assets`, `get_hvdc_mappings`,
`validate_hvdc_project`, `run_hvdc_scenario`, `get_hvdc_scenario_status`,
`analyze_hvdc_results`, `compare_hvdc_scenarios`, `list_hvdc_profiles`, and
`register_hvdc_profile`. Inspection is read-only and keeps source project,
canvas, component, definition, and parameter references in every inferred
asset or mapping. Topology and metrics are marked as observed, derived, or
unresolved; missing channels produce `INCOMPLETE_ANALYSIS` rather than zeros.

Built-in profiles include `lcc_bipolar_generic`, `vsc_2level_generic`,
`mmc_bipolar_generic`, and `hvdc_breaker_difforder`. A scenario can only use
controls already mapped in the project; inserting fault components or
rewiring a canvas returns `HVDC_CAPABILITY_UNAVAILABLE`. Mutating scenario
parameters and registering a user profile require `confirm=true` and remain
subject to `PSCAD_MCP_WORKSPACE` path policy.

`lcc_bipolar_earth_return_v1` is a standalone, read-only inspect/validate
profile for LCC bipolar projects. It verifies positive/negative poles and
earth-return evidence (or reports `HVDC_RETURN_PATH_UNRESOLVED`); it provides
no command bindings and never switches return modes. Evidence gaps remain
`INCOMPLETE_ANALYSIS`/unresolved rather than being inferred. This first phase
does not extend VSC/MMC topology support.

### Fixed CIGRE LCC builder

The LCC layer exposes four tools: `plan_lcc_model`, `build_lcc_model`,
`get_lcc_build_status`, and `validate_lcc_model`. It targets only the fixed
CIGRE single-pole 12-pulse benchmark in licensed PSCAD 4.6.2. The blueprint
uses fixed electrical parameters and an original companion library packaged
with this repository; it is not a user-rated design generator. Workspace writes
are limited to `PSCAD_MCP_WORKSPACE`; builds refuse an existing destination, require
`confirm=true`, and require the exact plan hash returned by
`plan_lcc_model` before mutation.

The intended sequence is: call `plan_lcc_model`, review its hash and
operations, call `build_lcc_model(..., expected_plan_hash=..., confirm=true)`,
poll with `get_lcc_build_status`, then call `validate_lcc_model` on the saved
case. The four capability levels are `planned`, `built`, `simulated`, and
`accepted`; structural success, compilation, or a mocked/synthetic waveform
does not imply acceptance. `poles=2`, user-rated designs, PSCAD 5.x, fault or
commutation-failure acceptance, and MMC construction are unavailable.

Planning fails closed unless the attached PSCAD service supplies live
4.6.2 definition inventory; the packaged catalog is not treated as live
evidence. Build output channels also require an explicit public
`create_output_channel` capability followed by read-back. The packaged
`golden.json` is a release-gate placeholder until an independently reviewed
licensed reference run is generated, so the current branch cannot pass real
LCC acceptance.

Licensed acceptance has not passed for the PSCAD 4.6.2 implementation branch,
so the feature must not be described as an autonomously constructed
accepted CIGRE LCC model until the opt-in real acceptance test passes.

### Parametric dual-engine MMC

The MMC layer adds exactly seven tools: `audit_mmc_template`,
`derive_mmc_parameters`, `plan_parametric_mmc_model`,
`build_parametric_mmc_model`, `get_parametric_mmc_build_status`,
`recommend_mmc_simulation`, and `validate_mmc_model`. A request may select
`detailed_pwm`, `average_value`, or both under PSCAD 4.6.2. The detailed-PWM
engine is a read-only official template adapter; its default sources are
`H_MMC_Mono_DC.pscx` and `intermediate.pslx` under `ModelsInProgress`.
Audit and planning hash installed sources, while execution uses an isolated
copy and enforces source immutability. Plans expose four preplanned candidates
per engine and explicit limits: `intrinsic_dc_fault_blocking=false`,
`individual_cell_balance_not_modeled`, `device_stress_not_modeled`,
`switching_harmonics_not_modeled`, and `thermal_not_modeled`.

Use `audit_mmc_template`, `derive_mmc_parameters`, and
`plan_parametric_mmc_model` before `build_parametric_mmc_model`; review the
parent plan hash, poll `get_parametric_mmc_build_status`, obtain scenarios from
`recommend_mmc_simulation`, then call `validate_mmc_model`. Published outputs
include an independent `_scenario_source.pscx` and a `derived_project`; the
scenario can be passed unchanged to `run_hvdc_scenario`. Structural states
`inspected`, `designed`, `planned`, `built`, `simulated`, and `accepted` are
distinct, and `NOT_RUN_ON_INTEGRATED_COMMIT` remains explicit until licensed
evidence exists.

Read-only HVDC inspection may scan an existing absolute `.pscx` source such as
`C:\\PSCADFiles\\Breaker\\TEST1\\difforder_new.pscx`; all scenario mutations
still require a workspace-scoped, pre-existing `derived_project` and explicit
confirmation.

Example read-only inspection:

```text
inspect_hvdc_project(project_name="D:\\PSCAD-Workspace\\difforder_new.pscx")
```

Example declarative scenario:

```json
{
  "name": "dc_fault_breaker_trip",
  "profile": "hvdc_breaker_difforder",
  "project": "difforder_new",
  "parameter_changes": [],
  "events": [
    {"time_s": 1.0, "target": "fault_command", "value": 1},
    {"time_s": 1.05, "target": "breaker_command", "value": 1}
  ],
  "run": {"timeout_s": 300},
  "analysis": {"metrics": ["dc_current_peak", "dc_voltage_min", "trip_delay_s"]}
}
```

HVDC event `time_s` is always EMTDC simulation time. There is no wall-clock
fallback: external events are rejected when the backend has neither verified
native scheduling nor a simulation-clock polling capability. The built-in
`hvdc_breaker_difforder` profile is version 2 and contains seven explicit
read-only result selectors with their recorded units; it intentionally contains
no writable breaker or fault binding. User profiles must provide a confirmed,
project-qualified command binding before any mutation is allowed. Output
`PlotType="OUT"` correction is limited to confirmed derived projects.

The built-in selector contract is: `dc_voltage_breaker` (`kV`),
`dc_current_breaker` (`kA`), `breaker_command_observed` (binary),
`dc_voltage_rectifier_pole1`/`dc_voltage_inverter_pole1` (`pu`), and
`dc_voltage_rectifier_pole2`/`dc_voltage_inverter_pole2` (`pu`). Selector
 paths and legacy call IDs are resolved exactly; aliases are not inferred for
 write operations. When a v2 scenario requests metrics, preflight also requires
 backend output-channel metadata and verifies path, call ID, and units before any
 parameter write; unavailable inspection is a structured safety rejection.

VSC 2-level and MMC generic profiles now expose explicit measurement selectors
and unit-aware roles for DC quantities, P/Q, PLL/dq signals, arm current,
submodule capacitor voltage, and circulating current. Generic profiles remain
read-only until a project-qualified result selector or command binding is
registered.

Polling-based EMTDC control uses a bounded interval and detects a stalled
simulation clock. Timed events carry stable IDs and duplicate IDs are rejected
before dispatch. Legacy and Modern adapters only advertise native scheduling,
simulation-clock, or output-channel capabilities when the loaded project
exposes an explicit provider; otherwise the scenario fails closed.

Opt-in licensed acceptance requires `PSCAD_MCP_ACCEPTANCE=1`,
`PSCAD_MCP_HVDC_SOURCE`, `PSCAD_MCP_HVDC_LIBRARY`, and
`PSCAD_MCP_WORKSPACE` to point to approved absolute paths:

```powershell
$env:PSCAD_MCP_ACCEPTANCE='1'
& .\.venv\Scripts\python.exe -m pytest tests\test_hvdc_real_acceptance.py -q -s
```

Acceptance copies the case and library to a timestamped workspace, preserves
source hashes, and safely reports `HVDC_TIMED_CONTROL_UNAVAILABLE` or
`HVDC_MAPPING_MISSING` before mutation when strict timing or a confirmed
binding is unavailable.

The implementation is modular, with each tool family registered from its own module in `pscad_mcp\tools`.

Simulation sets are workspace-level resources rather than project-owned
resources. The original `project_name` arguments on `list_simulation_sets`,
`run_simulation_set`, and `add_task_to_set` remain for compatibility only.
The complete workflow includes `create_simulation_set`,
`remove_simulation_set`, `list_simulation_set_tasks`,
`remove_tasks_from_set`, `get_simulation_task_parameters`,
`set_simulation_task_parameters`, and `get_simulation_set_details`.
Destructive removals require `confirm=true`; PSCAD 4.6.2 task writes support
only `controlgroup`, `volley`, and `affinity`, with `namespace` read-only.

## Silent local learning

Silent learning is enabled by default and stores local-only scalar metadata.
It never persists parameters, results, project paths, prompts, exception text,
error details, or tracebacks. It does not upload telemetry or create model
training data.

The default Windows state directory is `%LOCALAPPDATA%\pscad-mcp`, containing
`learning.sqlite3` and the generated `improvement-backlog.md`. The Markdown
file is a generated projection: it is atomically replaced and manual edits
are overwritten. The recommended repository-local override is ignored by
`.gitignore`.

The five learning variables are:

```text
PSCAD_MCP_LEARNING_ENABLED=true
PSCAD_MCP_LEARNING_DB=<optional absolute SQLite path>
PSCAD_MCP_LEARNING_BACKLOG=<optional absolute Markdown path>
PSCAD_MCP_LEARNING_RETENTION_DAYS=90       # 1 through 3650
PSCAD_MCP_LEARNING_MAX_EVENTS=20000       # 100 through 1000000
```

Successful operation remains silent. Ordinary improvement evidence waits for
review; only narrowly defined critical correctness, partial-mutation, or
recovery risks may produce one concise reminder, while the original
operational or safety error remains visible. After a failed goal, the host
may still show a collapsed `record_goal_failure` audit entry even though
routine user-facing prose remains silent.

The three learning tools are `record_goal_failure`,
`review_improvement_backlog`, and `clear_learning_history`. Clearing requires
explicit confirmation and regenerates the header-only backlog.

A separately created Codex desktop heartbeat reviews the backlog every Monday
at 09:00 in `Asia/Shanghai`. The MCP server and installer do not create that
heartbeat implicitly. Scheduled work requires the machine and Codex desktop
app to be running, with the repository and MCP server available.

## Errors and connection recovery

Every MCP tool returns failures in one stable `error` object containing
`code`, `message`, `backend`, `operation`, `details`, `retryable`, and
`suggested_action`. This preserves backend diagnostics such as
`PARTIAL_COMPLETION` and `POSTCONDITION_FAILED` instead of reducing them to an
unstructured MCP execution error.

`get_pscad_status` also returns an `executor` object with `healthy`,
`last_operation`, `last_error`, `last_timeout_seconds`, `reset_generation`, and
`previous_worker_retiring`. After a timeout, call `repair_connection` before
retrying the failed operation. Recovery uses
the backend's cached process ownership and never terminates a process reported
as external.

For a managed legacy session, `get_pscad_status.session` includes the launch
mode, managed PID when the vendor process handle exposes it, existing-process
policy, `ordinary_gui_attach_supported=false`, the pause-state source, and any
currently tracked paused project.

If an owned PSCAD 4.6.x instance cannot be closed after the executor is reset,
repair returns `REPAIR_CLEANUP_FAILED` and does not launch a second instance.
Close that PSCAD process manually, then call `repair_connection` again.

## Optional workflow extensions

The existing 60 tools keep their names and default return shapes while accepting
these optional arguments:

- `get_project_output(project_name, structured=true)` returns JSON-safe message
  records with `severity`, `text`, and optional `source`; the default remains a
  text string.
- `read_output_file(file_path, channel="Root/Voltage/PGB:Data",
  summary_only=true)` selects one normalized channel path and returns bounded
  statistics (`count`, `min`, `max`, `mean`, `first`, and `last`) without raw
  samples. Skipped traces are reported in `warnings` and `skipped_channels`.
- `get_project_settings` and `set_project_settings` accept
  `mode="parameter_grid"` with an action mapping for `view_project`, `load`,
  or `save` of a `.csv` grid. The modern backend forwards supported actions to
  the vendor proxy; PSCAD 4.6.2 legacy automation returns
  `CAPABILITY_UNAVAILABLE` explicitly.

## Requirements

For full PSCAD automation you need:

- Windows
- Python 3.10+
- PSCAD installed
- the matching PSCAD Python automation package
- an MCP client such as Codex or GitHub Copilot CLI

The current implementation targets `mcp>=1.29,<2`, official
`mhrc-automation` 1.2.x for PSCAD 4.6.x, `mhi-pscad` 3.1.x for PSCAD 5.x,
and `mhi-psout` 1.3.x. The `mcp` upper bound is intentional because this
repository uses the FastMCP 1.x import path.

File operations require `PSCAD_MCP_WORKSPACE` to be set to the directory that
contains the projects and output files the server may access:

```powershell
$env:PSCAD_MCP_WORKSPACE = "D:\PSCAD-Workspace"
```

When this variable is set, project and result paths outside the workspace are
rejected. If it is not set, file operations return
`WORKSPACE_NOT_CONFIGURED` instead of accessing an unscoped path. Destructive
or overwrite-capable tools also require `confirm=true`.

For controlled development only, you may explicitly opt into the previous
unscoped behavior:

```powershell
$env:PSCAD_MCP_ALLOW_UNSCOPED_PATHS = "true"
```

Do not use that override for shared or production MCP servers. Restart the MCP
connection after changing either workspace variable.

You can still run tests and documentation-related tasks without PSCAD installed.

## Install GitHub Copilot CLI

Install Copilot CLI using one of the supported methods from GitHub. On Windows, the most direct option is:

```powershell
winget install GitHub.Copilot
```

You can also install via npm:

```powershell
npm install -g @github/copilot
```

Then start it with:

```powershell
copilot
```

If needed, sign in from inside the CLI using `/login`.

## Install this MCP server on Windows

From the repository root, keep the checkout and virtual environment paths in
variables so the same commands work on another machine:

```powershell
$repoRoot = (Get-Location).Path
$venvPath = Join-Path $repoRoot ".venv"
py -3 -m venv $venvPath
& (Join-Path $venvPath "Scripts\python.exe") -m pip install -e "$repoRoot[windows]"
```

For PSCAD 4.6.x, install the licensed Automation Library wheel supplied with
your PSCAD installation or by the vendor; it is not redistributed by this
repository:

```powershell
& (Join-Path $venvPath "Scripts\python.exe") -m pip install "C:\path\to\mhrc_automation-1.2.4-py3-none-any.whl"
```

For non-Windows development tasks such as tests or documentation work, install base dependencies only:

```powershell
py -3 -m pip install -e .
```

The repository includes a portable Codex template at
[`config.example.toml`](config.example.toml). Copy its `mcp_servers.pscad`
block into `%USERPROFILE%\.codex\config.toml`, then replace the example
Python interpreter and workspace paths with paths on your machine. Do not
copy the maintainer's local configuration file. After saving the TOML file,
start a new Codex task so the MCP server is loaded again.

## Quick setup for Copilot CLI

The easiest path is the included installer:

```powershell
py -3 mcp_installer.py
```

It installs the package, tries to sync PSCAD documentation, and prints the values you should enter into Copilot CLI.

You can also configure the server manually.

### Option 1: Add the server interactively in Copilot CLI

1. Start Copilot CLI in this repository:

   ```powershell
   copilot
   ```

2. Run:

   ```text
   /mcp add
   ```

3. Fill in the server details:

   - Name: `pscad`
   - Type: `stdio`
   - Command: your Python executable
   - Args: `-m pscad_mcp.main`
   - Environment: `PSCAD_MCP_WORKSPACE=C:\\path\\to\\PSCAD-Workspace`
   - Environment: `PSCAD_MCP_ALLOW_UNSCOPED_PATHS=false`
   - Environment: `PSCAD_MCP_LEARNING_ENABLED=true`

4. Press `Ctrl+S` to save.

By default, Copilot CLI stores MCP definitions in `~/.copilot/mcp-config.json` on Windows as `%USERPROFILE%\.copilot\mcp-config.json`.

### Option 2: Edit `mcp-config.json` directly

If you prefer editing the config file yourself, add an entry like this:

```json
{
  "mcpServers": {
    "pscad": {
      "type": "stdio",
      "command": "C:\\Path\\To\\Python\\python.exe",
      "args": ["-m", "pscad_mcp.main"],
      "tools": ["*"],
      "env": {
        "PSCAD_MCP_WORKSPACE": "C:\\path\\to\\PSCAD-Workspace",
        "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "false",
        "PSCAD_MCP_LEARNING_ENABLED": "true"
      }
    }
  }
}
```

Replace the `command` path with the interpreter from the environment where `pscad-mcp` is installed.

### Codex configuration

The equivalent path-neutral entry is:

```toml
[mcp_servers.pscad]
type = 'stdio'
command = 'C:/path/to/pscad-mcp/.venv/Scripts/python.exe'
args = ['-m', 'pscad_mcp.main']
startup_timeout_sec = 120
tool_timeout_sec = 600

[mcp_servers.pscad.env]
PSCAD_MCP_BACKEND = 'legacy'
PSCAD_MCP_VERSION = '4.6.2'
PSCAD_MCP_X64 = 'true'
PSCAD_MCP_LEGACY_MINIMIZE = 'false'
PSCAD_MCP_LEGACY_EXISTING_POLICY = 'reject'
PSCAD_MCP_WORKSPACE = 'C:/path/to/PSCAD-Workspace'
PSCAD_MCP_ALLOW_UNSCOPED_PATHS = 'false'
PSCAD_MCP_LEARNING_ENABLED = 'true'
PSCAD_MCP_LEARNING_RETENTION_DAYS = '90'
PSCAD_MCP_LEARNING_MAX_EVENTS = '20000'
```

Replace both local paths in this example, or copy the values from
[`config.example.toml`](config.example.toml). Use
`PSCAD_MCP_BACKEND='modern'` and an installed 5.x version for PSCAD 5.x.
The current repository has contract coverage for Modern but does not claim
real PSCAD 5.x end-to-end acceptance.

`PSCAD_MCP_LEGACY_MINIMIZE=false` keeps the managed 4.6.x window visible.
`PSCAD_MCP_LEGACY_EXISTING_POLICY=allow` is an explicit opt-in to launch a
separate managed instance while another PSCAD process exists; it does not
attach to that external GUI.

## First prompts to try in Copilot CLI

Once the server is registered, open `copilot` in this repository and try prompts like:

- `Connect to my local PSCAD instance and show me its status.`
- `List the projects currently loaded in PSCAD.`
- `Load C:\Projects\IEEE_9Bus.pscx and start the simulation.`
- `Find the component named MainTransformer and show its parameters.`
- `Read the PSCAD project documentation module and summarize the run_status API.`
- `Create a bus on the main canvas and connect it to the selected components.`

## Running the server directly

To launch the MCP server without the installer:

```powershell
py -3 -m pscad_mcp.main
```

An installed entry point is also available:

```powershell
pscad-mcp
```

## Development workflow

### Sync documentation snapshots

This project can generate PSCAD API reference snapshots that are easier for LLMs to consume:

```powershell
py -3 -m pscad_mcp.utils.doc_manager
```

Generated files are written to:

- `docs\raw` for raw extracted output
- `docs\md` for enriched Markdown

### Run tests

```powershell
py -3 -m unittest discover tests
```

Tests mock the PSCAD layer, so they can run without PSCAD installed.

Licensed PSCAD 4.6.2 acceptance is opt-in and works only on timestamped copies:

```powershell
& .\scripts\run_legacy_acceptance.ps1 `
  -Workspace 'D:\PSCAD-Workspace\acceptance' `
  -Version '4.6.2' -X64
```

The runner refuses to start while another PSCAD process is open and never
broadly terminates PSCAD processes. It runs the six original acceptance tests
plus nine reliability tests, records owned PIDs and evidence directories, and
requires all owned processes to exit. PSCAD 4.6.2 has been exercised on a real
licensed installation; PSCAD 5.x remains contract-tested only until a real 5.x
installation is available for end-to-end acceptance.

## Project structure

```text
pscad_mcp\
  core\
    backend\
      legacy.py
      modern.py
      selector.py
    connection_manager.py
    executor.py
    service.py
  hvdc\
    models.py
    scanner.py
    classifier.py
    mappings.py
    profiles.py
    scenarios.py
    metrics.py
    service.py
  tools\
    app_tools.py
    project_tools.py
    data_tools.py
    simset_tools.py
    creation_tools.py
    canvas_tools.py
    component_tools.py
    hvdc_tools.py
  utils\
    doc_manager.py
  main.py
tests\
docs\
```

## Architecture notes

Two implementation details matter for reliability:

- `PscadService` is the only entry point used by MCP tools; it centralizes safety, confirmation, and JSON normalization.
- `LegacyBackend` and `ModernBackend` keep vendor objects behind the backend boundary.
- `RobustExecutor` serializes PSCAD calls through a single-worker executor with a timeout guard to reduce hangs from COM/RMI operations.

Those guardrails are important because PSCAD automation is effectively single-threaded and can become unstable if calls are issued concurrently.

## Troubleshooting

If Copilot CLI can see the server but tool calls fail:

- verify the configured Python executable matches the environment where `pscad-mcp` is installed
- confirm PSCAD is installed and licensed
- rerun `py -3 mcp_installer.py`
- run `py -3 -m unittest discover tests` to verify the Python package is still healthy

If documentation tools return no modules, run the documentation sync command again.

## License and attribution

Project material contributed under this repository is available under the
[MIT License](LICENSE). This repository is a modified fork of
[`SecchiAlessandro/pscad-mcp`](https://github.com/SecchiAlessandro/pscad-mcp).

See [NOTICE](NOTICE) for upstream attribution, third-party material boundaries,
and the PSCAD/MHI non-affiliation statement.
