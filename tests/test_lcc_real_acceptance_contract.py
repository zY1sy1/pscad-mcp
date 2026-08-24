from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from test_lcc_real_acceptance import acceptance_config, evidence_directory, write_acceptance_report


def test_acceptance_config_requires_absolute_legacy_462_workspace():
    with pytest.raises(ValueError):
        acceptance_config({"PSCAD_MCP_BACKEND": "modern", "PSCAD_MCP_VERSION": "4.6.2", "PSCAD_MCP_WORKSPACE": "C:/workspace"})
    with pytest.raises(ValueError):
        acceptance_config({"PSCAD_MCP_BACKEND": "legacy", "PSCAD_MCP_VERSION": "5.0", "PSCAD_MCP_WORKSPACE": "C:/workspace"})

    config = acceptance_config({"PSCAD_MCP_BACKEND": "legacy", "PSCAD_MCP_VERSION": "4.6.2", "PSCAD_MCP_WORKSPACE": "C:/workspace", "PSCAD_MCP_X64": "true"})
    assert config["workspace"] == Path("C:/workspace").resolve()
    assert config["backend"] == "legacy"


def test_acceptance_config_keeps_parametric_template_explicit_and_absolute():
    config = acceptance_config({
        "PSCAD_MCP_BACKEND": "legacy",
        "PSCAD_MCP_VERSION": "4.6.2",
        "PSCAD_MCP_WORKSPACE": "C:/workspace",
        "PSCAD_MCP_LCC_TEMPLATE": "C:/templates/HVDC_Bipolar_1000MW_500kV.pscx",
    })
    assert config["template"] == Path("C:/templates/HVDC_Bipolar_1000MW_500kV.pscx").resolve()


def test_evidence_directory_is_timestamped_and_owned(tmp_path):
    directory = evidence_directory(tmp_path, now=datetime(2026, 8, 19, 12, 34, 56, 123456))

    assert directory.parent == tmp_path
    assert directory.name == "lcc-acceptance-20260819-123456-123456"
    assert directory.is_dir()


def test_report_schema_is_written(tmp_path):
    report = {
        "schema_version": 1,
        "status": "INCOMPLETE_ANALYSIS",
        "config": {},
        "build": {},
        "validation": {},
        "assets": {},
        "workspace_before": {},
        "workspace_after": {},
    }
    path = write_acceptance_report(tmp_path / "lcc-acceptance-report.json", report)

    assert path.is_file()
    assert '"schema_version": 1' in path.read_text(encoding="utf-8")


def test_report_schema_rejects_invalid_version_and_pass_without_evidence(tmp_path):
    invalid_version = {
        "schema_version": 2,
        "status": "INCOMPLETE_ANALYSIS",
        "config": {},
        "build": {},
        "validation": {},
        "assets": {},
        "workspace_before": {},
        "workspace_after": {},
    }
    with pytest.raises(ValueError):
        write_acceptance_report(tmp_path / "invalid-version.json", invalid_version)

    invalid_pass = dict(invalid_version, schema_version=1, status="PASS")
    with pytest.raises(ValueError):
        write_acceptance_report(tmp_path / "invalid-pass.json", invalid_pass)


def test_report_schema_rejects_pass_without_asset_and_final_compile_evidence(tmp_path):
    payload = {
        "schema_version": 1,
        "status": "PASS",
        "config": {},
        "build": {
            "state": "published",
            "history": [{"state": "published", "final_project_name": "final", "final_compile_smoke": True}],
        },
        "validation": {
            "valid": True,
            "accepted": True,
            "project_file": "C:/workspace/final.pscx",
            "output_file": "C:/workspace/final.out",
            "acceptance": {"status": "evaluated", "verdict": "PASS"},
        },
        "assets": {},
        "workspace_before": {},
        "workspace_after": {},
    }

    with pytest.raises(ValueError):
        write_acceptance_report(tmp_path / "missing-evidence.json", payload)


def test_report_schema_rejects_pass_without_final_project_hash(tmp_path):
    payload = {
        "schema_version": 1,
        "status": "PASS",
        "config": {},
        "build": {
            "state": "published",
            "history": [{"state": "published", "final_project_name": "final", "final_compile_smoke": True}],
        },
        "validation": {
            "valid": True,
            "accepted": True,
            "project_file": "C:/workspace/final.pscx",
            "output_file": "C:/workspace/final.out",
            "acceptance": {"status": "evaluated", "verdict": "PASS"},
        },
        "assets": {"blueprint.json": "a" * 64},
        "workspace_before": {},
        "workspace_after": {},
    }

    with pytest.raises(ValueError):
        write_acceptance_report(tmp_path / "missing-final-hash.json", payload)


def test_report_schema_rejects_pass_when_build_asset_hashes_do_not_match(tmp_path):
    payload = {
        "schema_version": 1,
        "status": "PASS",
        "config": {},
        "build": {
            "state": "published",
            "asset_hashes": {"blueprint.json": "b" * 64},
            "history": [
                {
                    "state": "published",
                    "final_project_name": "final",
                    "final_compile_smoke": True,
                    "final_project_sha256": "c" * 64,
                }
            ],
        },
        "validation": {
            "valid": True,
            "accepted": True,
            "project_file": "C:/workspace/final.pscx",
            "output_file": "C:/workspace/final.out",
            "acceptance": {"status": "evaluated", "verdict": "PASS"},
        },
        "assets": {"blueprint.json": "a" * 64},
        "workspace_before": {},
        "workspace_after": {},
    }

    with pytest.raises(ValueError, match="asset hashes"):
        write_acceptance_report(tmp_path / "mismatched-assets.json", payload)


def test_report_schema_rejects_pass_when_validation_hash_differs_from_publication(tmp_path):
    payload = {
        "schema_version": 1,
        "status": "PASS",
        "config": {},
        "build": {
            "state": "published",
            "asset_hashes": {"blueprint.json": "a" * 64},
            "history": [
                {
                    "state": "published",
                    "final_project_name": "final",
                    "final_compile_smoke": True,
                    "final_project_sha256": "b" * 64,
                }
            ],
        },
        "validation": {
            "valid": True,
            "accepted": True,
            "project_file": "C:/workspace/final.pscx",
            "project_sha256": "c" * 64,
            "output_file": "C:/workspace/final.out",
            "acceptance": {"status": "evaluated", "verdict": "PASS"},
        },
        "assets": {"blueprint.json": "a" * 64},
        "workspace_before": {},
        "workspace_after": {},
    }

    with pytest.raises(ValueError, match="final project hash"):
        write_acceptance_report(tmp_path / "mismatched-project.json", payload)
