"""Opt-in licensed PSCAD 4.6.2 compile gate for Master bindings."""

from __future__ import annotations

import json
import os
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.master_bindings import audit_master_bindings
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import PscadService
from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set, sha256_file

ACCEPTANCE_ENABLED = os.getenv("PSCAD_MCP_MASTER_BINDING_ACCEPTANCE") == "1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def validate_master_binding_compile_report(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise TypeError("Master binding acceptance report must be an object")
    required = {
        "schema_version",
        "status",
        "pscad_version",
        "master_path",
        "master_before_sha256",
        "master_after_sha256",
        "registry_sha256",
        "bindings",
        "compile",
        "project",
    }
    if set(payload) != required:
        raise ValueError("Master binding acceptance report fields are incomplete")
    if payload["schema_version"] != 1:
        raise ValueError("Master binding acceptance schema version must be 1")
    if payload["status"] not in {"PASS", "FAIL", "INCOMPLETE_ANALYSIS"}:
        raise ValueError("Master binding acceptance status is invalid")
    for field in (
        "master_before_sha256",
        "master_after_sha256",
        "registry_sha256",
    ):
        if not isinstance(payload[field], str) or _SHA256.fullmatch(payload[field]) is None:
            raise ValueError(f"{field} must be a SHA-256 value")
    if payload["master_before_sha256"] != payload["master_after_sha256"]:
        raise ValueError("Master source changed during acceptance")
    bindings = payload["bindings"]
    if not isinstance(bindings, list) or len(bindings) != 8:
        raise ValueError("Master binding acceptance requires exactly eight bindings")
    logical_names = {
        item.get("logical_name")
        for item in bindings
        if isinstance(item, dict)
    }
    if len(logical_names) != 8 or any(
        not isinstance(item, dict)
        or item.get("verification_state") != "verified"
        or not isinstance(item.get("observed_instances"), list)
        or not item["observed_instances"]
        for item in bindings
    ):
        raise ValueError("Every Master binding requires physical read-back evidence")
    compile_evidence = payload["compile"]
    project = payload["project"]
    if payload["status"] == "PASS" and (
        not isinstance(compile_evidence, dict)
        or compile_evidence.get("success") is not True
        or not isinstance(project, dict)
        or not isinstance(project.get("sha256"), str)
        or _SHA256.fullmatch(project["sha256"]) is None
    ):
        raise ValueError("PASS requires compile and project hash evidence")
    return payload


def _configuration() -> tuple[Path, Path]:
    workspace_value = os.getenv("PSCAD_MCP_WORKSPACE")
    if not workspace_value:
        raise ValueError("PSCAD_MCP_WORKSPACE is required")
    workspace = Path(workspace_value).expanduser().resolve()
    master = Path(
        os.getenv(
            "PSCAD_MCP_MASTER_LIBRARY",
            r"C:\Program Files (x86)\PSCAD46\master.pslx",
        )
    ).expanduser().resolve()
    if not master.is_file() or master.is_symlink():
        raise ValueError("PSCAD_MCP_MASTER_LIBRARY must be a regular file")
    return workspace, master


