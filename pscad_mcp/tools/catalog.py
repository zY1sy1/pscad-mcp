from types import MappingProxyType


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
