"""Command-line entry point for a durable LCC/MMC preflight report."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from ..core.backend.legacy import LegacyBackend
from ..core.executor import robust_executor
from ..core.path_policy import PathPolicy
from ..core.process_inventory import list_pscad_processes
from ..core.service import PscadService
from .preflight import (
    PreflightRequest,
    run_program_preflight,
    write_preflight_report,
)


def _service(workspace: Path) -> PscadService:
    backend = LegacyBackend(
        robust_executor,
        version="4.6.2",
        x64=True,
        process_probe=list_pscad_processes,
    )
    return PscadService(
        lambda: backend,
        executor=robust_executor,
        path_policy=PathPolicy(workspace_root=str(workspace)),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write a durable LCC/MMC program preflight report.",
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--master-path", type=Path, required=True)
    parser.add_argument("--compiler-configuration", type=Path, required=True)
    parser.add_argument("--compiler-executable", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-branch", required=True)
    parser.add_argument(
        "--read-only-source",
        action="append",
        default=[],
        type=Path,
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Callable[
        [PreflightRequest, Any], Awaitable[dict[str, Any]]
    ] = run_program_preflight,
    service_factory: Callable[[Path], Any] = _service,
) -> int:
    args = _parser().parse_args(argv)
    workspace = args.workspace_root.resolve()
    output = args.output.resolve()
    try:
        output.relative_to(workspace)
    except ValueError as error:
        raise SystemExit(
            "--output must be contained by --workspace-root"
        ) from error
    request = PreflightRequest(
        repository_root=args.repository_root,
        workspace_root=workspace,
        master_path=args.master_path,
        compiler_configuration=args.compiler_configuration,
        compiler_executable=args.compiler_executable,
        expected_commit=args.expected_commit,
        expected_branch=args.expected_branch,
        read_only_sources=tuple(args.read_only_source),
    )
    payload = asyncio.run(runner(request, service_factory(workspace)))
    write_preflight_report(output, payload)
    print(f"PROGRAM_PREFLIGHT={payload['status']}")
    print(f"PROGRAM_PREFLIGHT_REPORT={output}")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
