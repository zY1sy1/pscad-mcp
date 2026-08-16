import json
from dataclasses import asdict
from pathlib import Path

from pscad_mcp.hvdc.scanner import scan_project


REACHABLE_FIXTURE = Path(__file__).parent / "fixtures" / "hvdc" / "reachable_definitions.pscx"


def test_scanner_extracts_definitions_components_labels_and_source(tmp_path):
    path = tmp_path / "difforder_new.pscx"
    path.write_text(
        """<project version='4.6.2'><definitions>
      <Definition name='RectCC'/><Definition name='InverterPole'/>
      <Definition name='loadbreaker_3'/><Definition name='TL1'/>
      </definitions><canvas name='Main'><component id='7' name='B1'
      definition='master:loadbreaker_3'><parameter name='trip' value='1'/>
      <label>DC breaker</label></component><label>Idc</label></canvas></project>""",
        encoding="utf-8",
    )
    evidence = scan_project(path, canvas_name="Main")
    assert evidence.project_name == "difforder_new"
    assert evidence.pscad_version == "4.6.2"
    assert "RectCC" in evidence.definitions
    assert evidence.components[0].source.component_id == "7"
    assert any(label.text == "Idc" for label in evidence.labels)
    assert json.loads(json.dumps(asdict(evidence)))


def test_scanner_reports_missing_canvas_as_warning(tmp_path):
    path = tmp_path / "case.pscx"
    path.write_text("<project><definitions /></project>", encoding="utf-8")
    evidence = scan_project(path, canvas_name="Main")
    assert any("canvas" in warning.lower() for warning in evidence.warnings)


def test_scanner_extracts_real_pscad_462_user_components_and_evidence(tmp_path):
    path = tmp_path / "real_shape.pscx"
    path.write_text(
        """<project name='real_shape' version='4.6.2'><definitions>
        <Definition classid='UserCmpDefn' name='RectCC' instances='2'/>
        <Definition classid='UserCmpDefn' name='Main'><schematic classid='UserCanvas'>
          <User classid='UserCmp' id='610346983' name='' defn='master:breaker1'>
            <paramlist><param name='NAME' value='BRK1'/><parameter name='trip' value='1'/></paramlist>
            <Port id='3' classid='Port' name='LB1'/>
          </User>
          <User classid='UserCmp' id='1728450176' name='master:datalabel' defn='master:datalabel'>
            <paramlist><param name='Name' value='BrkOrd1'/></paramlist>
          </User>
          <text>DC breaker protection</text>
        </schematic></Definition></definitions></project>""",
        encoding="utf-8",
    )

    evidence = scan_project(path, canvas_name="Main")

    assert evidence.project_name == "real_shape"
    assert evidence.pscad_version == "4.6.2"
    assert "RectCC" in evidence.definitions
    breaker = next(item for item in evidence.components if item.component_id == "610346983")
    assert breaker.name == "BRK1"
    assert breaker.definition == "master:breaker1"
    assert breaker.parameters == {"NAME": "BRK1", "trip": "1"}
    assert breaker.ports == ({"id": "3", "classid": "Port", "name": "LB1"},)
    assert breaker.source.project_path == str(path.resolve())
    assert breaker.source.canvas_name == "Main"
    labels = {(item.text, item.kind, item.source.component_id) for item in evidence.labels}
    assert ("BrkOrd1", "datalabel", "1728450176") in labels
    assert ("DC breaker protection", "text", None) in labels


def test_scanner_preserves_simplified_fixture_support(tmp_path):
    path = tmp_path / "simple.pscx"
    path.write_text(
        "<project><canvas name='Main'><component id='7' name='B1' definition='breaker'>"
        "<parameter name='trip' value='1'/><label>DC breaker</label></component></canvas></project>",
        encoding="utf-8",
    )
    evidence = scan_project(path)
    assert evidence.components[0].name == "B1"
    assert evidence.components[0].parameters == {"trip": "1"}
    assert any(item.text == "DC breaker" for item in evidence.labels)


def test_scanner_aggregates_only_reachable_definition_schematics_with_provenance():
    evidence = scan_project(REACHABLE_FIXTURE, canvas_name="Main")
    by_id = {component.component_id: component for component in evidence.components}
    assert {"1", "2", "10", "11", "12", "20"} <= set(by_id)
    assert "99" not in by_id
    assert by_id["10"].source.canvas_name == "BreakerBlock"
    assert by_id["20"].source.canvas_name == "LineBlock"
    assert {port["name"] for port in by_id["20"].ports} == {"P1", "P2"}
    imc = next(label for label in evidence.labels if label.text == "IMC")
    assert imc.source.canvas_name == "BreakerBlock"
