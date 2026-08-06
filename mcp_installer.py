import sys
import subprocess
import json
import os
import platform
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("mcp-installer")

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _workspace_environment():
    workspace = os.getenv("PSCAD_MCP_WORKSPACE", "").strip()
    allow_unscoped = (
        "true"
        if os.getenv("PSCAD_MCP_ALLOW_UNSCOPED_PATHS", "").strip().lower()
        in _TRUE_VALUES
        else "false"
    )
    environment = {"PSCAD_MCP_ALLOW_UNSCOPED_PATHS": allow_unscoped}
    if workspace:
        environment = {
            "PSCAD_MCP_WORKSPACE": workspace,
            **environment,
        }
    return environment

def check_pscad():
    """Check if PSCAD is potentially installed (Windows only)."""
    if platform.system() != "Windows":
        logger.warning("⚠️ PSCAD is a Windows-only application. You appear to be on %s.", platform.system())
        return False
    
    # Try importing mhi.pscad
    try:
        import mhi.pscad
        logger.info("✅ mhi-pscad library is already installed.")
        return True
    except ImportError:
        logger.warning("❌ mhi-pscad library not found. It will be installed as a dependency.")
        return False

def install_package():
    """Install the pscad-mcp package in editable mode."""
    logger.info("🔧 Installing pscad-mcp and base dependencies...")
    
    install_cmd = [sys.executable, "-m", "pip", "install", "-e", "."]
    
    if platform.system() == "Windows":
        logger.info("🪟 Windows detected. Installing PSCAD RMI dependencies...")
        install_cmd[-1] = ".[windows]"
    
    try:
        subprocess.check_call(install_cmd)
        logger.info("✅ Installation successful.")
    except subprocess.CalledProcessError as e:
        logger.error("❌ Installation failed: %s", e)
        sys.exit(1)

def sync_docs():
    """Run the documentation sync utility."""
    logger.info("📚 Synchronizing PSCAD documentation for AI reference...")
    try:
        # Run via the new command point or module
        subprocess.check_call([sys.executable, "-m", "pscad_mcp.utils.doc_manager"])
        logger.info("✅ Documentation synced in /docs.")
    except Exception as e:
        logger.warning("⚠️ Doc sync failed (maybe PSCAD is not installed?). Skipping. Error: %s", e)

def print_copilot_cli_setup():
    """Generate and print GitHub Copilot CLI configuration guidance."""
    python_exe = sys.executable
    environment = _workspace_environment()
    workspace = environment.get("PSCAD_MCP_WORKSPACE")
    allow_unscoped = environment["PSCAD_MCP_ALLOW_UNSCOPED_PATHS"] == "true"

    config = {
        "mcpServers": {
            "pscad": {
                "type": "stdio",
                "command": python_exe,
                "args": ["-m", "pscad_mcp.main"],
                "tools": ["*"],
                "env": environment,
            }
        }
    }

    logger.info("\n--- 🤖 GITHUB COPILOT CLI SETUP ---")
    if workspace:
        logger.info("Workspace boundary: %s", workspace)
    elif allow_unscoped:
        logger.warning(
            "PSCAD_MCP_ALLOW_UNSCOPED_PATHS=true enables unscoped file access "
            "for controlled development only."
        )
    else:
        logger.warning(
            "PSCAD_MCP_WORKSPACE is not set. File operations are unavailable "
            "until the workspace is configured; they will return "
            "WORKSPACE_NOT_CONFIGURED. Set PSCAD_MCP_WORKSPACE to the directory "
            "that the server may access."
        )
    logger.info("Start GitHub Copilot CLI in this repository and run `/mcp add`.")
    logger.info("Use the following values in the form:")
    logger.info("  Name: pscad")
    logger.info("  Type: stdio")
    logger.info("  Command: %s", python_exe)
    logger.info("  Args: -m pscad_mcp.main")
    logger.info("  Environment:")
    if workspace:
        logger.info("    PSCAD_MCP_WORKSPACE=%s", workspace)
    else:
        logger.info(
            "    PSCAD_MCP_WORKSPACE=<set this before using file operations>"
        )
    logger.info(
        "    PSCAD_MCP_ALLOW_UNSCOPED_PATHS=%s",
        environment["PSCAD_MCP_ALLOW_UNSCOPED_PATHS"],
    )
    logger.info("Press Ctrl+S in Copilot CLI to save the server definition.")
    logger.info("\nIf you prefer editing the config file directly, add this JSON to mcp-config.json:")
    logger.info(json.dumps(config, indent=2))

    if platform.system() == "Windows":
        logger.info("\nDefault config location: %%USERPROFILE%%\\.copilot\\mcp-config.json")
    else:
        logger.info("\nDefault config location: ~/.copilot/mcp-config.json")

    return bool(workspace or allow_unscoped)

def main():
    logger.info("=== PSCAD MCP SERVER INSTALLER ===")
    
    check_pscad()
    install_package()
    sync_docs()

    file_operations_available = print_copilot_cli_setup()

    if file_operations_available:
        logger.info(
            "\n🎉 Setup Complete! You can now use PSCAD tools from GitHub "
            "Copilot CLI."
        )
    else:
        logger.info(
            "\nSetup complete for non-file PSCAD tools. Configure "
            "PSCAD_MCP_WORKSPACE before using file operations."
        )

if __name__ == "__main__":
    main()
