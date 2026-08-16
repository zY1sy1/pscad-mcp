from pscad_mcp.hvdc.mappings import resolve_mappings
from pscad_mcp.hvdc.profiles import load_profile
from pscad_mcp.hvdc.scanner import scan_project


def test_mapping_aliases_resolve_observed_labels(tmp_path):
    path = tmp_path / "case.pscx"
    path.write_text("<project><canvas name='Main'><label>Idc</label><label>Vdc</label></canvas></project>", encoding="utf-8")
    result = resolve_mappings(scan_project(path), load_profile("lcc_bipolar_generic"))
    by_name = {mapping.canonical: mapping for mapping in result.mappings}
    assert by_name["dc_current"].status == "observed"
    assert by_name["dc_voltage"].status == "observed"
    assert result.unresolved


def test_profile_not_found_has_stable_error():
    import pytest
    from pscad_mcp.core.backend.base import BackendError
    with pytest.raises(BackendError) as raised:
        load_profile("does_not_exist")
    assert raised.value.code == "HVDC_PROFILE_NOT_FOUND"


def test_mapping_reads_component_parameters_and_reports_unit_conflict(tmp_path):
    path = tmp_path / "case.pscx"
    path.write_text("<project><canvas name='Main'><component id='4' name='meter' definition='meter'><parameter name='Idc' value='3 kA'/><parameter name='Vdc' value='500 V'/></component><label>Idc (kV)</label></canvas></project>", encoding="utf-8")
    result = resolve_mappings(scan_project(path), load_profile("lcc_bipolar_generic"))
    assert any(mapping.source and mapping.source.component_id == "4" for mapping in result.mappings)
    assert result.warnings
