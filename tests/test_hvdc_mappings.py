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
    assert any(mapping.status == "conflict" for mapping in result.mappings)


def test_mapping_honors_source_kinds(tmp_path):
    path = tmp_path / "case.pscx"
    path.write_text(
        "<project><canvas name='Main'><label>Idc</label>"
        "<component id='8' name='master:datalabel' definition='master:datalabel'>"
        "<parameter name='Name' value='Vdc'/></component></canvas></project>",
        encoding="utf-8",
    )
    profile = {"mappings": [
        {"canonical": "dc_current", "aliases": ["Idc"], "source_kinds": ["meter"]},
        {"canonical": "dc_voltage", "aliases": ["Vdc"], "source_kinds": ["datalabel"]},
    ]}
    result = resolve_mappings(scan_project(path), profile)
    by_name = {mapping.canonical: mapping for mapping in result.mappings}
    assert by_name["dc_current"].status == "unresolved"
    assert by_name["dc_voltage"].status == "observed"


def test_one_character_alias_does_not_match_unrelated_substring(tmp_path):
    path = tmp_path / "case.pscx"
    path.write_text("<project><canvas name='Main'><label>protection trip</label></canvas></project>", encoding="utf-8")
    result = resolve_mappings(scan_project(path), load_profile("lcc_bipolar_generic"))
    active_power = next(mapping for mapping in result.mappings if mapping.canonical == "active_power")
    assert active_power.status == "unresolved"


def test_same_source_is_deduplicated_and_not_reused_across_canonicals(tmp_path):
    path = tmp_path / "case.pscx"
    path.write_text(
        "<project><canvas name='Main'><component id='9' name='controller' definition='control'>"
        "<parameter name='Name' value='fault command'/></component></canvas></project>",
        encoding="utf-8",
    )
    profile = {"mappings": [
        {"canonical": "breaker_command", "aliases": ["fault command"], "source_kinds": ["control"]},
        {"canonical": "fault_command", "aliases": ["fault command"], "source_kinds": ["control"]},
    ]}
    result = resolve_mappings(scan_project(path), profile)
    assert result.conflicts == ("breaker_command", "fault_command")
    assert all(mapping.status == "conflict" and mapping.source is None for mapping in result.mappings)


def test_source_is_not_reused_when_other_canonical_has_multiple_candidates(tmp_path):
    path = tmp_path / "case.pscx"
    path.write_text(
        "<project><canvas name='Main'><label>shared trip</label><label>alternate trip</label></canvas></project>",
        encoding="utf-8",
    )
    profile = {"mappings": [
        {"canonical": "protection_trip", "aliases": ["shared trip", "alternate trip"], "source_kinds": ["label"]},
        {"canonical": "breaker_status", "aliases": ["shared trip"], "source_kinds": ["label"]},
    ]}
    result = resolve_mappings(scan_project(path), profile)
    assert result.conflicts == ("protection_trip", "breaker_status")
    assert all(mapping.status == "conflict" for mapping in result.mappings)


def test_duplicate_text_candidates_from_one_parameter_are_one_source(tmp_path):
    path = tmp_path / "case.pscx"
    path.write_text(
        "<project><canvas name='Main'><component id='10' name='meter' definition='master:ammeter'>"
        "<parameter name='Name' value='IMC'/></component></canvas></project>",
        encoding="utf-8",
    )
    profile = {"mappings": [{"canonical": "dc_current", "aliases": ["IMC"], "source_kinds": ["meter"]}]}
    result = resolve_mappings(scan_project(path), profile)
    assert result.conflicts == ()
    assert result.mappings[0].status == "observed"
