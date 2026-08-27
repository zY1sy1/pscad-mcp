from dataclasses import dataclass
from types import MappingProxyType

from mcp.types import ToolAnnotations


@dataclass(frozen=True)
class ToolSpec:
    name: str
    group: str
    description: str
    read_only: bool
    destructive: bool
    idempotent: bool
    open_world: bool
    backend_support: frozenset[str] = frozenset({"legacy", "modern"})
    limitation_code: str | None = None

    def annotations(self) -> ToolAnnotations:
        return ToolAnnotations(
            title=self.name.replace("_", " ").title(),
            readOnlyHint=self.read_only,
            destructiveHint=self.destructive,
            idempotentHint=self.idempotent,
            openWorldHint=self.open_world,
        )


TOOL_GROUPS = MappingProxyType(
    {
        "core": frozenset(
            {
                "get_local_pscad",
                "get_pscad_status",
                "sync_documentation",
                "list_documentation",
                "read_documentation",
                "repair_connection",
                "quit_pscad",
                "load_projects",
                "list_projects",
                "run_project",
                "get_run_status",
                "find_components",
                "get_component_parameters",
                "set_component_parameters",
                "validate_component_parameters",
                "pause_simulation",
                "stop_simulation",
                "get_project_settings",
                "set_project_settings",
                "get_project_output",
                "read_output_file",
                "list_simulation_sets",
                "run_simulation_set",
                "add_task_to_set",
                "create_simulation_set",
                "remove_simulation_set",
                "list_simulation_set_tasks",
                "remove_tasks_from_set",
                "get_simulation_task_parameters",
                "set_simulation_task_parameters",
                "get_simulation_set_details",
                "create_case",
                "create_library",
                "save_project",
                "save_project_as",
                "build_project",
                "build_all_projects",
                "get_project_definitions",
                "add_component",
                "create_component",
                "create_wire",
                "create_bus",
                "create_connection",
                "connect_ports",
                "create_annotation",
                "create_graph_frame",
                "create_control_frame",
                "list_canvas_components",
                "find_empty_space",
                "delete_components",
                "get_component_location",
                "set_component_location",
                "rotate_component",
                "mirror_component",
                "clone_component",
                "get_component_ports",
                "get_component_port",
                "enable_component",
                "disable_component",
                "delete_component",
            }
        ),
        "hvdc": frozenset(
            {
                "inspect_hvdc_project",
                "get_hvdc_assets",
                "get_hvdc_mappings",
                "validate_hvdc_project",
                "run_hvdc_scenario",
                "get_hvdc_scenario_status",
                "analyze_hvdc_results",
                "compare_hvdc_scenarios",
                "list_hvdc_profiles",
                "register_hvdc_profile",
            }
        ),
        "lcc": frozenset(
            {
                "plan_lcc_model",
                "build_lcc_model",
                "get_lcc_build_status",
                "validate_lcc_model",
            }
        ),
        "parametric_lcc": frozenset(
            {
                "derive_lcc_parameters",
                "audit_lcc_template",
                "plan_parametric_lcc_model",
                "build_parametric_lcc_model",
                "get_parametric_lcc_build_status",
                "validate_lcc_operating_modes",
            }
        ),
        "learning": frozenset(
            {
                "record_goal_failure",
                "review_improvement_backlog",
                "clear_learning_history",
            }
        ),
    }
)

COMPATIBILITY_TOOL_NAMES = frozenset().union(*TOOL_GROUPS.values())
FULL_TOOL_NAMES = COMPATIBILITY_TOOL_NAMES

_GROUP_BY_NAME = {
    name: group for group, names in TOOL_GROUPS.items() for name in names
}
_ALL_BACKENDS = frozenset({"legacy", "modern"})
_SERVER_LOCAL = frozenset()


def _spec(
    name: str,
    description: str,
    *,
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    open_world: bool = True,
    backend_support: frozenset[str] = _ALL_BACKENDS,
    limitation_code: str | None = None,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        group=_GROUP_BY_NAME[name],
        description=description,
        read_only=read_only,
        destructive=destructive,
        idempotent=idempotent,
        open_world=open_world,
        backend_support=backend_support,
        limitation_code=limitation_code,
    )


