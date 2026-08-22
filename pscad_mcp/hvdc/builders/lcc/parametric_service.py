"""Public lifecycle composition for parameterized LCC models."""

from __future__ import annotations

import hashlib
import json
import secrets
from importlib import resources
from pathlib import Path
import re
from typing import Any

from ....core.backend.base import BackendError
from ....core.path_policy import PathPolicy, WorkspaceNotConfiguredError
from .derivation import derive_lcc_parameters
from .modes import derive_mode_copies, validate_lcc_schedule
from .parametric_models import ParametricLccRequest
from .template_audit import audit_lcc_template


_PROJECT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_PLAN_MAX_BYTES = 256 * 1024
_PATH_MAX_CHARS = 4096
_TOPOLOGY_BLUEPRINTS = {
    "bipolar": ("lcc_bipole_parametric_v1",),
    "monopolar": ("lcc_monopole_parametric_v1",),
}
_REQUIRED_TEMPLATE_ROLES = {
    "bipolar": {
        "rectifier_positive_pole",
        "rectifier_negative_pole",
        "inverter_positive_pole",
        "inverter_negative_pole",
        "earth_electrode",
    },
    "monopolar": {"rectifier_valve_group", "inverter_valve_group", "earth_electrode"},
}


def _error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _asset_json(relative: tuple[str, ...]) -> tuple[dict[str, Any], str]:
    try:
        payload = resources.files("pscad_mcp").joinpath("assets", "lcc", *relative).read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error(
            "LCC_ASSET_MISMATCH",
            "A packaged parametric LCC asset could not be read.",
            "plan_parametric_lcc_model",
            reason="asset_unreadable",
            error_type=type(error).__name__,
        ) from error
    if not isinstance(value, dict):
        raise _error(
            "LCC_ASSET_MISMATCH",
            "A packaged parametric LCC asset is not an object.",
            "plan_parametric_lcc_model",
            reason="asset_not_object",
        )
    return value, hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any, *, operation: str) -> bytes:
    try:
        payload = json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise _error(
            "LCC_PLAN_INVALID",
            "The parametric LCC plan contains non-JSON evidence.",
            operation,
            reason="plan_not_json_safe",
            error_type=type(error).__name__,
        ) from error
    if len(payload) > _PLAN_MAX_BYTES:
        raise _error(
            "LCC_PLAN_INVALID",
            "The parametric LCC plan exceeds the evidence size limit.",
            operation,
            reason="plan_too_large",
            actual_bytes=len(payload),
            max_bytes=_PLAN_MAX_BYTES,
        )
    return payload


def _load_parametric_asset_snapshot(
    topology: str, catalog_override: Any = None
) -> dict[str, Any]:
    blueprint_parts = _TOPOLOGY_BLUEPRINTS.get(topology)
    if blueprint_parts is None:
        raise _error(
            "LCC_TEMPLATE_TOPOLOGY_MISMATCH",
            "The requested LCC topology is not supported.",
            "plan_parametric_lcc_model",
            reason="unsupported_topology",
        )
    blueprint_name = blueprint_parts[0]
    blueprint, blueprint_hash = _asset_json((blueprint_name, "blueprint.json"))
    provenance, provenance_hash = _asset_json(
        ("lcc_bipole_parametric_v1", "provenance-parametric-v1.json")
    )
    if catalog_override is None:
        catalog, catalog_hash = _asset_json(("lcc_parametric_catalog_v1.json",))
        catalog_source = "packaged"
    else:
        if not isinstance(catalog_override, dict):
            raise _error(
                "LCC_ASSET_MISMATCH",
                "The injected parametric catalog must be an object.",
                "plan_parametric_lcc_model",
                reason="catalog_not_object",
            )
        catalog = catalog_override
        catalog_hash = hashlib.sha256(
            _canonical_bytes(catalog, operation="plan_parametric_lcc_model")
        ).hexdigest()
        catalog_source = "injected"
    if (
        catalog.get("identity") != "lcc_parametric_catalog_v1"
        or provenance.get("identity") != "lcc_parametric_provenance_v1"
        or blueprint.get("name") != blueprint_name
    ):
        raise _error(
            "LCC_ASSET_MISMATCH",
            "Parametric LCC asset identity validation failed.",
            "plan_parametric_lcc_model",
            reason="asset_identity_mismatch",
        )
    return {
        "catalog": catalog,
        "blueprint": blueprint,
        "provenance": provenance,
        "evidence": {
            "catalog": {
                "identity": catalog["identity"],
                "sha256": catalog_hash,
                "source": catalog_source,
            },
            "provenance": {
                "identity": provenance["identity"],
                "sha256": provenance_hash,
            },
            "blueprint": {"identity": blueprint_name, "sha256": blueprint_hash},
        },
    }


