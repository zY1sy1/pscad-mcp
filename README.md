# PSCAD Enterprise MCP Server

A professional, robust Model Context Protocol (MCP) server for **Power System Computer Aided Design (PSCAD)**. This server enables AI assistants (like Claude and Gemini) to automate PSCAD simulations, manage projects, and analyze results directly on a local Windows machine.

## 🚀 Key Features

- **Local-First Approach**: Optimized for local Windows automation using `mhi.pscad.application()`.
- **Execution Watchdog**: A 30-second timeout layer prevents AI tools from hanging if PSCAD is frozen or showing a modal dialog.
- **Process Monitoring**: OS-level detection of `PSCAD.exe` crashes or closures.
- **Thread-Safe Command Queue**: Ensures sequential execution, critical for PSCAD's single-threaded COM/RMI interface.
- **Self-Healing Docs**: The `sync_documentation` tool re-extracts API references directly from your installed `mhi-pscad` version.

---

## 🛠 Installation (Simplified)

We've automated the setup process. Simply run the installer:

```bash
# 1. Clone the repository
# 2. Run the automated installer
python mcp_installer.py
```

The installer will:
- Check for PSCAD and Python prerequisites.
- Install the `pscad-mcp` package and all dependencies.
- Synchronize your local PSCAD API documentation for AI reference.
- Generate the exact configuration snippets for **Claude Desktop** and **Gemini CLI**.

---

## 🤖 AI Tool Integration

After running the installer, follow the printed instructions to add the server to your favorite AI tool.

### Claude Desktop
Copy the generated JSON into your `claude_desktop_config.json`.

### Gemini CLI
Run the `gemini mcp add` command provided by the installer.

---

## 🏗 Implementation Details

### Architecture (SOLID Principles)
The server is built using a modular package structure to ensure maintainability and testability:
- **`core/connection_manager.py`**: A **Singleton** that manages the lifecycle of the PSCAD instance and monitors OS-level process health.
- **`core/executor.py`**: Implements the **Command/Proxy Pattern**. All calls to PSCAD are proxied through a single-worker thread pool with an `asyncio` watchdog.
- **`tools/`**: Modularized toolsets (App, Project, Data) following the **Single Responsibility Principle**.

### Safety Mechanisms
1. **JSON-RPC Compliance**: The server enforces strict JSON serializability of all return types and prevents `stdout` pollution (which would break the protocol).
2. **Heartbeat Checks**: Before every command, the server performs a "heartbeat" check (`is_busy()`) to ensure the connection is still valid.
3. **Stale Handle Recovery**: If a project handle is lost (e.g., due to a manual reload), the `repair_connection` tool allows the AI to re-synchronize state without restarting the server.

---

## 📖 Available Tools

### System & Lifecycle
- `get_local_pscad`: Attach to/Launch a local PSCAD instance.
- `get_pscad_status`: Health check and version info.
- `sync_documentation`: Extract and update AI's internal reference files.
- `list_documentation`: List available PSCAD API documentation modules.
- `read_documentation`: Read clean, LLM-optimized Markdown documentation for a specific module.
- `repair_connection`: Force-reset the RMI connection.
- `quit_pscad`: Terminate the PSCAD application.

### Project & Components
- `load_projects`: Load `.pscx`, `.pslx`, or `.pswx` files.
- `list_projects`: Get a list of loaded cases/libraries.
- `run_project`: Start a simulation (includes license verification).
- `get_run_status`: Monitor simulation progress.
- `find_components`: Locate components by name or definition.

### Data & Results
- `get_project_output`: Capture simulation runtime messages.
- `read_output_file`: Parse `.psout` or `.out` results into JSON.

---

## 🧪 Testing & Validation
Run the full test suite to verify logic and protocol integrity:
```bash
python -m unittest discover tests
```
*Note: Unit tests use mocks to simulate PSCAD behavior, allowing verification on any OS.*
