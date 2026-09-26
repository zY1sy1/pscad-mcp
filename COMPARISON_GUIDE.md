# Automation Comparison: Traditional vs. MCP

## 1. Traditional Approach (The "Hard" Way)
To run a simple simulation and check results, an engineer must write:

```python
import mhi.pscad
import time

try:
    pscad = mhi.pscad.launch()
    project = pscad.load("C:\\temp\\vdiv.pscx")
    project.parameters(R1="100 [ohm]")
    project.run()
    
    # Must wait manually or poll
    while project.run_status()[0] == "Run":
        time.sleep(1)
        
    print(project.output())
except Exception as e:
    # If PSCAD freezes here, the script hangs forever
    print(f"Failed: {e}")
```

## 2. MCP Approach (The "Intelligent" Way)
The user simply provides a goal to GitHub Copilot CLI:

**User Prompt:**
> "Launch PSCAD, load the vdiv project, set R1 to 100 ohms and run it. Summarize the output messages for me."

**What happens behind the scenes (The MCP Advantage):**
1. **Managed Launch**: MCP uses `get_local_pscad` to launch a server-owned PSCAD instance; it never attaches to a GUI you opened yourself.
2. **Watchdog Protection**: If `project.run()` takes too long to respond, the MCP Executor triggers a timeout instead of hanging the AI.
3. **Contextual Knowledge**: The AI reads the synced `mhi.pscad.project` module with `read_documentation` (stored in local state, not in the repository) to know that `run_status` returns a tuple, something a human might forget.
4. **Data Translation**: The binary results are translated into a JSON summary automatically.

## Summary of Value
| Feature | Manual Scripting | MCP Server |
| :--- | :--- | :--- |
| **Development Speed** | Slow (Coding required) | Instant (Conversational) |
| **Maintenance** | High (Scripts break on API update) | Low (AI adapts via `sync_documentation`) |
| **Accessibility** | Limited to Programmers | Available to all Power Engineers |
| **Stability** | Fragile (COM hangs) | Robust (Watchdogs & OS monitoring) |
