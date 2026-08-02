# PSCAD MCP for Codex and GitHub Copilot CLI

`pscad-mcp` is a Windows Model Context Protocol (MCP) server for PSCAD automation. It uses `mhrc.automation` for PSCAD 4.6.x and `mhi.pscad` for PSCAD 5.x behind one stable 53-tool service contract.

中文安装、配置、安全和验收说明：[docs/zh-CN/README.md](docs/zh-CN/README.md)

The server is designed for Windows-based power-system workflows where you want Copilot to do more than explain code: it can connect to a live PSCAD session, open projects, edit parameters, build cases, run simulations, inspect outputs, and manipulate the canvas.

## Why this repo exists

PSCAD automation is powerful, but the raw API is not especially friendly for conversational workflows. This project packages that API into structured MCP tools so Copilot CLI can:

- launch a new PSCAD 4.6.x automation instance, or attach/launch through the modern backend
- inspect projects, simulation status, and output messages
- update project settings and component parameters
- create, place, wire, move, and delete components on the canvas
- run builds, simulation sets, and output file reads
- read synced PSCAD API documentation when it needs extra context

The legacy PSCAD 4.6.2 backend is launch-only: it starts a new automation
instance and does not attach to an already-open GUI. `repair_connection` quits
that instance only when the backend reports that the MCP server owns it;
otherwise it disconnects without terminating the external process.

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

The implementation is modular, with each tool family registered from its own module in `pscad_mcp\tools`.

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

For safer file handling, set `PSCAD_MCP_WORKSPACE` to the directory that
contains the projects and output files you want the server to access:

```powershell
$env:PSCAD_MCP_WORKSPACE = "D:\PSCAD-Workspace"
```

When this variable is set, project and result paths outside the workspace are
rejected. Destructive or overwrite-capable tools also require `confirm=true`.

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

## Install this MCP server on D:

From the repository root:

```powershell
py -3 -m venv D:\pscad-mcp\.venv
& D:\pscad-mcp\.venv\Scripts\python.exe -m pip install -e "D:\pscad-mcp[windows]"
```

For PSCAD 4.6.x, install the licensed Automation Library wheel supplied with
your PSCAD installation or by the vendor; it is not redistributed by this
repository:

```powershell
& D:\pscad-mcp\.venv\Scripts\python.exe -m pip install "D:\path\to\mhrc_automation-1.2.4-py3-none-any.whl"
```

For non-Windows development tasks such as tests or documentation work, install base dependencies only:

```powershell
py -3 -m pip install -e .
```

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
      "tools": ["*"]
    }
  }
}
```

Replace the `command` path with the interpreter from the environment where `pscad-mcp` is installed.

### Codex configuration

Add this to `%USERPROFILE%\.codex\config.toml`, then start a new Codex task:

```toml
[mcp_servers.pscad]
command = 'D:\pscad-mcp\.venv\Scripts\python.exe'
args = ['-m', 'pscad_mcp.main']
startup_timeout_sec = 120
tool_timeout_sec = 600

[mcp_servers.pscad.env]
PSCAD_MCP_BACKEND = 'legacy'
PSCAD_MCP_VERSION = '4.6.2'
PSCAD_MCP_X64 = 'true'
PSCAD_MCP_WORKSPACE = 'D:\PSCAD-Workspace'
```

Use `PSCAD_MCP_BACKEND='modern'` and an installed 5.x version for PSCAD 5.x.

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
broadly terminates PSCAD processes. PSCAD 4.6.2 has been exercised on a real
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
  tools\
    app_tools.py
    project_tools.py
    data_tools.py
    simset_tools.py
    creation_tools.py
    canvas_tools.py
    component_tools.py
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

## License

MIT
