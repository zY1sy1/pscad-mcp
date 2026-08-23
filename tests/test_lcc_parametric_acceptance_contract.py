import pytest

from pscad_mcp.hvdc.builders.lcc.parametric_service import validate_parametric_acceptance_report


def test_acceptance_contract_requires_absolute_workspace_and_mode_evidence():
    report = {
        "schema_version": 1,
        "status": "PASS",
        "workspace": "C:/workspace/lcc-acceptance",
        "assets": {"blueprint.json": "a" * 64},
        "build": {"state": "published", "final_project_sha256": "b" * 64},
        "modes": [{"mode": "bipolar_run", "status": "PASS", "compile": True, "waveform": True}],
    }
    assert validate_parametric_acceptance_report(report)["valid"] is True


def test_acceptance_contract_rejects_pass_without_mode_evidence():
    report = {
        "schema_version": 1,
        "status": "PASS",
        "workspace": "C:/workspace/lcc-acceptance",
        "assets": {"blueprint.json": "a" * 64},
        "build": {"state": "published", "final_project_sha256": "b" * 64},
        "modes": [],
    }
    with pytest.raises(ValueError, match="mode evidence"):
        validate_parametric_acceptance_report(report)
