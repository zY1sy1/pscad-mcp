from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_mmc_real_acceptance import acceptance_config, evidence_directory, write_acceptance_report


def test_mmc_acceptance_config_requires_legacy_462_and_absolute_workspace(tmp_path):
    values = {
        "PSCAD_MCP_MMC_ACCEPTANCE": "1",
        "PSCAD_MCP_BACKEND": "legacy",
        "PSCAD_MCP_VERSION": "4.6.2",
        "PSCAD_MCP_WORKSPACE": str(tmp_path),
    }
    config = acceptance_config(values)
    assert config["enabled"] is True
    assert config["backend"] == "legacy"
    assert config["version"] == "4.6.2"
    assert Path(config["workspace"]).is_absolute()

    with pytest.raises(ValueError, match="legacy"):
        acceptance_config({**values, "PSCAD_MCP_BACKEND": "modern"})
    with pytest.raises(ValueError, match="4.6.2"):
        acceptance_config({**values, "PSCAD_MCP_VERSION": "5.0"})
    with pytest.raises(ValueError, match="absolute"):
        acceptance_config({**values, "PSCAD_MCP_WORKSPACE": "relative-workspace"})


def test_mmc_acceptance_evidence_directory_is_timestamped_and_disjoint(tmp_path):
    directory = evidence_directory(tmp_path)
    assert directory.parent == tmp_path
    assert directory.name.startswith("mmc-acceptance-")
    assert directory != tmp_path


def _pass_payload() -> dict[str, object]:
    hashes = {"blueprint.json": "a" * 64}
    project_hash = "b" * 64
    return {
        "schema_version": 1,
        "status": "PASS",
        "config": {"backend": "legacy", "version": "4.6.2", "workspace": "D:/acceptance"},
        "build": {
            "state": "published",
            "asset_hashes": hashes,
            "history": [{"state": "published", "final_project_name": "MMC_STAGE_A", "final_project_sha256": project_hash, "final_compile_smoke": True}],
        },
        "validation": {
            "valid": True,
            "accepted": True,
            "project_file": "D:/acceptance/MMC_STAGE_A.pscx",
            "project_sha256": project_hash,
            "output_file": "D:/acceptance/MMC_STAGE_A.out",
            "independent_validation": {"performed": True},
            "observed": {"arm_count": 12},
            "acceptance": {
                "status": "evaluated",
                "verdict": "PASS",
                "checks": [{"name": name, "passed": True} for name in ("precharge_ready", "forward_steady", "power_reversal", "reverse_steady")],
            },
        },
        "assets": hashes,
        "source_hashes": hashes,
        "workspace_before": {},
        "workspace_after": {},
    }


def test_mmc_acceptance_report_rejects_incomplete_pass(tmp_path):
    payload = _pass_payload()
    del payload["validation"]["independent_validation"]
    with pytest.raises(ValueError, match="complete independent MMC evidence"):
        write_acceptance_report(tmp_path / "report.json", payload)


def test_mmc_acceptance_report_is_bounded_json_and_requires_all_windows(tmp_path):
    path = write_acceptance_report(tmp_path / "report.json", _pass_payload())
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["status"] == "PASS"
    assert loaded["validation"]["observed"]["arm_count"] == 12

    payload = _pass_payload()
    payload["validation"]["acceptance"]["checks"] = [{"name": "forward_steady", "passed": True}]
    with pytest.raises(ValueError, match="complete independent MMC evidence"):
        write_acceptance_report(tmp_path / "missing-window.json", payload)
