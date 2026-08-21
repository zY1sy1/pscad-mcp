import json
from dataclasses import asdict

from pscad_mcp.core.service import _ERROR_GUIDANCE
from pscad_mcp.hvdc.models import (
    HvdcReturnPath,
    HvdcSourceRef,
    HvdcTopologySummary,
)


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
