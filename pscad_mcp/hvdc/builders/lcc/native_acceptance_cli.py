"""Explicit run and promotion commands for native LCC acceptance."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from ....acceptance.preflight import PreflightRequest, run_static_preflight
from ....core.backend.legacy import LegacyBackend
from ....core.executor import robust_executor
from ....core.master_bindings import audit_master_bindings
from ....core.path_policy import PathPolicy
from ....core.process_inventory import list_pscad_processes
from ....core.service import PscadService
from .assets import load_packaged_asset_set, sha256_file
from .blank_service import BlankLccBuilderService
from .native_acceptance import (
    NATIVE_SCOPE,
    NativeLccAcceptanceRequest,
    promote_native_lcc_report,
    run_native_lcc_acceptance,
    write_native_lcc_setup_failure_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="action", required=True)
    run = subcommands.add_parser("run")
    run.add_argument("--repository-root", type=Path, required=True)
    run.add_argument("--workspace-root", type=Path, required=True)
    run.add_argument("--template-path", type=Path, required=True)
    run.add_argument("--master-path", type=Path, required=True)
    run.add_argument("--compiler-configuration", type=Path, required=True)
    run.add_argument("--compiler-executable", type=Path, required=True)
    run.add_argument("--report", type=Path, required=True)
    run.add_argument("--commit", required=True)
    run.add_argument("--branch", required=True)
    run.add_argument("--project-name", default="WP1A_NATIVE_LCC")
    promote = subcommands.add_parser("promote")
    promote.add_argument("--baseline", type=Path, required=True)
    promote.add_argument("--report", type=Path, required=True)
    return parser


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _preflight(arguments: argparse.Namespace) -> dict[str, Any]:
    try:
        report = run_static_preflight(
            PreflightRequest(
                repository_root=arguments.repository_root,
                workspace_root=arguments.workspace_root,
                master_path=arguments.master_path,
                compiler_configuration=arguments.compiler_configuration,
                compiler_executable=arguments.compiler_executable,
                expected_commit=arguments.commit,
                expected_branch=arguments.branch,
                read_only_sources=(arguments.template_path,),
            )
        )
    except Exception as error:  # noqa: BLE001 - persist setup failure evidence
        report = {
            "schema_version": 1,
            "status": "FAIL",
            "error": {
                "type": type(error).__name__,
                "message": str(error)[:1024],
            },
        }
    return {
        "status": str(report["status"]),
        "sha256": _canonical_hash(report),
        "snapshot": report,
    }


def _service_factory(
    request: NativeLccAcceptanceRequest,
) -> tuple[Any, Any, str, str, str]:
    assets = load_packaged_asset_set()
    if assets.master_bindings is None:
        raise RuntimeError("Packaged Master registry is unavailable.")
    audited = audit_master_bindings(request.master_path, assets.master_bindings)
    backend = LegacyBackend(
        robust_executor,
        version="4.6.2",
        x64=True,
        definition_paths={"master": request.master_path},
        process_probe=list_pscad_processes,
    )
    service = PscadService(
        lambda: backend,
        executor=robust_executor,
        path_policy=PathPolicy(workspace_root=str(request.workspace_root)),
    )
    builder = BlankLccBuilderService(
        service,
        workspace_root=request.workspace_root,
        master_registry=audited,
    )
    asset_root = (
        request.repository_root
        / "pscad_mcp"
        / "assets"
        / "lcc"
        / "cigre_lcc_monopole_v1"
    )
    return (
        service,
        builder,
        audited.registry.sha256,
        sha256_file(asset_root / "master-bindings-pscad-4.6.2.json"),
        sha256_file(asset_root / "manifest.json"),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    run_action: Callable[..., Any] = run_native_lcc_acceptance,
    promote_action: Callable[..., Any] = promote_native_lcc_report,
    service_factory: Callable[
        [NativeLccAcceptanceRequest],
        tuple[Any, Any, str, str, str],
    ] = _service_factory,
    preflight_action: Callable[[argparse.Namespace], dict[str, Any]] = _preflight,
    setup_failure_action: Callable[..., dict[str, Any]] = (
        write_native_lcc_setup_failure_report
    ),
) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.action == "promote":
        promote_action(arguments.baseline, arguments.report)
        print(f"NATIVE_LCC_PROMOTED={NATIVE_SCOPE}")
        return 0

    workspace = arguments.workspace_root.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    report_path = arguments.report.resolve()
    try:
        report_path.relative_to(workspace)
    except ValueError as error:
        raise SystemExit("--report must be inside --workspace-root") from error
    preflight = preflight_action(arguments)
    request = NativeLccAcceptanceRequest(
        repository_root=arguments.repository_root.resolve(),
        workspace_root=workspace,
        template_path=arguments.template_path.resolve(),
        master_path=arguments.master_path.resolve(),
        report_path=report_path,
        project_name=arguments.project_name,
        commit=arguments.commit,
        branch=arguments.branch,
        registry_sha256="0" * 64,
        registry_file_sha256="0" * 64,
        asset_manifest_sha256="0" * 64,
        preflight=preflight,
    )
    try:
        service, builder, registry_hash, registry_file_hash, manifest_hash = (
            service_factory(request)
        )
    except Exception as error:  # noqa: BLE001 - persist setup failure evidence
        result = setup_failure_action(request, error)
        print(f"NATIVE_LCC_ACCEPTANCE={result['status']}")
        print(f"NATIVE_LCC_REPORT={report_path}")
        print(f"NATIVE_LCC_REPORT_SHA256={sha256_file(report_path)}")
        print(f"NATIVE_LCC_COMMIT={result['commit']}")
        return 1
    request = replace(
        request,
        registry_sha256=registry_hash,
        registry_file_sha256=registry_file_hash,
        asset_manifest_sha256=manifest_hash,
    )
    result = asyncio.run(run_action(request, service=service, builder=builder))
    print(f"NATIVE_LCC_ACCEPTANCE={result['status']}")
    print(f"NATIVE_LCC_REPORT={report_path}")
    print(f"NATIVE_LCC_REPORT_SHA256={sha256_file(report_path)}")
    print(f"NATIVE_LCC_COMMIT={result['commit']}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
