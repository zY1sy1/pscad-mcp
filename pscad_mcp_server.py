import os
import sys
import logging
import asyncio
import threading
import psutil
from typing import Optional, List, Dict, Any, Union, Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from mcp.server.fastmcp import FastMCP
import mhi.pscad

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("pscad-mcp")

# Global Configuration & State
COMMAND_TIMEOUT = 30.0  # Seconds to wait for PSCAD to respond
pscad_instance: Optional[mhi.pscad.PSCAD] = None
pscad_lock = threading.Lock()  # PSCAD is mostly single-threaded via COM/RMI
executor = ThreadPoolExecutor(max_workers=1) # Ensure sequential execution for stability

# Initialize FastMCP server
mcp = FastMCP("PSCAD-Robust-Local")

# Attempt to import mhi.psout
try:
    import mhi.psout
    PSOUT_AVAILABLE = True
except ImportError:
    PSOUT_AVAILABLE = False

# --- Robustness Helpers ---

def is_pscad_process_running() -> bool:
    """Check if PSCAD.exe is actually running on the OS."""
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] and 'pscad' in proc.info['name'].lower():
            return True
    return False

def get_pscad_safe() -> mhi.pscad.PSCAD:
    """Helper to get a verified, responsive PSCAD instance."""
    global pscad_instance
    
    if pscad_instance is None:
        raise RuntimeError("PSCAD not connected. Use launch_pscad() or get_local_pscad() first.")
    
    # 1. OS-level check
    if not is_pscad_process_running():
        pscad_instance = None
        raise RuntimeError("PSCAD process (PSCAD.exe) is not running on the system.")
    
    # 2. Heartbeat check (RMI check)
    try:
        # is_alive() is a quick check on the connection
        if not pscad_instance.is_alive():
             pscad_instance = None
             raise RuntimeError("Connection to PSCAD lost.")
        
        # is_busy() triggers a real RMI call to verify responsiveness
        pscad_instance.is_busy()
    except Exception as e:
        pscad_instance = None
        raise RuntimeError(f"PSCAD is unresponsive or crashed: {str(e)}")
        
    return pscad_instance

