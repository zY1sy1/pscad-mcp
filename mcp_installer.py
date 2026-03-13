import os
import sys
import subprocess
import json
import platform
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("mcp-installer")

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

def print_claude_config():
    """Generate and print Claude Desktop configuration."""
    current_dir = os.path.abspath(os.getcwd())
    python_exe = sys.executable
    
    # In a packaged install, we use the 'pscad-mcp' command if it's in PATH,
    # but for Claude it's safer to use the absolute path to the main.py or the installed script.
    
    config = {
        "mcpServers": {
            "pscad": {
                "command": python_exe,
                "args": [os.path.join(current_dir, "pscad_mcp", "main.py")]
            }
        }
    }
    
    logger.info("\n--- 🤖 CLAUDE DESKTOP CONFIGURATION ---")
    logger.info("Add the following to your claude_desktop_config.json:")
    logger.info(json.dumps(config, indent=2))
    
    if platform.system() == "Windows":
        logger.info("\nConfig Location: %%APPDATA%%\\Claude\\claude_desktop_config.json")
    elif platform.system() == "Darwin":
        logger.info("\nConfig Location: ~/Library/Application Support/Claude/claude_desktop_config.json")

def print_gemini_config():
    """Generate and print Gemini CLI command."""
    current_dir = os.path.abspath(os.getcwd())
    python_exe = sys.executable
    main_py = os.path.join(current_dir, "pscad_mcp", "main.py")
    
    logger.info("\n--- 🤖 GEMINI CLI CONFIGURATION ---")
    logger.info("Run this command in your terminal:")
    logger.info(f"gemini mcp add pscad-mcp {python_exe} {main_py}")

def main():
    logger.info("=== PSCAD MCP SERVER INSTALLER ===")
    
    check_pscad()
    install_package()
    sync_docs()
    
    print_claude_config()
    print_gemini_config()
    
    logger.info("\n🎉 Setup Complete! You can now use PSCAD tools in your AI assistant.")

if __name__ == "__main__":
    main()
