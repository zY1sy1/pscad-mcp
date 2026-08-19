"""Opt-in licensed PSCAD acceptance for the fixed CIGRE LCC builder."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
import unittest

from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import PscadService
from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set
from pscad_mcp.hvdc.builders.lcc.service import LccBuilderService


ACCEPTANCE_ENABLED = os.getenv("PSCAD_MCP_LCC_ACCEPTANCE") == "1"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    if raw.casefold() in {"1", "true", "yes", "on"}:
        return True
    if raw.casefold() in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be boolean")


def acceptance_config(environ: dict[str, str] | None = None) -> dict[str, object]:
    values = os.environ if environ is None else environ
    workspace_value = values.get("PSCAD_MCP_WORKSPACE")
    if not workspace_value:
        raise ValueError("PSCAD_MCP_WORKSPACE is required")
    workspace = Path(workspace_value).expanduser().resolve()
    if not workspace.is_absolute():
        raise ValueError("PSCAD_MCP_WORKSPACE must be absolute")
    backend = values.get("PSCAD_MCP_BACKEND", "legacy")
    version = values.get("PSCAD_MCP_VERSION", "4.6.2")
    if backend != "legacy":
        raise ValueError("LCC acceptance requires the legacy backend")
    if version != "4.6.2":
        raise ValueError("LCC acceptance requires PSCAD 4.6.2")
    return {
        "enabled": values.get("PSCAD_MCP_LCC_ACCEPTANCE") == "1",
        "backend": backend,
        "version": version,
        "x64": _env_bool("PSCAD_MCP_X64", True) if environ is None else values.get("PSCAD_MCP_X64", "true").casefold() in {"1", "true", "yes", "on"},
        "workspace": workspace,
    }


def evidence_directory(workspace: Path, *, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S-%f")
    directory = workspace / f"lcc-acceptance-{stamp}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def asset_hash_snapshot() -> dict[str, str]:
    assets = load_packaged_asset_set()
    return dict(assets.hashes)


def write_acceptance_report(path: Path, payload: dict[str, object]) -> Path:
    required = {"schema_version", "status", "config", "build", "validation", "assets", "workspace_before", "workspace_after"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"acceptance report is missing fields: {sorted(missing)}")
    if payload.get("schema_version") != 1:
        raise ValueError("acceptance report schema_version must be 1")
    status = payload.get("status")
    if status not in {"PASS", "FAIL", "INCOMPLETE_ANALYSIS"}:
        raise ValueError("acceptance report status is invalid")
    for field in ("config", "build", "validation", "assets", "workspace_before", "workspace_after"):
        if not isinstance(payload.get(field), dict):
            raise ValueError(f"acceptance report field '{field}' must be an object")
    if status == "PASS":
        build = payload["build"]
        validation = payload["validation"]
        acceptance = validation.get("acceptance") if isinstance(validation, dict) else None
        assets = payload["assets"]
        history = build.get("history") if isinstance(build, dict) else None
        publication = next(
            (entry for entry in history if isinstance(entry, dict) and entry.get("state") == "published"),
            None,
        ) if isinstance(history, list) else None
        if (
            not isinstance(build, dict)
            or not isinstance(build.get("asset_hashes"), dict)
            or build.get("asset_hashes") != assets
        ):
            raise ValueError("PASS acceptance reports require matching asset hashes")
        publication_hash = publication.get("final_project_sha256") if isinstance(publication, dict) else None
        validation_hash = validation.get("project_sha256") if isinstance(validation, dict) else None
        if (
            not isinstance(publication_hash, str)
            or not isinstance(validation_hash, str)
            or publication_hash != validation_hash
        ):
            raise ValueError("PASS acceptance reports require matching final project hash")
        if (
            not isinstance(build, dict)
            or build.get("state") != "published"
            or not isinstance(assets, dict)
            or not assets
            or any(not isinstance(key, str) or not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for key, value in assets.items())
            or not isinstance(publication, dict)
            or publication.get("final_compile_smoke") is not True
            or not isinstance(publication.get("final_project_name"), str)
            or re.fullmatch(r"[0-9a-f]{64}", publication.get("final_project_sha256", "")) is None
            or not isinstance(validation, dict)
            or validation.get("valid") is not True
            or validation.get("accepted") is not True
            or not isinstance(validation.get("project_file"), str)
            or Path(validation["project_file"]).suffix.casefold() != ".pscx"
            or not isinstance(validation.get("output_file"), str)
            or Path(validation["output_file"]).suffix.casefold() not in {".out", ".psout"}
            or not isinstance(acceptance, dict)
            or acceptance.get("status") != "evaluated"
            or acceptance.get("verdict") != "PASS"
        ):
            raise ValueError("PASS acceptance reports require published structural and waveform evidence")
    try:
        encoded = json.dumps(payload, allow_nan=False, ensure_ascii=True, sort_keys=True, indent=2)
    except (TypeError, ValueError) as error:
        raise ValueError("acceptance report must be JSON-safe") from error
    path.write_text(encoded + "\n", encoding="utf-8")
    return path


@unittest.skipUnless(
    ACCEPTANCE_ENABLED,
    "Set PSCAD_MCP_LCC_ACCEPTANCE=1 to run licensed PSCAD 4.6.2 LCC acceptance.",
)
class TestLccRealAcceptance(unittest.IsolatedAsyncioTestCase):
    async def test_build_from_empty_case_and_accept(self) -> None:
        config = acceptance_config()
        workspace = config["workspace"]
        assert isinstance(workspace, Path)
        evidence = evidence_directory(workspace)
        assets = load_packaged_asset_set()
        before_assets = dict(assets.hashes)
        before_workspace = {str(path.relative_to(workspace)): sha256_file(path) for path in workspace.rglob("*") if path.is_file()}

        backend = LegacyBackend(
            robust_executor,
            version="4.6.2",
            x64=bool(config["x64"]),
        )
        service = PscadService(lambda: backend, path_policy=PathPolicy(workspace_root=str(workspace)))
        builder = LccBuilderService(service, workspace_root=workspace)
        report: dict[str, object] = {
            "schema_version": 1,
            "status": "INCOMPLETE_ANALYSIS",
            "config": {"backend": config["backend"], "version": config["version"], "x64": config["x64"], "workspace": str(workspace)},
            "build": {},
            "validation": {},
            "assets": before_assets,
            "workspace_before": before_workspace,
            "workspace_after": {},
        }
        try:
            await service.attach_local()
            plan = builder.plan_model("CIGRE_LCC", folder=str(evidence))
            started = await builder.build_model("CIGRE_LCC", plan["plan_hash"], folder=str(evidence), confirm=True)
            build_id = str(started["build_id"])
            deadline = asyncio.get_running_loop().time() + 900.0
            while True:
                status = builder.get_build_status(build_id)
                if status.get("state") in {"published", "failed", "timed_out", "interrupted"}:
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("LCC acceptance build timed out")
                await asyncio.sleep(0.5)
            target_project = Path(str(plan["target_path"])).resolve()
            output_file = status.get("result", {}).get("output_file") if isinstance(status.get("result"), dict) else None
            if not isinstance(output_file, str) or Path(output_file).suffix.casefold() not in {".out", ".psout"}:
                raise AssertionError("The LCC build did not retain the waveform output selected during simulation")
            validation = builder.validate_model(
                str(target_project),
                output_file=output_file,
            )
            report["build"] = status
            report["validation"] = validation
            report["status"] = (
                "PASS"
                if status.get("state") == "published"
                and validation.get("valid")
                and validation.get("accepted")
                and validation.get("acceptance", {}).get("verdict") == "PASS"
                else "FAIL"
            )
            assert report["status"] == "PASS", report
        finally:
            try:
                await service.quit_pscad(confirm=True)
            except Exception:
                pass
            report["workspace_after"] = {
                str(path.relative_to(workspace)): sha256_file(path)
                for path in workspace.rglob("*")
                if path.is_file() and evidence not in path.parents
            }
            assert {key: value for key, value in report["workspace_after"].items() if key in before_workspace} == {
                key: value for key, value in before_workspace.items() if key not in {".pscad-mcp/lcc-build.lock"}
            }
            write_acceptance_report(evidence / "lcc-acceptance-report.json", report)


__all__ = ["ACCEPTANCE_ENABLED", "acceptance_config", "asset_hash_snapshot", "evidence_directory", "write_acceptance_report"]
