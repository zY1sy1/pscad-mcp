import json
from dataclasses import asdict

from pscad_mcp.hvdc.scanner import scan_project


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
