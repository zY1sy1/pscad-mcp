# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable mode, base deps only)
pip install -e .

# Install with PSCAD RMI dependencies (Windows only)
pip install -e ".[windows]"

# Run the automated installer (installs + syncs docs + prints AI tool config)
python mcp_installer.py

# Run the server directly
python pscad_mcp/main.py
# or via installed script:
pscad-mcp

# Sync PSCAD API documentation to docs/md/ and docs/raw/
python -m pscad_mcp.utils.doc_manager

# Run all tests
python -m unittest discover tests

# Run a single test file
python -m unittest tests/test_enhanced_tools.py
```

## Architecture

This is a **Model Context Protocol (MCP) server** that exposes PSCAD automation as AI tools. PSCAD is a Windows-only power system simulation tool accessed via a COM/RMI interface (`mhi.pscad`).

### Entry point and tool registration

`pscad_mcp/main.py` creates a `FastMCP` server and calls four `register_*` functions to attach tools. Each tool module holds a group of `async` functions and a `register_*` function that calls `mcp.tool()` on each:

- `tools/app_tools.py` — lifecycle (connect, status, quit) and documentation tools
- `tools/project_tools.py` — project loading, simulation control (run/pause/stop), component parameter get/set/validate, project settings
- `tools/data_tools.py` — simulation output capture, `.psout`/`.out` file parsing
- `tools/simset_tools.py` — batch simulation sets (list, run, add tasks)
- `tools/creation_tools.py` — project creation (case/library), save, build, definition listing
- `tools/canvas_tools.py` — component placement, wiring, bus/connection creation, annotations, graph frames, canvas queries
- `tools/component_tools.py` — per-component operations: location, rotation, mirror, clone, ports, enable/disable, delete

### Core layer

- **`core/connection_manager.py`** — `PSCADConnectionManager` singleton. Holds the live `mhi.pscad.PSCAD` handle. Before returning it, performs an OS-level `psutil` process check (`PSCAD.exe`) and an RMI heartbeat (`is_busy()`). Access via the module-level `pscad_manager` instance.
- **`core/executor.py`** — `RobustExecutor` wraps every PSCAD call in a `ThreadPoolExecutor(max_workers=1)` with a threading `Lock` and a 30-second `asyncio.wait_for` watchdog. This prevents hangs caused by frozen dialogs and serializes all COM calls. Access via the module-level `robust_executor` instance. Every tool that calls PSCAD must use `await robust_executor.run_safe(func, *args)`.

### Documentation system

`utils/doc_manager.py` — `DocumentationManager` uses `pydoc` to extract raw docs and `ast`-based `SourceAnalyzer` to enrich them with `@rmi`/`@requires` decorator metadata and type hints that pydoc misses. Output goes to:
- `docs/raw/*.txt` — raw pydoc output
- `docs/md/*.md` — LLM-friendly enriched Markdown

The AI can read these at runtime via `list_documentation` / `read_documentation` tools.

### Testing approach

Tests use `unittest.IsolatedAsyncioTestCase` and mock the full PSCAD hierarchy (`pscad_manager` + `robust_executor.run_safe`). The executor mock collapses the async wrapper: `side_effect=lambda f, *args, **kwargs: f(*args, **kwargs)`. Tests can run on any OS without PSCAD installed.

### Key constraints

- **Windows only** for actual PSCAD execution; tests and doc sync work cross-platform.
- All tool return values must be JSON-serializable (enforced by MCP protocol).
- Stdout must not be polluted — all logging goes through the `logging` module.
- PSCAD's COM interface is single-threaded; the executor's single-worker pool + lock enforces this.