@unittest.skipUnless(
    ACCEPTANCE_ENABLED,
    "Set PSCAD_MCP_MASTER_BINDING_ACCEPTANCE=1 for licensed PSCAD acceptance.",
)
class TestMasterBindingRealAcceptance(unittest.IsolatedAsyncioTestCase):
    async def test_all_eight_bindings_instantiate_read_back_and_compile(self) -> None:
        workspace, master_path = _configuration()
        evidence_root = workspace / (
            "master-binding-acceptance-"
            + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        )
        evidence_root.mkdir(parents=True, exist_ok=False)
        report_path = evidence_root / "master-binding-acceptance-report.json"
        master_before = sha256_file(master_path)
        assets = load_packaged_asset_set()
        assert assets.master_bindings is not None
        audited = audit_master_bindings(master_path, assets.master_bindings)
        backend = LegacyBackend(
            robust_executor,
            version="4.6.2",
            x64=True,
            definition_paths={"master": master_path},
        )
        service = PscadService(
            lambda: backend,
            path_policy=PathPolicy(workspace_root=str(workspace)),
        )
        report: dict[str, object] = {
            "schema_version": 1,
            "status": "INCOMPLETE_ANALYSIS",
            "pscad_version": "4.6.2",
            "master_path": str(master_path),
            "master_before_sha256": master_before,
            "master_after_sha256": master_before,
            "registry_sha256": assets.master_bindings.sha256,
            "bindings": [],
            "compile": {"success": False},
            "project": {},
        }
        failure: Exception | None = None
        try:
            await service.attach_local()
            inventory = await service.get_lcc_inventory(
                assets.catalog,
                assets.master_bindings.to_dict(),
            )
            self.assertEqual(inventory["master_sha256"], master_before)
            project_record = await service.create_project(
                "case",
                "MasterBindingAcceptance.pscx",
                str(evidence_root),
                confirm=True,
            )
            project_name = project_record["name"]
            project_path = Path(project_record["filename"])
            parameters = {
                "master:three_phase_source": {
                    "Amplitude_kV": 230.0,
                    "Frequency_Hz": 50.0,
                    "Phase_deg": 0.0,
                },
                "master:converter_transformer": {
                    "Ratio": 1.0,
                    "Connection": "Y-delta",
                    "PhaseShift_deg": 30.0,
                },
                "master:ac_filter_branch": {
                    "Branch_MVAR": 50.0,
                    "Tuning_Hz": 300.0,
                },
                "master:smoothing_reactor": {"Inductance_mH": 100.0},
                "master:dc_line_section": {
                    "Length_km": 300.0,
                    "Resistance_ohm": 10.0,
                },
                "master:ac_meter": {},
                "master:dc_meter": {},
                "master:ground": {},
            }
            locations = {
                "master:three_phase_source": (180, 180),
                "master:converter_transformer": (540, 180),
                "master:ac_filter_branch": (900, 180),
                "master:smoothing_reactor": (1260, 180),
                "master:dc_line_section": (1620, 180),
                "master:ac_meter": (180, 540),
                "master:dc_meter": (540, 540),
                "master:ground": (900, 540),
            }
            binding_reports: list[dict[str, object]] = []
            for logical_name, logical_parameters in parameters.items():
                resolved = audited.resolve_component(
                    logical_name,
                    logical_parameters,
                )
                created = await service.add_canvas_component(
                    project_name,
                    "master",
                    logical_name.split(":", 1)[1],
                    locations[logical_name][0],
                    locations[logical_name][1],
                    0,
                    logical_parameters,
                    binding_evidence=resolved.to_evidence(),
                )
                component_id = int(created["id"])
                observed = await backend.get_master_binding_evidence(
                    project_name,
                    component_id,
                )
                observed_ports = await service.get_component_ports(
                    project_name,
                    component_id,
                )
                self.assertEqual(
                    set(observed_ports),
                    set(resolved.selected_ports),
                )
                binding_reports.append(observed)
            report["bindings"] = binding_reports
            await service.save_project(project_name, confirm=True)
            compile_result = await service.build_project(project_name)
            await service.save_project(project_name, confirm=True)
            report["compile"] = {
                "success": True,
                "result": compile_result,
            }
            report["project"] = {
                "name": project_name,
                "path": str(project_path),
                "sha256": sha256_file(project_path),
            }
            report["status"] = "PASS"
        except Exception as error:  # noqa: BLE001 - persist vendor failure evidence
            failure = error
            report["status"] = "FAIL"
            report["compile"] = {
                "success": False,
                "error_type": type(error).__name__,
                "error": str(error),
            }
        finally:
            report["master_after_sha256"] = sha256_file(master_path)
            try:
                await service.quit_pscad(confirm=True)
            except Exception as quit_error:  # noqa: BLE001 - report cleanup failure
                if failure is None:
                    failure = quit_error
                    report["status"] = "FAIL"
                    report["compile"] = {
                        "success": False,
                        "error_type": type(quit_error).__name__,
                        "error": str(quit_error),
                    }
            report_path.write_text(
                json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
        if failure is not None:
            raise failure
        validate_master_binding_compile_report(report)


def test_master_binding_compile_report_fails_closed() -> None:
    payload = {
        "schema_version": 1,
        "status": "PASS",
        "pscad_version": "4.6.2",
        "master_path": "C:/PSCAD46/master.pslx",
        "master_before_sha256": "a" * 64,
        "master_after_sha256": "b" * 64,
        "registry_sha256": "c" * 64,
        "bindings": [],
        "compile": {"success": True},
        "project": {"sha256": "d" * 64},
    }

    with unittest.TestCase().assertRaisesRegex(ValueError, "Master source"):
        validate_master_binding_compile_report(payload)


__all__ = [
    "ACCEPTANCE_ENABLED",
    "validate_master_binding_compile_report",
]
