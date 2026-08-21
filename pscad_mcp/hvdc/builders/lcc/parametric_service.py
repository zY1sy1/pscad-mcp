"""Public lifecycle composition for parameterized LCC models."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from ....core.backend.base import BackendError
from .derivation import derive_lcc_parameters
from .modes import derive_mode_copies, validate_lcc_schedule
from .parametric_models import ParametricLccRequest
from .template_audit import audit_lcc_template


class ParametricLccBuilderService:
    def __init__(self, pscad_service: Any = None, *, workspace_root: str | Path | None = None, catalog: Any = None) -> None:
        self.pscad_service = pscad_service
        self.workspace_root = Path(workspace_root).expanduser().resolve() if workspace_root is not None else None
        self.catalog = catalog
        self._statuses: dict[str, dict[str, Any]] = {}

    def derive_parameters(self, request: ParametricLccRequest) -> dict[str, Any]:
        return derive_lcc_parameters(request, self.catalog).to_dict()

    def audit_template(self, template_path: str | Path) -> dict[str, Any]:
        return audit_lcc_template(template_path).to_dict()

    def plan_parametric_model(self, request: ParametricLccRequest) -> dict[str, Any]:
        report = derive_lcc_parameters(request, self.catalog)
        payload = {"request": request.to_dict(), "derived": report.to_dict()}
        plan_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {"plan_hash": plan_hash, "request": payload["request"], "derived": payload["derived"], "status": "planned"}

    async def build_parametric_model(self, request: ParametricLccRequest, *, expected_plan_hash: str, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise BackendError("CONFIRMATION_REQUIRED", "confirm=true is required.", "hvdc", "build_parametric_lcc_model")
        plan = self.plan_parametric_model(request)
        if expected_plan_hash != plan["plan_hash"]:
            raise BackendError("LCC_PLAN_STALE", "The supplied plan hash is stale.", "hvdc", "build_parametric_lcc_model", {"expected_plan_hash": expected_plan_hash, "observed_plan_hash": plan["plan_hash"]})
        build_id = hashlib.sha256(plan["plan_hash"].encode()).hexdigest()[:24]
        status = {"build_id": build_id, "status": "validated", "plan_hash": plan["plan_hash"], "evidence": {"derived": plan["derived"]}}
        self._statuses[build_id] = status
        return status

    def get_status(self, build_id: str) -> dict[str, Any]:
        if build_id not in self._statuses:
            raise BackendError("NOT_FOUND", "Parametric LCC build was not found.", "hvdc", "get_parametric_lcc_build_status", {"build_id": build_id})
        return dict(self._statuses[build_id])

    def validate_operating_modes(self, events: Any) -> dict[str, Any]:
        schedule = validate_lcc_schedule(events)
        return {"valid": True, "events": [item.to_dict() for item in schedule]}


__all__ = ["ParametricLccBuilderService"]


def validate_parametric_acceptance_report(report: dict[str, Any]) -> dict[str, Any]:
    """Validate the bounded, persisted evidence contract for opt-in acceptance."""
    required = {"schema_version", "status", "workspace", "assets", "build", "modes"}
    missing = sorted(required - set(report))
    if missing:
        raise ValueError(f"acceptance report is missing fields: {missing}")
    if report.get("schema_version") != 1:
        raise ValueError("acceptance report schema_version must be 1")
    if report.get("status") not in {"PASS", "FAIL", "INCOMPLETE_ANALYSIS"}:
        raise ValueError("acceptance report status is invalid")
    workspace = report.get("workspace")
    if not isinstance(workspace, str) or not Path(workspace).is_absolute():
        raise ValueError("acceptance report workspace must be absolute")
    assets = report.get("assets")
    if not isinstance(assets, dict) or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in assets.values()):
        raise ValueError("acceptance report assets must contain SHA-256 hashes")
    modes = report.get("modes")
    if not isinstance(modes, list) or any(not isinstance(item, dict) or not isinstance(item.get("mode"), str) for item in modes):
        raise ValueError("acceptance report modes must be a list of mode reports")
    if report["status"] == "PASS":
        build = report.get("build")
        if not isinstance(build, dict) or build.get("state") != "published" or not isinstance(build.get("final_project_sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", build["final_project_sha256"]) is None:
            raise ValueError("PASS acceptance reports require final project evidence")
        if not modes or any(item.get("status") != "PASS" or item.get("compile") is not True or item.get("waveform") is not True for item in modes):
            raise ValueError("PASS acceptance reports require compile, waveform, and mode evidence")
    return {"valid": True, "status": report["status"], "mode_count": len(modes)}


__all__.append("validate_parametric_acceptance_report")
