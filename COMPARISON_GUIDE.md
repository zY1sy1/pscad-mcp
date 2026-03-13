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
The user simply provides a goal to the AI:

**User Prompt:**
> "Launch PSCAD, load the vdiv project, set R1 to 100 ohms and run it. Summarize the output messages for me."

**What happens behind the scenes (The MCP Advantage):**
1. **Auto-Connection**: MCP uses `get_local_pscad` to find an existing instance (Saving 10s of startup time).
2. **Watchdog Protection**: If `project.run()` takes too long to respond, the MCP Executor triggers a timeout instead of hanging the AI.
3. **Contextual Knowledge**: The AI reads `docs/pydoc_mhi_pscad_project.txt` to know that `run_status` returns a tuple, something a human might forget.
4. **Data Translation**: The binary results are translated into a JSON summary automatically.

## Summary of Value
| Feature | Manual Scripting | MCP Server |
| :--- | :--- | :--- |
| **Development Speed** | Slow (Coding required) | Instant (Conversational) |
| **Maintenance** | High (Scripts break on API update) | Low (AI adapts via `sync_documentation`) |
| **Accessibility** | Limited to Programmers | Available to all Power Engineers |
| **Stability** | Fragile (COM hangs) | Robust (Watchdogs & OS monitoring) |
