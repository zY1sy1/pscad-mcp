"""Opt-in licensed PSCAD 4.6.2 acceptance for the fixed MMC Stage A builder."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import PscadService
from pscad_mcp.hvdc.builders.mmc.assets import load_packaged_asset_set
from pscad_mcp.hvdc.builders.mmc.service import MmcBuilderService


ACCEPTANCE_ENABLED = os.getenv("PSCAD_MCP_MMC_ACCEPTANCE") == "1"
_WINDOWS = {"precharge_ready", "forward_steady", "power_reversal", "reverse_steady"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): _sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def acceptance_config(environ: dict[str, str] | None = None) -> dict[str, object]:
    values = os.environ if environ is None else environ
    workspace_value = values.get("PSCAD_MCP_WORKSPACE")
    if not workspace_value:
        raise ValueError("PSCAD_MCP_WORKSPACE is required")
    workspace_candidate = Path(workspace_value).expanduser()
    if not workspace_candidate.is_absolute():
        raise ValueError("PSCAD_MCP_WORKSPACE must be absolute")
    workspace = workspace_candidate.resolve()
    backend = values.get("PSCAD_MCP_BACKEND", "legacy")
    version = values.get("PSCAD_MCP_VERSION", "4.6.2")
    if backend != "legacy":
        raise ValueError("MMC acceptance requires the legacy backend")
    if version != "4.6.2":
        raise ValueError("MMC acceptance requires PSCAD 4.6.2")
    x64 = values.get("PSCAD_MCP_X64", "true").casefold() in {"1", "true", "yes", "on"}
    return {
        "enabled": values.get("PSCAD_MCP_MMC_ACCEPTANCE") == "1",
        "backend": backend,
        "version": version,
        "x64": x64,
        "workspace": workspace,
    }


def evidence_directory(workspace: Path, *, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S-%f")
    directory = workspace / f"mmc-acceptance-{stamp}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def _json_error(error: BaseException) -> dict[str, object]:
    if isinstance(error, BackendError):
        return error.to_dict()
    return {"code": "MMC_ACCEPTANCE_TEST_FAILED", "type": type(error).__name__, "message": str(error)}


def write_acceptance_report(path: Path, payload: dict[str, object]) -> Path:
    required = {
        "schema_version",
        "status",
        "config",
        "build",
        "validation",
        "assets",
        "source_hashes",
        "workspace_before",
        "workspace_after",
    }
    missing = required - set(payload)
    if missing:
        raise ValueError(f"acceptance report is missing fields: {sorted(missing)}")
    if payload.get("schema_version") != 1:
        raise ValueError("acceptance report schema_version must be 1")
    status = payload.get("status")
    if status not in {"PASS", "FAIL", "INCOMPLETE_ANALYSIS"}:
        raise ValueError("acceptance report status is invalid")
    for field in ("config", "build", "validation", "assets", "source_hashes", "workspace_before", "workspace_after"):
        if not isinstance(payload.get(field), dict):
            raise ValueError(f"acceptance report field '{field}' must be an object")

    if status == "PASS":
        build = payload["build"]
        validation = payload["validation"]
        assets = payload["assets"]
        source_hashes = payload["source_hashes"]
        history = build.get("history") if isinstance(build, dict) else None
        publication = next(
            (entry for entry in history if isinstance(entry, dict) and entry.get("state") == "published"),
            None,
        ) if isinstance(history, list) else None
        acceptance = validation.get("acceptance") if isinstance(validation, dict) else None
        checks = acceptance.get("checks") if isinstance(acceptance, dict) else None
        check_names = {item.get("name") for item in checks if isinstance(item, dict)} if isinstance(checks, list) else set()
        project_hash = validation.get("project_sha256") if isinstance(validation, dict) else None
        publication_hash = publication.get("final_project_sha256") if isinstance(publication, dict) else None
        hash_maps_valid = all(
            isinstance(mapping, dict)
            and mapping
            and all(isinstance(key, str) and isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value) for key, value in mapping.items())
            for mapping in (assets, source_hashes)
        )
        if (
            not isinstance(build, dict)
            or build.get("state") != "published"
            or not hash_maps_valid
            or source_hashes != assets
            or not isinstance(publication, dict)
            or publication.get("final_compile_smoke") is not True
            or not isinstance(publication.get("final_project_name"), str)
            or not isinstance(project_hash, str)
            or publication_hash != project_hash
            or len(project_hash) != 64
            or not isinstance(validation, dict)
            or validation.get("valid") is not True
            or validation.get("accepted") is not True
            or not isinstance(validation.get("project_file"), str)
            or Path(validation["project_file"]).suffix.casefold() != ".pscx"
            or not isinstance(validation.get("output_file"), str)
            or Path(validation["output_file"]).suffix.casefold() not in {".out", ".psout"}
            or not isinstance(validation.get("independent_validation"), dict)
            or validation["independent_validation"].get("performed") is not True
            or not isinstance(validation.get("observed"), dict)
            or validation["observed"].get("arm_count") != 12
            or not isinstance(acceptance, dict)
            or acceptance.get("status") != "evaluated"
            or acceptance.get("verdict") != "PASS"
            or not _WINDOWS <= check_names
        ):
            raise ValueError("PASS acceptance reports require complete independent MMC evidence")

    try:
        encoded = json.dumps(payload, allow_nan=False, ensure_ascii=True, sort_keys=True, indent=2)
    except (TypeError, ValueError) as error:
        raise ValueError("acceptance report must be JSON-safe") from error
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded + "\n", encoding="utf-8")
    return path


@pytest.mark.skipif(
    not ACCEPTANCE_ENABLED,
    reason="Set PSCAD_MCP_MMC_ACCEPTANCE=1 to run licensed PSCAD 4.6.2 MMC acceptance.",
)
@pytest.mark.asyncio
async def test_real_mmc_stage_a_acceptance_from_empty_case() -> None:
    config = acceptance_config()
    workspace = config["workspace"]
    assert isinstance(workspace, Path)
    assert workspace.is_dir(), workspace
    workspace_before = _sha256_tree(workspace)
    evidence = evidence_directory(workspace)
    assets = load_packaged_asset_set()
    asset_hashes = dict(assets.hashes)
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "INCOMPLETE_ANALYSIS",
        "config": {"backend": config["backend"], "version": config["version"], "x64": config["x64"], "workspace": str(workspace)},
        "build": {},
        "validation": {},
        "assets": asset_hashes,
        "source_hashes": asset_hashes,
        "workspace_before": workspace_before,
        "workspace_after": {},
    }
    failure: BaseException | None = None
    service: PscadService | None = None
    try:
        backend = LegacyBackend(robust_executor, version="4.6.2", x64=bool(config["x64"]))
        service = PscadService(lambda: backend, path_policy=PathPolicy(workspace_root=str(evidence)))
        builder = MmcBuilderService(service, workspace_root=evidence)
        await service.attach_local()
        plan = builder.plan_model("MMC_STAGE_A", folder=str(evidence))
        started = await builder.build_model("MMC_STAGE_A", plan["plan_hash"], folder=str(evidence), confirm=True)
        build_id = str(started["build_id"])
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 900.0
        while True:
            status = builder.get_build_status(build_id)
            if status.get("state") in {"published", "failed", "timed_out", "interrupted"}:
                break
            if loop.time() >= deadline:
                raise AssertionError("MMC acceptance build timed out")
            await asyncio.sleep(0.5)
        target_project = Path(str(plan["target_path"])).resolve()
        output_file = status.get("result", {}).get("output_file") if isinstance(status.get("result"), dict) else None
        validation = builder.validate_model(str(target_project), output_file=output_file) if status.get("state") == "published" and isinstance(output_file, str) else {"valid": False, "accepted": False, "reason": "build did not publish a retained output"}
        if isinstance(validation, dict):
            validation["independent_validation"] = {"performed": True, "project": str(target_project), "output": output_file}
        report["build"] = status
        report["validation"] = validation
        report["status"] = "PASS" if status.get("state") == "published" and validation.get("valid") and validation.get("accepted") else "FAIL"
        if report["status"] != "PASS":
            raise AssertionError(report)
    except BaseException as error:
        failure = error
        report["status"] = "FAIL"
        report["error"] = _json_error(error)
    finally:
        if service is not None:
            try:
                await service.quit_pscad(confirm=True)
            except BaseException:
                pass
        report["workspace_after"] = _sha256_tree(workspace)
        unchanged_before = {key: value for key, value in report["workspace_after"].items() if key in workspace_before}
        if unchanged_before != workspace_before:
            report["status"] = "FAIL"
            report["workspace_immutability_error"] = {"before": workspace_before, "after": unchanged_before}
            if failure is None:
                failure = AssertionError("pre-existing workspace files changed during MMC acceptance")
        report_path = evidence / "mmc-acceptance-report.json"
        write_acceptance_report(report_path, report)
    if failure is not None:
        raise failure


__all__ = ["ACCEPTANCE_ENABLED", "acceptance_config", "evidence_directory", "write_acceptance_report"]
