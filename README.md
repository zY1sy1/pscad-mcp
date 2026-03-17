# PSCAD MCP for GitHub Copilot CLI

`pscad-mcp` is a Model Context Protocol (MCP) server that lets GitHub Copilot CLI control PSCAD through the `mhi.pscad` automation API.

The server is designed for Windows-based power-system workflows where you want Copilot to do more than explain code: it can connect to a live PSCAD session, open projects, edit parameters, build cases, run simulations, inspect outputs, and manipulate the canvas.

## Why this repo exists

PSCAD automation is powerful, but the raw API is not especially friendly for conversational workflows. This project packages that API into structured MCP tools so Copilot CLI can:

- attach to an existing PSCAD session or launch one
- inspect projects, simulation status, and output messages
- update project settings and component parameters
- create, place, wire, move, and delete components on the canvas
- run builds, simulation sets, and output file reads
- read synced PSCAD API documentation when it needs extra context

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
- the PSCAD Python packages, typically installed through the optional `windows` extras in this repo
- GitHub Copilot CLI

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

## Install this MCP server

From the repository root:

```powershell
py -3 -m pip install -e ".[windows]"
```

If `python` is available on your machine, this is equivalent:

```powershell
python -m pip install -e ".[windows]"
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

## Project structure

```text
pscad_mcp\
  core\
    connection_manager.py
    executor.py
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

- `PSCADConnectionManager` tracks the live PSCAD handle and checks process health before reuse.
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
