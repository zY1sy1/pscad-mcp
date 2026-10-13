import hashlib

import pytest

from pscad_mcp.builders.blueprint.corpus_extractor import extract_project
from pscad_mcp.builders.blueprint.corpus_models import CorpusDefinitionSource, CorpusSource
from pscad_mcp.builders.blueprint.corpus_relations import materialize_instance_ports
from pscad_mcp.builders.blueprint.definition_catalog import load_definition_catalog
from pscad_mcp.core.backend.base import BackendError


def ports(tmp_path, master_text, parameter_text=""):
    project = tmp_path / "case.pscx"
    project.write_text('<project name="Case" version="4.6.2" Target="EMTDC"><definitions>'
                       '<Definition name="Main"><schematic><User id="1" defn="master:test" x="0" y="0">'
                       + parameter_text + '</User></schematic></Definition></definitions></project>', encoding="utf-8")
    payload = project.read_bytes()
    graph = extract_project(tmp_path, CorpusSource("case", project.name, len(payload),
                            hashlib.sha256(payload).hexdigest(), ("4.6.2",), ()),
                            schema_version=2, normalization_profile="pscad-xml-v2")
    master = tmp_path / "master.pslx"
    master.write_text('<project name="master" version="4.6.2"><definitions><Definition name="test">'
                      + master_text + '</Definition></definitions></project>', encoding="utf-8")
    payload = master.read_bytes()
    source = CorpusDefinitionSource("master", master.name, len(payload), hashlib.sha256(payload).hexdigest(),
                                    ("4.6.2",), "ports-and-classification-v1")
    return materialize_instance_ports(graph, load_definition_catalog((source,), {("master", "4.6.2"): master})).ports


def test_declared_vector_width_is_not_replaced_by_scalar_one(tmp_path):
    observed = ports(tmp_path, '''
    <form><parameter name="Dim" type="Integer"><value>1</value></parameter></form>
    <svg><port name="B:Dim" model="Transfer" dim="0"/></svg>''',
                     '<paramlist><param name="Dim" value="3"/></paramlist>')
    assert observed[0].dimension == 3


def test_vector_merge_width_follows_admitted_integer_computations(tmp_path):
    observed = ports(tmp_path, '''
    <svg><port name="B:Dim" model="Transfer" dim="0"/></svg>
    <script><segment name="Computations">INTEGER Begin1 = 1
INTEGER End1 = Begin1 + Dim1 - 1
INTEGER Begin2 = Begin1 + Dim1
INTEGER End2 = Begin2 + Dim2 - 1
INTEGER Dim = End2
#IF N&gt;2
INTEGER Dim = Dim + Dim3
#ENDIF</segment></script>''',
                     '<paramlist><param name="N" value="3"/><param name="Dim1" value="1"/>'
                     '<param name="Dim2" value="1"/><param name="Dim3" value="1"/></paramlist>')
    assert observed[0].dimension == 3


def test_auto_width_signal_port_is_recorded_as_unspecified(tmp_path):
    observed = ports(tmp_path, '<svg><port name="A" model="Transfer" dim="0"/></svg>')
    assert observed[0].dimension is None


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "nan", "arbitrary()"])
def test_active_vector_port_rejects_nonpositive_or_unproved_width(tmp_path, value):
    with pytest.raises(BackendError) as error:
        ports(tmp_path, '<svg><port name="B:Dim" model="Transfer" dim="0"/></svg>',
              '<paramlist><param name="Dim" value="' + value + '"/></paramlist>')
    assert error.value.code == "CORPUS_PORT_GEOMETRY_UNRESOLVED"


def test_computed_width_does_not_execute_function_calls(tmp_path):
    with pytest.raises(BackendError) as error:
        ports(tmp_path, '<svg><port name="B:Dim" model="Transfer" dim="0"/></svg>'
              '<script><segment name="Computations">INTEGER Dim = arbitrary()</segment></script>')
    assert error.value.code == "CORPUS_PORT_GEOMETRY_UNRESOLVED"
