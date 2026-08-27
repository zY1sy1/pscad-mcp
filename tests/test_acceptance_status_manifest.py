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
    }
    assert scopes["legacy_core_462"]["licensed_status"] == "PASS_HISTORICAL"
    topology = scopes["unified_topology_462"]
    assert topology["licensed_status"] == "PASS"
    assert topology["pscad_version"] == "4.6.2"
    assert topology["evidence"]["commit"] == (
        "a78d5e0e9bafe06221d32fe1153b66593fb61a7a"
    )
    assert len(topology["evidence"]["sha256"]) == 64
    assert scopes["fixed_cigre_lcc"]["licensed_status"] == "INCOMPLETE_ANALYSIS"
    assert scopes["parametric_lcc"]["licensed_status"] in {
        "NOT_RUN_ON_INTEGRATED_COMMIT",
        "PASS",
        "FAIL",
        "INCOMPLETE_ANALYSIS",
    }
    assert scopes["hvdc_scenarios"]["licensed_status"] == "PARTIAL"
    assert scopes["mmc_stage_a"]["licensed_status"] == "NOT_INTEGRATED"


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