COMPATIBILITY_TOOL_SPECS = MappingProxyType(
    {
        "get_local_pscad": _spec(
            "get_local_pscad",
            "Attach to a running local PSCAD instance or launch a new one.",
        ),
        "get_pscad_status": _spec(
            "get_pscad_status",
            "Get detailed health and status of the PSCAD instance.",
            read_only=True,
            idempotent=True,
        ),
        "sync_documentation": _spec(
            "sync_documentation",
            "Synchronize AI reference files with the currently installed library version.",
            backend_support=_SERVER_LOCAL,
        ),
        "list_documentation": _spec(
            "list_documentation",
            "List available PSCAD API documentation modules that can be read.",
            read_only=True,
            idempotent=True,
            backend_support=_SERVER_LOCAL,
        ),
        "read_documentation": _spec(
            "read_documentation",
            "Read the Markdown documentation for a specific PSCAD module (e.g., 'mhi.pscad.types').",
            read_only=True,
            idempotent=True,
            backend_support=_SERVER_LOCAL,
        ),
        "repair_connection": _spec(
            "repair_connection",
            "Force-reset the connection to PSCAD.",
        ),
        "quit_pscad": _spec(
            "quit_pscad",
            "Terminate the PSCAD application.",
            destructive=True,
        ),
        "load_projects": _spec(
            "load_projects",
            "Load projects or workspace into PSCAD.",
        ),
        "list_projects": _spec(
            "list_projects",
            "List all projects in the workspace.",
            read_only=True,
            idempotent=True,
        ),
        "run_project": _spec(
            "run_project",
            "Start simulation for a given project.",
        ),
        "get_run_status": _spec(
            "get_run_status",
            "Get simulation progress and state.",
            read_only=True,
            idempotent=True,
        ),
        "find_components": _spec(
            "find_components",
            "Find components matching criteria in a project.",
            read_only=True,
            idempotent=True,
        ),
        "get_component_parameters": _spec(
            "get_component_parameters",
            "Get all parameter values for a specific component by its ID.",
            read_only=True,
            idempotent=True,
        ),
        "set_component_parameters": _spec(
            "set_component_parameters",
            "Set parameter values for a specific component.",
        ),
        "validate_component_parameters": _spec(
            "validate_component_parameters",
            "Validate if the given parameters are within the legal range for a component.",
            read_only=True,
            idempotent=True,
        ),
        "pause_simulation": _spec(
            "pause_simulation",
            "Pause the running simulation for a project.",
        ),
        "stop_simulation": _spec(
            "stop_simulation",
            "Stop/terminate the running simulation for a project.",
        ),
        "get_project_settings": _spec(
            "get_project_settings",
            "Get project settings or a normalized parameter-grid view.",
            read_only=True,
            idempotent=True,
        ),
        "set_project_settings": _spec(
            "set_project_settings",
            "Update project settings or run a parameter-grid action.",
        ),
        "get_project_output": _spec(
            "get_project_output",
            "Get text output or normalized structured messages from a PSCAD project.",
            read_only=True,
            idempotent=True,
        ),
        "read_output_file": _spec(
            "read_output_file",
            "Read sampled traces or bounded channel summaries from a PSOUT file.",
            read_only=True,
            idempotent=True,
        ),
        "list_simulation_sets": _spec(
            "list_simulation_sets",
            "List all simulation sets defined in the PSCAD application.",
            read_only=True,
            idempotent=True,
        ),
        "run_simulation_set": _spec(
            "run_simulation_set",
            "Run a specific simulation set (batch of tasks).",
        ),
        "add_task_to_set": _spec(
            "add_task_to_set",
            "Add a project task to an existing simulation set.",
        ),
        "create_simulation_set": _spec(
            "create_simulation_set",
            "Create a workspace-level simulation set.",
        ),
        "remove_simulation_set": _spec(
            "remove_simulation_set",
            "Remove a workspace-level simulation set after confirmation.",
            destructive=True,
        ),
        "list_simulation_set_tasks": _spec(
            "list_simulation_set_tasks",
            "List the tasks assigned to a workspace-level simulation set.",
            read_only=True,
            idempotent=True,
        ),
        "remove_tasks_from_set": _spec(
            "remove_tasks_from_set",
            "Remove tasks from a simulation set after confirmation.",
            destructive=True,
        ),
        "get_simulation_task_parameters": _spec(
            "get_simulation_task_parameters",
            "Read normalized task parameters from a simulation set.",
            read_only=True,
            idempotent=True,
        ),
        "set_simulation_task_parameters": _spec(
            "set_simulation_task_parameters",
            "Update supported simulation task parameters and verify read-back.",
            idempotent=True,
        ),
        "get_simulation_set_details": _spec(
            "get_simulation_set_details",
            "Read normalized details for a workspace-level simulation set.",
            read_only=True,
            idempotent=True,
        ),
        "create_case": _spec(
            "create_case",
            "Create a new empty PSCAD case project (.pscx).",
        ),
        "create_library": _spec(
            "create_library",
            "Create a new empty PSCAD library project (.pslx).",
        ),
        "save_project": _spec(
            "save_project",
            "Save a project to disk.",
        ),
        "save_project_as": _spec(
            "save_project_as",
            "Save a project under a new filename.",
        ),
        "build_project": _spec(
            "build_project",
            "Compile/build a single project. May take a long time for large projects.",
        ),
        "build_all_projects": _spec(
            "build_all_projects",
            "Compile/build all projects in the workspace.",
        ),
        "get_project_definitions": _spec(
            "get_project_definitions",
            "List all component definitions available in a project.",
            read_only=True,
            idempotent=True,
        ),
        "add_component": _spec(
            "add_component",
            "Add a library component to a canvas.",
        ),
        "create_component": _spec(
            "create_component",
            "Create a component from a scoped definition such as master:source3.",
        ),
        "create_wire": _spec(
            "create_wire",
            "Create an orthogonal wire through the supplied vertices.",
        ),
        "create_bus": _spec(
            "create_bus",
            "Create an electrical bus through the supplied vertices.",
        ),
        "create_connection": _spec(
            "create_connection",
            "Connect two points using a wire or matching node labels.",
        ),
        "connect_ports": _spec(
            "connect_ports",
            "Connect two named component ports with a wire.",
        ),
        "create_annotation": _spec(
            "create_annotation",
            "Create a two-line annotation.",
        ),
        "create_graph_frame": _spec(
            "create_graph_frame",
            "Create an empty graph frame.",
        ),
        "create_control_frame": _spec(
            "create_control_frame",
            "Create an empty runtime control frame.",
        ),
        "list_canvas_components": _spec(
            "list_canvas_components",
            "List normalized objects on a canvas.",
            read_only=True,
            idempotent=True,
        ),
        "find_empty_space": _spec(
            "find_empty_space",
            "Find the closest empty rectangle near a point.",
            read_only=True,
            idempotent=True,
        ),
        "delete_components": _spec(
            "delete_components",
            "Delete components after explicit confirmation.",
            destructive=True,
        ),
        "get_component_location": _spec(
            "get_component_location",
            "Get a component's grid location.",
            read_only=True,
            idempotent=True,
        ),
        "set_component_location": _spec(
            "set_component_location",
            "Move a component to a grid location.",
            idempotent=True,
        ),
        "rotate_component": _spec(
            "rotate_component",
            "Rotate a component right, left, or 180 degrees.",
        ),
        "mirror_component": _spec(
            "mirror_component",
            "Mirror a component horizontally or vertically.",
        ),
        "clone_component": _spec(
            "clone_component",
            "Duplicate a component at a new grid location.",
        ),
        "get_component_ports": _spec(
            "get_component_ports",
            "List a component's named ports and absolute locations.",
            read_only=True,
            idempotent=True,
        ),
        "get_component_port": _spec(
            "get_component_port",
            "Get one named component port.",
            read_only=True,
            idempotent=True,
        ),
        "enable_component": _spec(
            "enable_component",
            "Enable a component.",
        ),
        "disable_component": _spec(
            "disable_component",
            "Disable a component.",
        ),
        "delete_component": _spec(
            "delete_component",
            "Delete a component after explicit confirmation.",
            destructive=True,
        ),
        "inspect_hvdc_project": _spec(
            "inspect_hvdc_project",
            "Inspect an HVDC project's topology, assets, mappings, and evidence.",
            read_only=True,
            idempotent=True,
        ),
        "get_hvdc_assets": _spec(
            "get_hvdc_assets",
            "Get normalized HVDC assets, optionally filtered by kind.",
            read_only=True,
            idempotent=True,
        ),
        "get_hvdc_mappings": _spec(
            "get_hvdc_mappings",
            "Get canonical HVDC signal mappings and their evidence.",
            read_only=True,
            idempotent=True,
        ),
        "validate_hvdc_project": _spec(
            "validate_hvdc_project",
            "Validate an HVDC project against a named mapping profile.",
            read_only=True,
            idempotent=True,
        ),
        "run_hvdc_scenario": _spec(
            "run_hvdc_scenario",
            "Apply and run a validated HVDC scenario after required confirmation.",
        ),
        "get_hvdc_scenario_status": _spec(
            "get_hvdc_scenario_status",
            "Get the current status and bounded evidence for an HVDC scenario.",
            read_only=True,
            idempotent=True,
        ),
        "analyze_hvdc_results": _spec(
            "analyze_hvdc_results",
            "Analyze selected metrics from a completed HVDC scenario.",
            read_only=True,
            idempotent=True,
        ),
        "compare_hvdc_scenarios": _spec(
            "compare_hvdc_scenarios",
            "Compare selected metrics across completed HVDC scenarios.",
            read_only=True,
            idempotent=True,
        ),
        "list_hvdc_profiles": _spec(
            "list_hvdc_profiles",
            "List built-in and workspace-local HVDC mapping profiles.",
            read_only=True,
            idempotent=True,
            backend_support=_SERVER_LOCAL,
        ),
        "register_hvdc_profile": _spec(
            "register_hvdc_profile",
            "Register a workspace-local HVDC mapping profile after confirmation.",
            backend_support=_SERVER_LOCAL,
        ),
        "plan_lcc_model": _spec(
            "plan_lcc_model",
            "Plan a fixed CIGRE LCC model build without changing the workspace.",
            read_only=True,
            idempotent=True,
        ),
        "build_lcc_model": _spec(
            "build_lcc_model",
            "Start a confirmed fixed CIGRE LCC model build from a matching plan.",
            backend_support=frozenset({"legacy"}),
            limitation_code="LCC_BUILD_UNAVAILABLE",
        ),
        "get_lcc_build_status": _spec(
            "get_lcc_build_status",
            "Get the current status and evidence for a fixed LCC model build.",
            read_only=True,
            idempotent=True,
            backend_support=_SERVER_LOCAL,
        ),
        "validate_lcc_model": _spec(
            "validate_lcc_model",
            "Validate a fixed LCC model and optional output evidence.",
            read_only=True,
            idempotent=True,
            backend_support=_SERVER_LOCAL,
        ),
        "derive_lcc_parameters": _spec(
            "derive_lcc_parameters",
            "Derive deterministic LCC design parameters from a parametric request.",
            read_only=True,
            idempotent=True,
            open_world=False,
            backend_support=_SERVER_LOCAL,
        ),
        "audit_lcc_template": _spec(
            "audit_lcc_template",
            "Audit an LCC template and report binding evidence without modifying it.",
            read_only=True,
            idempotent=True,
            backend_support=_SERVER_LOCAL,
        ),
        "plan_parametric_lcc_model": _spec(
            "plan_parametric_lcc_model",
            "Plan a parameterized LCC model build without changing the workspace.",
            read_only=True,
            idempotent=True,
            backend_support=_SERVER_LOCAL,
        ),
        "build_parametric_lcc_model": _spec(
            "build_parametric_lcc_model",
            "Start a confirmed parameterized LCC build from a matching plan.",
        ),
        "get_parametric_lcc_build_status": _spec(
            "get_parametric_lcc_build_status",
            "Get the current status and evidence for a parameterized LCC build.",
            read_only=True,
            idempotent=True,
            open_world=False,
            backend_support=_SERVER_LOCAL,
        ),
        "validate_lcc_operating_modes": _spec(
            "validate_lcc_operating_modes",
            "Validate an ordered schedule of LCC operating-mode events.",
            read_only=True,
            idempotent=True,
            open_world=False,
            backend_support=_SERVER_LOCAL,
        ),
        "record_goal_failure": _spec(
            "record_goal_failure",
            "Record a bounded goal-level failure signal for local improvement review.",
            open_world=False,
            backend_support=_SERVER_LOCAL,
        ),
        "review_improvement_backlog": _spec(
            "review_improvement_backlog",
            "Review bounded local improvement candidates and optionally mark them notified.",
            open_world=False,
            backend_support=_SERVER_LOCAL,
        ),
        "clear_learning_history": _spec(
            "clear_learning_history",
            "Clear local learning history and backlog records after confirmation.",
            destructive=True,
            open_world=False,
            backend_support=_SERVER_LOCAL,
        ),
    }
)

TOOL_SPECS = COMPATIBILITY_TOOL_SPECS
