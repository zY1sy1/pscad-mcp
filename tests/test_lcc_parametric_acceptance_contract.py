import pytest

from pscad_mcp.hvdc.builders.lcc.acceptance import validate_parametric_acceptance_contract
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


def _evidence(status="PASS"):
    return {
        "status": status,
        "compile": {"status": "succeeded", "project_sha256": "a" * 64},
        "output": {"path": "C:/workspace/run.out", "sha256": "b" * 64},
        "selectors": [
            {"name": "gamma", "selector": "Main/Gamma", "units": "deg"},
            {"name": "alpha", "selector": "Main/Alpha", "units": "deg"},
            {"name": "vdc_positive", "selector": "Main/VdcP", "units": "kV"},
            {"name": "vdc_negative", "selector": "Main/VdcN", "units": "kV"},
            {"name": "idc_positive", "selector": "Main/IdcP", "units": "kA"},
            {"name": "idc_negative", "selector": "Main/IdcN", "units": "kA"},
            {"name": "neutral_current", "selector": "Main/In", "units": "kA"},
            {"name": "return_current", "selector": "Main/Ir", "units": "kA"},
        ],
        "derived_parameters": {"rated_power_mw": 1000.0, "dc_voltage_kv": 500.0},
    }


def test_parametric_acceptance_requires_compile_output_and_lcc_selectors():
    assert validate_parametric_acceptance_contract(_evidence())["status"] == "PASS"

    missing = _evidence()
    missing["selectors"] = missing["selectors"][:-1]
    assert validate_parametric_acceptance_contract(missing)["status"] == "INCOMPLETE_ANALYSIS"


def test_parametric_acceptance_rejects_unknown_units_and_bad_output_hash():
    evidence = _evidence()
    evidence["selectors"][0]["units"] = "unknown"
    assert validate_parametric_acceptance_contract(evidence)["status"] == "INCOMPLETE_ANALYSIS"

    evidence = _evidence()
    evidence["output"]["sha256"] = "bad"
    assert validate_parametric_acceptance_contract(evidence)["status"] == "INCOMPLETE_ANALYSIS"
