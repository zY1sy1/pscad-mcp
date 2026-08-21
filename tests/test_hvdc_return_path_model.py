import json
from dataclasses import asdict
from pathlib import Path

from pscad_mcp.core.service import _ERROR_GUIDANCE
from pscad_mcp.hvdc.models import (
    HvdcConnectionRecord,
    HvdcReturnPath,
    HvdcSourceRef,
    HvdcTopologySummary,
)
from pscad_mcp.hvdc.scanner import scan_project


def test_return_path_summary_is_json_serializable():
    source = HvdcSourceRef(
        project_path="case.pscx",
        canvas_name="Main",
        component_id="42",
        definition="EarthElectrode",
    )
    path = HvdcReturnPath(
        mode="earth_return",
        segments=(source,),
        endpoints=(source,),
        closed=True,
        confidence=1.0,
        evidence=("EarthElectrode", "GroundReturn"),
        unresolved_questions=(),
    )
    summary = HvdcTopologySummary(
        family="lcc",
        polarity="bipolar",
        terminal_count=2,
        breaker_protection_present=False,
        dc_line_present=True,
        confidence=1.0,
        return_mode="earth_return",
        return_path_status="verified",
        return_path=(path,),
        pole_roles={"positive": source},
        neutral_assets=(source,),
        mode_evidence=("closed return graph",),
        evidence=("Rectifier",),
        unresolved_questions=(),
    )

    assert "earth_return" in json.dumps(asdict(summary))
    assert asdict(path)["closed"] is True


def test_unresolved_return_path_error_has_stable_guidance():
    assert _ERROR_GUIDANCE["HVDC_RETURN_PATH_UNRESOLVED"] == (
        False,
        "Inspect the return-path evidence and provide a project-qualified profile.",
    )


def test_scanner_preserves_connection_evidence(tmp_path: Path):
    source = tmp_path / "case.pscx"
    source.write_text(
        """<project version='4.6.2'>
          <canvas name='Main'>
            <component id='1' name='Neutral' definition='NeutralBus'>
              <port id='n1' name='N'/>
            </component>
            <component id='2' name='Electrode' definition='EarthElectrode'>
              <port id='e1' name='E'/>
            </component>
            <connection id='c1' from_component='1' from_port='n1'
                        to_component='2' to_port='e1'/>
          </canvas>
        </project>""",
        encoding="utf-8",
    )

    evidence = scan_project(source)
    assert len(evidence.connections) == 1
    connection = evidence.connections[0]
    assert isinstance(connection, HvdcConnectionRecord)
    assert connection.source_component_id == "1"
    assert connection.target_component_id == "2"
    assert connection.source_port == "n1"
    assert connection.target_port == "e1"
