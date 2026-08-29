"""Read-only static and licensed session checks for LCC/MMC work packages."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.path_policy import PathPolicy
from ..core.process_inventory import list_pscad_processes
from ..core.service import PscadService


@dataclass(frozen=True)
class PreflightRequest:
    repository_root: Path
    workspace_root: Path
    master_path: Path
    compiler_configuration: Path
    compiler_executable: Path
    expected_commit: str
    expected_branch: str
    backend: str = "legacy"
    pscad_version: str = "4.6.2"
    x64: bool = True
    automation_module: str = "mhrc.automation"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_reader(root: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"commit": commit, "branch": branch, "clean": not status.strip()}


def _module_finder(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _process_reader() -> list[dict[str, object]]:
    return list_pscad_processes()


def _workspace_write_probe(workspace: Path) -> bool:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".pscad-mcp-preflight-",
            suffix=".tmp",
            dir=workspace,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(b"preflight\n")
        return temporary.is_file()
    except OSError:
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _compiler_identities(path: Path) -> list[dict[str, str]]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return []
    return [
        {
            "name": item.get("name", ""),
            "version": item.get("version", ""),
            "exe_name": item.get("exe_name", ""),
            "emtdc": item.get("emtdc", ""),
            "compiler_type": item.get("compiler_type", ""),
        }
        for item in root.findall("compiler")
    ]


def _legacy_numbered_output_probe(workspace: Path) -> bool:
    try:
        with tempfile.TemporaryDirectory(
            prefix=".pscad-mcp-output-probe-",
            dir=workspace,
        ) as raw_probe:
            probe = Path(raw_probe)
            project = probe / "PREFLIGHT_CASE.pscx"
            project.write_text("<project />", encoding="ascii")
            generated = probe / "PREFLIGHT_CASE.gf42"
            generated.mkdir()
            output = generated / "PREFLIGHT_CASE_01.out"
            output.write_bytes(b"preflight")
            started_after = max(0.0, output.stat().st_mtime - 0.001)
            service = PscadService(
                lambda: object(),
                path_policy=PathPolicy(workspace_root=str(workspace)),
            )
            discovered = asyncio.run(
                service.discover_output_files(
                    str(project),
                    started_after=started_after,
                    max_files=10,
                )
            )
            return discovered == [str(output.resolve())]
    except (OSError, RuntimeError):
        return False


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def run_static_preflight(
    request: PreflightRequest,
    *,
    git_reader: Callable[[Path], Mapping[str, Any]] = _git_reader,
    module_finder: Callable[[str], bool] = _module_finder,
    process_reader: Callable[[], Sequence[Mapping[str, Any]]] = _process_reader,
    workspace_write_probe: Callable[[Path], bool] = _workspace_write_probe,
    output_discovery_probe: Callable[[Path], bool] = _legacy_numbered_output_probe,
) -> dict[str, Any]:
    repo = request.repository_root.resolve()
    workspace = request.workspace_root.resolve()
    master = request.master_path.resolve()
    compiler = request.compiler_configuration.resolve()
    compiler_executable = request.compiler_executable.resolve()
    git = dict(git_reader(repo))
    processes = [dict(item) for item in process_reader()]
    compiler_identities = (
        _compiler_identities(compiler) if compiler.is_file() else []
    )
    repository_ok = (
        git.get("commit") == request.expected_commit
        and git.get("branch") == request.expected_branch
        and git.get("clean") is True
    )
    workspace_ok = (
        workspace.is_dir()
        and workspace_write_probe(workspace)
        and not _inside(repo, workspace)
        and not _inside(workspace, repo)
        and not _inside(master, workspace)
        and not _inside(compiler, workspace)
        and not _inside(compiler_executable, workspace)
    )
    master_ok = master.is_file() and not master.is_symlink()
    compiler_ok = (
        compiler.is_file()
        and not compiler.is_symlink()
        and compiler_executable.is_file()
        and not compiler_executable.is_symlink()
        and any(
            item["exe_name"].casefold() == compiler_executable.name.casefold()
            for item in compiler_identities
        )
    )
    automation_ok = module_finder(request.automation_module)
    processes_ok = not processes
    output_discovery_ok = (
        workspace_ok and output_discovery_probe(workspace)
    )
    checks = {
        "repository": "PASS" if repository_ok else "FAIL",
        "workspace": "PASS" if workspace_ok else "FAIL",
        "master": "PASS" if master_ok else "FAIL",
        "compiler": "PASS" if compiler_ok else "FAIL",
        "automation": "PASS" if automation_ok else "FAIL",
        "processes": "PASS" if processes_ok else "FAIL",
        "legacy_numbered_output_discovery": (
            "PASS" if output_discovery_ok else "FAIL"
        ),
    }
    return {
        "schema_version": 1,
        "status": (
            "PASS" if all(value == "PASS" for value in checks.values()) else "FAIL"
        ),
        "checks": checks,
        "repository": git,
        "workspace_root": str(workspace),
        "master_path": str(master),
        "master_sha256": _sha256(master) if master_ok else None,
        "compiler_configuration": str(compiler),
        "compiler_configuration_sha256": (
            _sha256(compiler) if compiler_ok else None
        ),
        "compiler_executable": str(compiler_executable),
        "compiler_executable_sha256": (
            _sha256(compiler_executable) if compiler_ok else None
        ),
        "compiler_identities": compiler_identities,
        "automation_module": request.automation_module,
        "external_pscad_processes": processes,
        "backend": request.backend,
        "pscad_version": request.pscad_version,
        "x64": request.x64,
    }