class ParametricLccBuilderService:
    def __init__(self, pscad_service: Any = None, *, workspace_root: str | Path | None = None, catalog: Any = None) -> None:
        self.pscad_service = pscad_service
        self.workspace_root = Path(workspace_root).expanduser().resolve() if workspace_root is not None else None
        self.catalog = catalog
        self._statuses: dict[str, dict[str, Any]] = {}

    def derive_parameters(self, request: ParametricLccRequest) -> dict[str, Any]:
        return derive_lcc_parameters(request, self.catalog).to_dict()

    def audit_template(self, template_path: str | Path) -> dict[str, Any]:
        return audit_lcc_template(template_path, self.catalog).to_dict()

    @staticmethod
    def _required_inputs(
        template_path: str | Path | None,
        project_name: str | None,
        folder: str | Path | None,
        *,
        operation: str,
    ) -> tuple[str | Path, str, str | Path]:
        values = {
            "template_path": template_path,
            "project_name": project_name,
            "folder": folder,
        }
        missing = [name for name, value in values.items() if value is None]
        if missing:
            raise _error(
                "LCC_PLAN_INPUT_REQUIRED",
                "Template and destination inputs are required for parametric LCC planning.",
                operation,
                missing=missing,
            )
        return template_path, project_name, folder  # type: ignore[return-value]

    def _resolve_template(self, template_path: str | Path, *, operation: str) -> Path:
        if not isinstance(template_path, (str, Path)):
            raise _error(
                "LCC_TEMPLATE_INCOMPATIBLE",
                "template_path must be an absolute PSCX path.",
                operation,
                reason="template_path_not_absolute",
            )
        raw = Path(template_path).expanduser()
        if not raw.is_absolute():
            raise _error(
                "LCC_TEMPLATE_INCOMPATIBLE",
                "template_path must be absolute.",
                operation,
                reason="template_path_not_absolute",
            )
        if len(str(raw)) > _PATH_MAX_CHARS:
            raise _error(
                "LCC_TEMPLATE_INCOMPATIBLE",
                "template_path exceeds the path length limit.",
                operation,
                reason="template_path_too_long",
            )
        if raw.suffix.casefold() != ".pscx":
            raise _error(
                "LCC_TEMPLATE_INCOMPATIBLE",
                "template_path must identify a PSCX project.",
                operation,
                reason="template_suffix_invalid",
            )
        try:
            if raw.is_symlink() or not raw.is_file():
                reason = "template_not_regular" if raw.exists() else "template_not_found"
                raise _error(
                    "LCC_TEMPLATE_INCOMPATIBLE",
                    "template_path must identify an existing regular PSCX file.",
                    operation,
                    reason=reason,
                )
            return raw.resolve()
        except BackendError:
            raise
        except OSError as error:
            raise _error(
                "LCC_TEMPLATE_INCOMPATIBLE",
                "template_path could not be inspected.",
                operation,
                reason="template_unreadable",
                error_type=type(error).__name__,
            ) from error

    def _resolve_targets(
        self,
        project_name: str,
        folder: str | Path,
        *,
        operation: str,
        enforce_target_absent: bool,
    ) -> dict[str, str]:
        if not isinstance(project_name, str) or _PROJECT_NAME.fullmatch(project_name) is None:
            raise _error(
                "LCC_LAYOUT_INVALID",
                "project_name is not a safe PSCAD project identity.",
                operation,
                field="project_name",
                reason="unsafe_project_name",
            )
        if self.workspace_root is None:
            raise _error(
                "LCC_LAYOUT_INVALID",
                "A configured workspace is required for parametric LCC planning.",
                operation,
                reason="workspace_not_configured",
            )
        if not isinstance(folder, (str, Path)) or not Path(folder).expanduser().is_absolute():
            raise _error(
                "LCC_LAYOUT_INVALID",
                "folder must be an absolute path inside the configured workspace.",
                operation,
                reason="folder_not_absolute",
            )
        if len(str(folder)) > _PATH_MAX_CHARS:
            raise _error(
                "LCC_LAYOUT_INVALID",
                "folder exceeds the path length limit.",
                operation,
                reason="folder_path_too_long",
            )
        policy = PathPolicy(workspace_root=str(self.workspace_root))
        try:
            folder_path = policy.resolve(str(folder))
            if folder_path.exists() and not folder_path.is_dir():
                raise ValueError("folder is not a directory")
            target = policy.resolve_child(
                str(folder_path), f"{project_name}.pscx", suffixes={".pscx"}
            )
            staging_root = policy.resolve(
                str(self.workspace_root / ".pscad-mcp" / "lcc-builds")
            )
            staging = policy.resolve_child(
                str(staging_root), f"{project_name}.staging.pscx", suffixes={".pscx"}
            )
        except WorkspaceNotConfiguredError as error:
            raise _error(
                "LCC_LAYOUT_INVALID",
                "A configured workspace is required for parametric LCC planning.",
                operation,
                reason="workspace_not_configured",
            ) from error
        except (ValueError, OSError) as error:
            reason = (
                "folder_outside_workspace"
                if "outside the configured PSCAD workspace" in str(error)
                else "destination_path_invalid"
            )
            raise _error(
                "LCC_LAYOUT_INVALID",
                "The destination path is invalid for the configured workspace.",
                operation,
                reason=reason,
            ) from error
        if enforce_target_absent and (target.exists() or target.is_symlink()):
            raise _error(
                "LCC_BUILD_CONFLICT",
                "The planned final destination already exists.",
                operation,
                reason="final_target_exists",
            )
        return {
            "name": project_name,
            "folder": str(folder_path),
            "target_path": str(target),
            "staging_path": str(staging),
        }

    @staticmethod
    def _validate_topology(request: ParametricLccRequest, audit: dict[str, Any], *, operation: str) -> None:
        if not audit.get("compatible"):
            missing = audit.get("missing_contracts", [])
            raise _error(
                "LCC_TEMPLATE_INCOMPATIBLE",
                "The audited PSCX template does not satisfy the catalog contracts.",
                operation,
                reason="audit_not_compatible",
                missing_contracts=list(missing)[:32] if isinstance(missing, list) else [],
            )
        roles = audit.get("roles")
        required = _REQUIRED_TEMPLATE_ROLES.get(request.topology, set())
        if not isinstance(roles, dict) or not required.issubset(roles):
            raise _error(
                "LCC_TEMPLATE_TOPOLOGY_MISMATCH",
                "The audited template roles do not match the requested topology.",
                operation,
                topology=request.topology,
                reason="required_roles_missing",
            )

    def _compose_plan(
        self,
        request: ParametricLccRequest,
        *,
        template_path: str | Path | None,
        project_name: str | None,
        folder: str | Path | None,
        operation: str,
        enforce_target_absent: bool,
    ) -> dict[str, Any]:
        template_path, project_name, folder = self._required_inputs(
            template_path, project_name, folder, operation=operation
        )
        source = self._resolve_template(template_path, operation=operation)
        project = self._resolve_targets(
            project_name,
            folder,
            operation=operation,
            enforce_target_absent=enforce_target_absent,
        )
        assets = _load_parametric_asset_snapshot(request.topology, self.catalog)
        derived = derive_lcc_parameters(request, assets["catalog"]).to_dict()
        audited = audit_lcc_template(source, assets["catalog"]).to_dict()
        self._validate_topology(request, audited, operation=operation)
        payload = {
            "schema_version": 1,
            "request": request.to_dict(),
            "derived": derived,
            "template": {
                "path": str(source),
                "fingerprint": audited["fingerprint"],
                "roles": audited["roles"],
            },
            "assets": assets["evidence"],
            "project": project,
        }
        encoded = _canonical_bytes(payload, operation=operation)
        return {
            **payload,
            "plan_hash": hashlib.sha256(encoded).hexdigest(),
            "status": "planned",
        }

    def plan_parametric_model(
        self,
        request: ParametricLccRequest,
        *,
        template_path: str | Path | None = None,
        project_name: str | None = None,
        folder: str | Path | None = None,
    ) -> dict[str, Any]:
        return self._compose_plan(
            request,
            template_path=template_path,
            project_name=project_name,
            folder=folder,
            operation="plan_parametric_lcc_model",
            enforce_target_absent=True,
        )

    async def build_parametric_model(
        self,
        request: ParametricLccRequest,
        *,
        template_path: str | Path | None = None,
        project_name: str | None = None,
        folder: str | Path | None = None,
        expected_plan_hash: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise BackendError("CONFIRMATION_REQUIRED", "confirm=true is required.", "hvdc", "build_parametric_lcc_model")
        plan = self._compose_plan(
            request,
            template_path=template_path,
            project_name=project_name,
            folder=folder,
            operation="build_parametric_lcc_model",
            enforce_target_absent=False,
        )
        if not isinstance(expected_plan_hash, str) or not secrets.compare_digest(
            expected_plan_hash, plan["plan_hash"]
        ):
            raise _error(
                "LCC_PLAN_STALE",
                "The supplied plan hash is stale.",
                "build_parametric_lcc_model",
                reason="deterministic_plan_changed",
                observed_plan_hash=plan["plan_hash"],
            )
        target = Path(plan["project"]["target_path"])
        if target.exists() or target.is_symlink():
            raise _error(
                "LCC_BUILD_CONFLICT",
                "The planned final destination already exists.",
                "build_parametric_lcc_model",
                reason="final_target_exists",
            )
        missing = []
        if self.pscad_service is None:
            missing.append("pscad_service")
        if self.workspace_root is None:
            missing.append("workspace_root")
        if missing:
            raise BackendError(
                "LCC_BUILD_UNAVAILABLE",
                "The real PSCAD parametric LCC build lifecycle is unavailable.",
                "hvdc",
                "build_parametric_lcc_model",
                {"reason": "lifecycle_configuration_missing", "missing": missing},
            )
        raise BackendError(
            "LCC_BUILD_UNAVAILABLE",
            "The real PSCAD parametric LCC build lifecycle is not implemented.",
            "hvdc",
            "build_parametric_lcc_model",
            {"reason": "real_lifecycle_not_implemented", "missing": []},
        )

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
