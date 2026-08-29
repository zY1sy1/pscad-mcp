from pscad_mcp.core.definition_metadata import master_definition_binding


def test_master_binding_uses_installed_pscad_names_and_explicit_port_mapping():
    binding = master_definition_binding("master:three_phase_source")
    assert binding.definition == "source3"
    assert binding.port_map == {"A": "A", "B": "B", "C": "C"}
    assert binding.parameter_map["Amplitude_kV"] == "Vm"


def test_master_binding_marks_three_phase_filter_as_expansion():
    binding = master_definition_binding("master:ac_filter_branch")
    assert binding.definition == "cfilter"
    assert binding.instances == 3
    assert binding.port_map == {"IN": "A", "OUT": "B"}
