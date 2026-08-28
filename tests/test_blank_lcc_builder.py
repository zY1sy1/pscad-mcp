from pscad_mcp.hvdc.builders.lcc.blank import BlankLccRequest, plan_blank_lcc
from pscad_mcp.hvdc.builders.lcc.acceptance import evaluate_commutation_fault


def test_blank_lcc_request_reserves_ratings_and_operation_modes(tmp_path):
    request = BlankLccRequest.from_dict({
        "project_name": "LCC_BLANK",
        "folder": str(tmp_path),
        "topology": "single_pole_12_pulse",
        "ratings": {"dc_voltage_kv": 500.0, "power_mw": 1000.0},
        "operation_modes": ["rectifier", "inverter"],
    })
    planned = plan_blank_lcc(request, workspace_root=tmp_path)
    assert planned["request"]["ratings"]["power_mw"] == 1000.0
    assert planned["fault_events"][0]["kind"] == "inverter_ac_disturbance"


def test_lcc_commutation_fault_requires_indication_bounded_response_and_recovery():
    result = evaluate_commutation_fault({
        "disturbance": True,
        "failure_indication": True,
        "dc_current_peak_ka": 2.0,
        "dc_current_limit_ka": 3.0,
        "recovered": True,
    })
    assert result["verdict"] == "PASS"
