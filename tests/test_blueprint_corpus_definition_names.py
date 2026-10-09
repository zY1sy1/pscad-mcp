import hashlib

import pytest

from pscad_mcp.builders.blueprint.corpus_extractor import extract_project
from pscad_mcp.builders.blueprint.corpus_models import CorpusDefinitionSource, CorpusSource
from pscad_mcp.builders.blueprint.corpus_relations import materialize_instance_ports
from pscad_mcp.builders.blueprint.definition_catalog import load_definition_catalog
from pscad_mcp.core.backend.base import BackendError


def inputs(tmp_path, *, collision=False, mixed_case_condition=False):
    project = tmp_path / "case.pscx"
    params = '<paramlist><param name="Limit" value="1"/></paramlist>' if mixed_case_condition else ""
    project.write_text('''<project name="Case" version="4.6.2" Target="EMTDC"><definitions>
    <Definition name="Main"><svg/><schematic><User id="1" defn="master:var_switch" x="0" y="0">'''
                       + params + '</User></schematic></Definition></definitions></project>', encoding="utf-8")
    payload = project.read_bytes()
    graph = extract_project(tmp_path, CorpusSource("case", project.name, len(payload),
                            hashlib.sha256(payload).hexdigest(), ("4.6.2",), ()),
                            schema_version=2, normalization_profile="pscad-xml-v2")
    master = tmp_path / "master.pslx"
    extra = '<Definition name="var-switch"><svg/></Definition>' if collision else ""
    condition = "limit==1" if mixed_case_condition else "true"
    form = '<form><parameter name="Limit" type="Integer"><value>0</value></parameter></form>' if mixed_case_condition else ""
    master.write_text('''<project name="master" version="4.6.2"><definitions>
    <Definition name="var_switch">''' + form
                      + '<svg><port name="OUT" x="18" y="0" dim="1" model="Transfer">'
                      + condition + '</port></svg></Definition>' + extra + '</definitions></project>', encoding="utf-8")
    payload = master.read_bytes()
    declaration = CorpusDefinitionSource("master", master.name, len(payload), hashlib.sha256(payload).hexdigest(),
                                         ("4.6.2",), "ports-and-classification-v1")
    return graph, load_definition_catalog((declaration,), {("master", "4.6.2"): master})


def test_normalized_logical_definition_key_resolves_to_exact_admitted_physical_name(tmp_path):
    graph, catalog = inputs(tmp_path)
    materialized = materialize_instance_ports(graph, catalog)
    assert materialized.classifications[0].key == "definition:master:var-switch"
    assert materialized.classifications[0].physical_name == "var_switch"
    assert len(materialized.ports) == 1


def test_colliding_normalized_definition_names_are_rejected_instead_of_guessing(tmp_path):
    graph, catalog = inputs(tmp_path, collision=True)
    with pytest.raises(BackendError) as error:
        materialize_instance_ports(graph, catalog)
    assert error.value.code == "CORPUS_DEFINITION_AMBIGUOUS"


def test_vendor_port_condition_uses_declared_parameter_identity_despite_case(tmp_path):
    graph, catalog = inputs(tmp_path, mixed_case_condition=True)
    materialized = materialize_instance_ports(graph, catalog)
    assert materialized.ports[0].active is True
