# PSCAD MCP for Codex and GitHub Copilot CLI

`pscad-mcp` is a Windows Model Context Protocol (MCP) server for PSCAD automation. It uses `mhrc.automation` for PSCAD 4.6.x and `mhi.pscad` for PSCAD 5.x behind one stable 60-tool generic service contract, plus a separate HVDC domain layer.

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

The server currently exposes tool groups for:

- application lifecycle and documentation access
- project loading, simulation control, and settings
- component search, parameter reads, and updates
- canvas creation and editing
- component transforms and port inspection
- simulation-set operations
- project creation, save, and build tasks
- simulation output capture and file parsing

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
        "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "false"
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
licensed installation; PSCAD 5.x remains contract-tested until a real 5.x
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
