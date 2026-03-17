# PSCAD MCP repository instructions

This repository contains a Python MCP server that exposes PSCAD automation tools to GitHub Copilot CLI.

## Key commands

- Install base dependencies: `pip install -e .`
- Install with PSCAD RMI dependencies on Windows: `pip install -e ".[windows]"`
- Run the installer and print Copilot CLI setup details: `python mcp_installer.py`
- Start the server directly: `python -m pscad_mcp.main`
- Sync PSCAD docs into `docs\md` and `docs\raw`: `python -m pscad_mcp.utils.doc_manager`
- Run tests: `python -m unittest discover tests`

## Architecture

- `pscad_mcp\main.py` creates the FastMCP server and registers tool groups.
- `pscad_mcp\core\connection_manager.py` manages the live PSCAD session and validates process health.
- `pscad_mcp\core\executor.py` serializes PSCAD calls through a single-worker executor and timeout guard.
- Tool modules under `pscad_mcp\tools` group functionality by domain: app lifecycle, project control, data extraction, simulation sets, creation, canvas editing, and component operations.
- `pscad_mcp\utils\doc_manager.py` builds AI-friendly documentation snapshots from the PSCAD Python API.

## Repository-specific constraints

- Real PSCAD execution is Windows-only.
- Every PSCAD call should go through `robust_executor.run_safe(...)`.
- Tool return values must remain JSON-serializable.
- Do not write to stdout from library code; use the `logging` module.