async def run_in_executor(func: Callable, *args, **kwargs) -> Any:
    """Run a PSCAD call in a separate thread with a timeout to prevent hangs."""
    loop = asyncio.get_running_loop()
    
    def wrapped_call():
        with pscad_lock:
            return func(*args, **kwargs)
            
    try:
        # We use a wrapper to handle the timeout at the asyncio level
        return await asyncio.wait_for(
            loop.run_in_executor(executor, wrapped_call), 
            timeout=COMMAND_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.error(f"Command {func.__name__} timed out after {COMMAND_TIMEOUT}s. PSCAD might be frozen.")
        raise RuntimeError(f"PSCAD timed out while executing {func.__name__}. It might be frozen or showing a dialog.")
    except Exception as e:
        logger.error(f"Error executing {func.__name__}: {str(e)}")
        raise

# --- MCP Tools ---

@mcp.tool()
async def get_local_pscad() -> str:
    """
    Attach to a running PSCAD instance or launch a new local one.
    Automatically detects the environment and recovers from stale connections.
    """
    global pscad_instance
    try:
        # application() is the most robust way to get a local instance
        pscad_instance = await run_in_executor(mhi.pscad.application)
        return f"Successfully attached to PSCAD {pscad_instance.version} (Local Approach)."
    except Exception as e:
        return f"Failed to get local PSCAD: {str(e)}"

@mcp.tool()
async def repair_connection() -> str:
    """
    Force-reset the connection to PSCAD. Use this if commands are failing or hanging.
    It will try to reconnect to the existing process.
    """
    global pscad_instance
    pscad_instance = None # Invalidate current handle
    return await get_local_pscad()

@mcp.tool()
async def get_pscad_status() -> Dict[str, Any]:
    """Get detailed health and status of the PSCAD instance and connection."""
    process_running = is_pscad_process_running()
    
    if pscad_instance is None:
        return {"connected": False, "process_running": process_running}
    
    try:
        pscad = get_pscad_safe()
        return {
            "connected": True,
            "process_running": True,
            "version": pscad.version,
            "busy": pscad.is_busy(),
            "licensed": pscad.licensed(),
            "workspace": str(pscad.workspace_path),
            "projects": pscad.project_names()
        }
    except Exception as e:
        return {
            "connected": True, 
            "status": "UNRESPONSIVE",
            "process_running": process_running,
            "error": str(e)
        }

@mcp.tool()
async def sync_documentation() -> str:
    """
    Robustly refresh the local documentation reference from the installed package.
    Handles property descriptors and member-level errors gracefully.
    """
    import pydoc, inspect
    docs_dir = os.path.join(os.getcwd(), "docs")
    os.makedirs(docs_dir, exist_ok=True)
    
    modules = ["mhi.pscad", "mhi.pscad.project", "mhi.pscad.canvas", "mhi.pscad.component"]
    results = []
    
    for mod_name in modules:
        try:
            # We use a custom crawler if pydoc.render_doc fails
            try:
                content = pydoc.render_doc(mod_name, renderer=pydoc.plaintext)
            except Exception:
                # Fallback: manual member inspection
                import importlib
                mod = importlib.import_module(mod_name)
                content = f"FALLBACK HELP FOR {mod_name}\n"
                for name, obj in inspect.getmembers(mod):
                    if not name.startswith('_'):
                        content += f"\n--- {name} ---\n{getattr(obj, '__doc__', 'No docstring')}\n"
            
            file_path = os.path.join(docs_dir, f"pydoc_{mod_name.replace('.', '_')}.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            results.append(f"Synced {mod_name}")
        except Exception as e:
            results.append(f"Failed {mod_name}: {str(e)}")
            
    return "\n".join(results)

@mcp.tool()
async def run_project(project_name: str) -> str:
    """
    Run a simulation project with safety checks (licensing and responsiveness).
    """
    pscad = get_pscad_safe()
    
    if not pscad.licensed():
         return f"Error: No valid PSCAD license found. Simulation cannot start."
         
    try:
        project = await run_in_executor(pscad.project, project_name)
        # Verify it's a case, not a library
        if "Library" in str(type(project)):
             return f"Error: '{project_name}' is a Library and cannot be run."
             
        await run_in_executor(project.run)
        return f"Project '{project_name}' simulation started successfully."
    except Exception as e:
        return f"Failed to run project: {str(e)}"

# --- Forwarding other tools with the robust executor pattern ---

@mcp.tool()
async def list_projects() -> List[Dict[str, str]]:
    pscad = get_pscad_safe()
    return await run_in_executor(pscad.projects)

@mcp.tool()
async def load_projects(filenames: List[str]) -> str:
    pscad = get_pscad_safe()
    abs_paths = [os.path.abspath(f) for f in filenames]
    await run_in_executor(pscad.load, *abs_paths)
    return f"Loaded: {', '.join(abs_paths)}"

@mcp.tool()
async def get_project_output(project_name: str) -> str:
    pscad = get_pscad_safe()
    project = await run_in_executor(pscad.project, project_name)
    return await run_in_executor(project.output)

@mcp.tool()
async def read_output_file(file_path: str) -> Dict[str, Any]:
    """Read PSCAD results (.out/.psout) with graceful fallback."""
    if not PSOUT_AVAILABLE:
        return {"error": "mhi-psout package is missing. Cannot parse binary results."}
    
    try:
        # Use absolute path for local robustness
        abs_path = os.path.abspath(file_path)
        with mhi.psout.open(abs_path) as psout:
            data = {}
            for channel in psout.channels():
                data[channel.name] = psout.channel(channel.name).values().tolist()
            return {"channels": list(data.keys()), "data": data}
    except Exception as e:
        return {"error": f"Failed to read output: {str(e)}"}

@mcp.tool()
async def quit_pscad() -> str:
    global pscad_instance
    if pscad_instance:
        try:
            await run_in_executor(pscad_instance.quit)
            pscad_instance = None
            return "PSCAD terminated."
        except Exception as e:
            return f"Error during quit: {str(e)}"
    return "Not connected."

if __name__ == "__main__":
    mcp.run()
