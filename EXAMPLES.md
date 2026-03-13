# PSCAD MCP Server: Chat Examples & Prompts

This guide provides practical examples of how to interact with the PSCAD MCP server using AI assistants like Gemini CLI, Claude Code, or Claude Desktop.

---

## 🎯 High-Signal Prompt Ideas

### 🔍 Exploration & Documentation
*   "Connect to my local PSCAD instance and list all loaded projects."
*   "What documentation modules are available for the PSCAD API?"
*   "Read the documentation for the `mhi_pscad_component` module to see how to set parameters."

### ⚙️ Simulation Management
*   "Load the project at `C:\Projects\IEEE_9Bus.pscx` and start a simulation."
*   "Check the run status of the 'IEEE_9Bus' project. Is it still running?"
*   "Retrieve the simulation output messages for the current project to check for warnings."
*   "Change the 'Duration' of the 'IEEE_9Bus' project to 2.0 seconds and the 'TimeStep' to 100 microseconds."

### 🧩 Component Manipulation
*   "Find all 'Bus' components in the active project."
*   "Get all parameters for the component named 'Generator_1'."
*   "Update the 'Voltage' parameter of 'Bus10' to '230 [kV]', but validate the range first."
*   "Locate a component by its ID `10234` and tell me its current definition."

### 📊 Batching & Data Analysis
*   "List all simulation sets in the active project."
*   "Read the results from the latest `.psout` file for 'Wind_Farm_Test'."
*   "Add a new task to the 'Batch_Run' simulation set using the 'Scenario_HighLoad' configuration."

---

## 💬 Recorded Chat Example

**User:**
"Hey, I need to automate some tests. Can you connect to my local PSCAD, load the 'Wind_Farm_Test' project from my Documents, and find a component named 'MainTransformer'? I want to see its current 'Tap' setting."

**Assistant:**
> I will first establish a connection to your local PSCAD instance and then proceed to load the requested project and locate the component.

1.  **Tool Call:** `get_local_pscad()` → *Success (Attached to PSCAD v5.0.2)*
2.  **Tool Call:** `load_projects(filenames=["C:\\Users\\Lua\\Documents\\Wind_Farm_Test.pscx"])` → *Success*
3.  **Tool Call:** `find_components(project_name="Wind_Farm_Test", name="MainTransformer")` → *Success (Found 1 component, ID: 12345)*
4.  **Tool Call:** `get_component_parameters(project_name="Wind_Farm_Test", component_id=12345)` → *Returns Parameters*

**Assistant:**
"I've successfully connected to PSCAD and loaded your project. I found the 'MainTransformer' (ID: 12345). Its current 'Tap' setting is `1.02 [pu]`. Would you like me to adjust this value or run a simulation now?"

**User:**
"Actually, set the Tap to 1.05 and run the simulation. Let me know when it finishes."

**Assistant:**
> I'll update the component parameter and then start the project execution, monitoring its status until completion.

1.  **Tool Call:** `set_component_parameters(project_name="Wind_Farm_Test", component_id=12345, parameters={"Tap": "1.05"})` → *Success*
2.  **Tool Call:** `run_project(project_name="Wind_Farm_Test")` → *Success (Started)*
3.  **Tool Call:** `get_run_status(project_name="Wind_Farm_Test")` → *Returns ("Run", 45)*
4.  **Tool Call:** `get_run_status(project_name="Wind_Farm_Test")` → *Returns (None, None)*

**Assistant:**
"The Tap setting has been updated to 1.05, and the simulation for 'Wind_Farm_Test' is complete. No errors were reported in the output log. Would you like to see the final results or the output messages?"
