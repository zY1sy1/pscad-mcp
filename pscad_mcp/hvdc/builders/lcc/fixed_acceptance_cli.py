"""Explicit run and promotion commands for fixed LCC smoke acceptance."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ....acceptance.preflight import PreflightRequest, run_static_preflight
from ....acceptance.process_scope import acceptance_launch_policy
from ....core.backend.legacy import LegacyBackend
from ....core.executor import robust_executor
from ....core.path_policy import PathPolicy
from ....core.process_inventory import list_pscad_processes
from ....core.service import PscadService
from .assets import sha256_file
from .fixed_acceptance import (
    FIXED_SCOPE,
    FixedLccAcceptanceRequest,
    promote_fixed_lcc_report,
    run_fixed_lcc_acceptance,
    write_fixed_lcc_setup_failure_report,
)
from .service import LccBuilderService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="action", required=True)
    run = subcommands.add_parser("run")
    run.add_argument("--repository-root", type=Path, required=True)
    run.add_argument("--workspace-root", type=Path, required=True)
    run.add_argument("--master-path", type=Path, required=True)
    run.add_argument("--compiler-configuration", type=Path, required=True)
    run.add_argument("--compiler-executable", type=Path, required=True)
    run.add_argument("--report", type=Path, required=True)
    run.add_argument("--baseline", type=Path)
    run.add_argument("--commit", required=True)
    run.add_argument("--branch", required=True)
    run.add_argument("--project-name", default="WP1B_FIXED_LCC")
    promote = subcommands.add_parser("promote")
    promote.add_argument("--baseline", type=Path, required=True)
    promote.add_argument("--report", type=Path, required=True)
    return parser


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _asset_root(repository_root: Path) -> Path:
    return (
        repository_root
        / "pscad_mcp"
        / "assets"
        / "lcc"
        / "cigre_lcc_monopole_v1"
    )


def _preflight(arguments: argparse.Namespace) -> dict[str, Any]:
    asset_root = _asset_root(arguments.repository_root)
    read_only_sources = tuple(
        asset_root / relative
        for relative in (
            "manifest.json",
            "master-bindings-pscad-4.6.2.json",
            "catalog-pscad-4.6.2.json",
            "blueprint.json",
            "library/cigre_lcc_v1.pslx",
            "smoke.json",
            "PROVENANCE.md",
        )
    )
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
                read_only_sources=read_only_sources,
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


def _service_factory(request: FixedLccAcceptanceRequest) -> tuple[Any, Any]:
    backend = LegacyBackend(
        robust_executor,
        version="4.6.2",
        x64=True,
        definition_paths={"master": request.master_path},
        process_probe=list_pscad_processes,
        legacy_existing_policy=acceptance_launch_policy(),
    )
    service = PscadService(
        lambda: backend,
        executor=robust_executor,
        path_policy=PathPolicy(workspace_root=str(request.workspace_root)),
    )
    builder = LccBuilderService(
        service,
        workspace_root=request.workspace_root,
    )
    return service, builder


def main(
    argv: Sequence[str] | None = None,
    *,
    run_action: Callable[..., Any] = run_fixed_lcc_acceptance,
    promote_action: Callable[..., Any] = promote_fixed_lcc_report,
    service_factory: Callable[
        [FixedLccAcceptanceRequest],
        tuple[Any, Any],
    ] = _service_factory,
    preflight_action: Callable[[argparse.Namespace], dict[str, Any]] = _preflight,
    setup_failure_action: Callable[..., dict[str, Any]] = (
        write_fixed_lcc_setup_failure_report
    ),
) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.action == "promote":
        promote_action(arguments.baseline, arguments.report)
        print(f"FIXED_LCC_PROMOTED={FIXED_SCOPE}")
        return 0

    repository_root = arguments.repository_root.resolve()
    workspace_root = arguments.workspace_root.resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    report_path = arguments.report.resolve()
    try:
        report_path.relative_to(workspace_root)
    except ValueError as error:
        raise SystemExit("--report must be inside --workspace-root") from error
    baseline_path = (
        arguments.baseline.resolve()
        if arguments.baseline is not None
        else repository_root
        / "docs"
        / "acceptance"
        / "lcc-mmc-program-baseline.json"
    )
    asset_root = _asset_root(repository_root)
    preflight = preflight_action(arguments)
    request = FixedLccAcceptanceRequest(
        repository_root=repository_root,
        workspace_root=workspace_root,
        master_path=arguments.master_path.resolve(),
        registry_path=(
            asset_root / "master-bindings-pscad-4.6.2.json"
        ).resolve(),
        asset_manifest_path=(asset_root / "manifest.json").resolve(),
        report_path=report_path,
        baseline_path=baseline_path,
        project_name=arguments.project_name,
        commit=arguments.commit,
        branch=arguments.branch,
        preflight=preflight,
    )
    if preflight.get("status") != "PASS":
        result = setup_failure_action(
            request,
            RuntimeError("Fixed LCC static preflight failed."),
        )
        print(f"FIXED_LCC_ACCEPTANCE={result['status']}")
        print(f"FIXED_LCC_REPORT={report_path}")
        print(f"FIXED_LCC_REPORT_SHA256={sha256_file(report_path)}")
        print(f"FIXED_LCC_COMMIT={result['commit']}")
        return 1
    try:
        service, builder = service_factory(request)
    except Exception as error:  # noqa: BLE001 - persist setup failure evidence
        result = setup_failure_action(request, error)
        print(f"FIXED_LCC_ACCEPTANCE={result['status']}")
        print(f"FIXED_LCC_REPORT={report_path}")
        print(f"FIXED_LCC_REPORT_SHA256={sha256_file(report_path)}")
        print(f"FIXED_LCC_COMMIT={result['commit']}")
        return 1
    result = asyncio.run(run_action(request, service=service, builder=builder))
    print(f"FIXED_LCC_ACCEPTANCE={result['status']}")
    print(f"FIXED_LCC_REPORT={report_path}")
    print(f"FIXED_LCC_REPORT_SHA256={sha256_file(report_path)}")
    print(f"FIXED_LCC_COMMIT={result['commit']}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
