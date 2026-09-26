import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "docs" / "acceptance-status.json"


def test_acceptance_status_manifest_separates_live_acceptance_scopes():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    scopes = {item["scope"]: item for item in payload["scopes"]}
    assert set(scopes) == {
        "legacy_core_462",
        "unified_topology_462",
        "fixed_cigre_lcc",
        "parametric_lcc",
        "hvdc_scenarios",
        "mmc_stage_a",
        "parametric_mmc",
        "generic_blueprint_builder",
        "native_mmc_half_bridge_640kv",
        "mmc_full_bridge_joint_462",
        "modern_core_5",
        "lcc_parametric_executor_462",
        "native_mmc_half_bridge_500kv_50hz",
        "native_mmc_half_bridge_640kv_q100",
        "native_average_arm_462",
    }
    assert scopes["legacy_core_462"]["licensed_status"] == "PASS"
    assert scopes["legacy_core_462"]["implementation_status"] == "MERGED"
    topology = scopes["unified_topology_462"]
    assert topology["licensed_status"] == "PASS"
    assert topology["pscad_version"] == "4.6.2"
    assert topology["rule_version"] == "generic+hvdc-v1"
    assert topology["evidence"]["commit"] == (
        "6ec6118f9fd0e979fb9a8a00202327dbf576e165"
    )
    assert len(topology["evidence"]["sha256"]) == 64
    assert len(topology["evidence"]["truth_manifest_sha256"]) == 64
    assert len(topology["evidence"]["truth_review_sha256"]) == 64
    assert scopes["fixed_cigre_lcc"]["licensed_status"] == "INCOMPLETE_ANALYSIS"
    assert scopes["parametric_lcc"]["licensed_status"] in {
        "NOT_RUN_ON_INTEGRATED_COMMIT",
        "PASS",
        "FAIL",
        "INCOMPLETE_ANALYSIS",
        "PARTIAL",
    }
    assert scopes["hvdc_scenarios"]["licensed_status"] == "PARTIAL"
    assert scopes["mmc_stage_a"]["implementation_status"] == "MERGED"
    assert scopes["mmc_stage_a"]["licensed_status"] == "INCOMPLETE_ANALYSIS"
    assert scopes["parametric_mmc"]["implementation_status"] == "MERGED"
    assert scopes["parametric_mmc"]["licensed_status"] in {
        "NOT_RUN_ON_INTEGRATED_COMMIT",
        "PASS",
        "FAIL",
        "INCOMPLETE_ANALYSIS",
        "PARTIAL",
    }
    assert scopes["generic_blueprint_builder"]["implementation_status"] == "MERGED"
    assert scopes["generic_blueprint_builder"]["licensed_status"] == "NOT_RUN_ON_INTEGRATED_COMMIT"


def test_latest_mmc_evidence_is_scoped_and_old_attempts_remain_historical():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    scopes = {item["scope"]: item for item in payload["scopes"]}
    native = scopes["native_mmc_half_bridge_640kv"]
    assert native["licensed_status"] == "PASS"
    assert native["evidence"]["sha256"] == (
        "2c3d7d158f5069e3358ad1427500cb2882844bfabcacb43a80a4732821db98c3"
    )
    assert native["intrinsic_dc_fault_blocking"] is False
    assert scopes["parametric_mmc"]["licensed_status"] == "PARTIAL"
    assert scopes["parametric_mmc"]["historical_attempts"][0]["attempt"]["failure_code"]
    fixed = scopes["fixed_cigre_lcc"]
    assert fixed["engineering_verdict"] == "PASS"
    assert fixed["golden_verdict"] == "INCOMPLETE_ANALYSIS"
    assert fixed["licensed_status"] == "INCOMPLETE_ANALYSIS"
    assert fixed["historical_attempts"][0]["attempt"]["failure_code"] == "LCC_DEFINITION_MISSING"
    assert scopes["modern_core_5"]["licensed_status"] == "NOT_RUN_ON_INTEGRATED_COMMIT"


def test_native_matrix_keeps_three_requests_and_component_only_scope_separate():
    scopes = {s["scope"]: s for s in json.loads(MANIFEST.read_text())["scopes"]}
    names = scopes["parametric_mmc"]["accepted_subscopes"]
    assert len(names) == 3
    cases = [scopes[name] for name in names]
    assert {(s["request"]["dc_voltage_kv"], s["request"]["frequency_hz"], s["request"]["reactive_power_mvar"]) for s in cases} == {
        (640.0, 60.0, 0.0), (640.0, 60.0, 100.0), (500.0, 50.0, -75.0),
    }
    assert {s["evidence"]["commit"] for s in cases} == {"9cfe1d41dd2113cb4e72e3a285b1da00397a2b6b"}
    assert all(s["licensed_status"] == "PASS" and s["intrinsic_dc_fault_blocking"] is False for s in cases)
    for name in ("native_average_arm_462", "lcc_parametric_executor_462"):
        assert {"pointer": "/model_accepted", "equals": False} in scopes[name]["evidence_checks"]


def test_live_pass_requires_durable_evidence_identity():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    for scope in payload["scopes"]:
        assert scope["implementation_status"] in {"MERGED", "INTEGRATION_BRANCH", "NOT_INTEGRATED"}
        assert scope["licensed_status"] in {
            "PASS",
            "PASS_HISTORICAL",
            "FAIL",
            "INCOMPLETE_ANALYSIS",
            "NOT_RUN_ON_INTEGRATED_COMMIT",
            "PARTIAL",
            "NOT_INTEGRATED",
        }
        if scope["licensed_status"] == "PASS":
            assert scope["evidence"]["report_path"]
            assert len(scope["evidence"]["sha256"]) == 64
            assert scope["evidence"]["commit"]


def test_readme_points_to_the_scoped_status_manifest():
    readme = (ROOT / "docs" / "zh-CN" / "README.md").read_text(encoding="utf-8")

    assert "acceptance-status.json" in readme
    assert "通用 Legacy 验收不等于固定 LCC、参数化 LCC 或 MMC 验收" in readme
