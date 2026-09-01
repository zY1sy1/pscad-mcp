from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from pscad_mcp.acceptance.preflight import PreflightRequest, run_static_preflight


def request(tmp_path: Path) -> PreflightRequest:
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    install = tmp_path / "PSCAD46"
    repo.mkdir()
    workspace.mkdir()
    install.mkdir()
    master = install / "master.pslx"
    master.write_text("<pslx />", encoding="utf-8")
    compiler = install / "fortran_compilers.xml"
    compiler.write_text(
        "<compilers><compiler name='MHRC' version='4.6.2' "
        "exe_name='gfortran.exe' emtdc='gf46' compiler_type='x86'/></compilers>",
        encoding="utf-8",
    )
    compiler_executable = install / "gfortran.exe"
    compiler_executable.write_bytes(b"fake-gfortran")
    return PreflightRequest(
        repository_root=repo,
        workspace_root=workspace,
        master_path=master,
        compiler_configuration=compiler,
        compiler_executable=compiler_executable,
        expected_commit="dadd739e2abc14dcc7de73149da7fd7f0c0ca763",
        expected_branch="main",
    )


def clean_git(value: PreflightRequest) -> dict[str, object]:
    return {
        "commit": value.expected_commit,
        "branch": value.expected_branch,
        "clean": True,
    }


def test_static_preflight_reports_all_required_checks(tmp_path):
    value = request(tmp_path)

    report = run_static_preflight(
        value,
        git_reader=lambda root: clean_git(value),
        module_finder=lambda name: name == "mhrc.automation",
        process_reader=list,
        output_discovery_probe=lambda workspace: True,
    )

    assert report["status"] == "PASS"
    assert report["checks"] == {
        "repository": "PASS",
        "workspace": "PASS",
        "master": "PASS",
        "compiler": "PASS",
        "automation": "PASS",
        "processes": "PASS",
        "read_only_sources": "PASS",
        "legacy_numbered_output_discovery": "PASS",
    }
    assert len(report["master_sha256"]) == 64
    assert len(report["compiler_configuration_sha256"]) == 64
    assert len(report["compiler_executable_sha256"]) == 64


def test_source_inside_workspace_and_external_pscad_are_failures(tmp_path):
    value = request(tmp_path)
    source_inside = value.workspace_root / "master.pslx"
    source_inside.write_text("<pslx />", encoding="utf-8")
    value = PreflightRequest(
        repository_root=value.repository_root,
        workspace_root=value.workspace_root,
        master_path=source_inside,
        compiler_configuration=value.compiler_configuration,
        compiler_executable=value.compiler_executable,
        expected_commit=value.expected_commit,
        expected_branch=value.expected_branch,
    )

    report = run_static_preflight(
        value,
        git_reader=lambda root: clean_git(value),
        module_finder=lambda name: True,
        process_reader=lambda: [{"pid": 12, "name": "PSCAD.exe"}],
        output_discovery_probe=lambda workspace: True,
    )

    assert report["status"] == "FAIL"
    assert report["checks"]["workspace"] == "FAIL"
    assert report["checks"]["processes"] == "FAIL"


def test_dirty_or_wrong_commit_repository_fails(tmp_path):
    value = request(tmp_path)

    report = run_static_preflight(
        value,
        git_reader=lambda root: {
            "commit": "f" * 40,
            "branch": "feature",
            "clean": False,
        },
        module_finder=lambda name: True,
        process_reader=list,
        output_discovery_probe=lambda workspace: True,
    )

    assert report["status"] == "FAIL"
    assert report["checks"]["repository"] == "FAIL"


def test_legacy_numbered_output_discovery_failure_is_explicit(tmp_path):
    value = request(tmp_path)

    report = run_static_preflight(
        value,
        git_reader=lambda root: clean_git(value),
        module_finder=lambda name: True,
        process_reader=list,
        output_discovery_probe=lambda workspace: False,
    )

    assert report["status"] == "FAIL"
    assert report["checks"]["legacy_numbered_output_discovery"] == "FAIL"


def test_default_probe_discovers_legacy_numbered_output_parts(tmp_path):
    value = request(tmp_path)

    report = run_static_preflight(
        value,
        git_reader=lambda root: clean_git(value),
        module_finder=lambda name: True,
        process_reader=list,
    )

    assert report["status"] == "PASS"
    assert report["checks"]["legacy_numbered_output_discovery"] == "PASS"


def test_default_output_probe_never_creates_pscad_project(monkeypatch, tmp_path):
    value = request(tmp_path)
    original_write_text = Path.write_text

    def reject_project_write(path, *args, **kwargs):
        if path.suffix.casefold() == ".pscx":
            raise AssertionError("static preflight must not create PSCX files")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", reject_project_write)

    report = run_static_preflight(
        value,
        git_reader=lambda root: clean_git(value),
        module_finder=lambda name: True,
        process_reader=list,
    )

    assert report["status"] == "PASS"


class SessionService:
    def __init__(self, *, alive: bool = True) -> None:
        self.alive = alive
        self.calls = []

    async def attach_local(self):
        self.calls.append("attach_local")
        return "attached"

    async def status(self):
        self.calls.append("status")
        return {
            "connected": self.alive,
            "licensed": True,
            "backend": "legacy",
            "version": "4.6.2",
            "x64": True,
            "alive": self.alive,
            "busy": False,
            "owns_process": True,
        }

    async def quit_pscad(self, *, confirm=False):
        self.calls.append(("quit_pscad", confirm))
        return "quit"


def test_licensed_session_probe_attaches_reads_and_quits_without_project_creation(
    tmp_path,
):
    from pscad_mcp.acceptance.preflight import run_licensed_session_preflight

    service = SessionService()
    result = asyncio.run(
        run_licensed_session_preflight(
            service,
            workspace_root=tmp_path,
            process_reader=list,
        )
    )

    assert result["status"] == "PASS"
    assert service.calls == ["attach_local", "status", ("quit_pscad", True)]
    assert "create_project" not in service.calls
    assert result["projects_before"] == result["projects_after"] == {}


def test_licensed_session_probe_reports_runtime_and_cleanup_failure(tmp_path):
    from pscad_mcp.acceptance.preflight import run_licensed_session_preflight

    service = SessionService(alive=False)
    process_snapshots = iter(
        [[], [{"pid": 99, "name": "PSCAD.exe", "exe": "C:/PSCAD.exe"}]]
    )
    result = asyncio.run(
        run_licensed_session_preflight(
            service,
            workspace_root=tmp_path,
            process_reader=lambda: next(process_snapshots),
        )
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["runtime"] == "FAIL"
    assert result["checks"]["cleanup"] == "FAIL"


def test_preexisting_pscad_process_prevents_attach(tmp_path):
    from pscad_mcp.acceptance.preflight import run_licensed_session_preflight

    service = SessionService()
    result = asyncio.run(
        run_licensed_session_preflight(
            service,
            workspace_root=tmp_path,
            process_reader=lambda: [
                {"pid": 12, "name": "PSCAD.exe", "exe": "C:/PSCAD.exe"}
            ],
        )
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["process_conflict"] == "FAIL"
    assert service.calls == []


def test_program_preflight_combines_commit_session_and_source_immutability(tmp_path):
    from pscad_mcp.acceptance.preflight import run_program_preflight

    value = request(tmp_path)
    master_hash = hashlib.sha256(value.master_path.read_bytes()).hexdigest()
    compiler_hash = hashlib.sha256(
        value.compiler_configuration.read_bytes()
    ).hexdigest()
    compiler_executable_hash = hashlib.sha256(
        value.compiler_executable.read_bytes()
    ).hexdigest()

    def static_runner(candidate):
        assert candidate == value
        return {
            "status": "PASS",
            "master_sha256": master_hash,
            "compiler_configuration_sha256": compiler_hash,
            "compiler_executable_sha256": compiler_executable_hash,
            "read_only_source_hashes": {},
        }

    async def session_runner(service, *, workspace_root):
        assert workspace_root == value.workspace_root
        return {"status": "PASS"}

    result = asyncio.run(
        run_program_preflight(
            value,
            object(),
            static_runner=static_runner,
            session_runner=session_runner,
        )
    )

    assert result["status"] == "PASS"
    assert result["commit"] == value.expected_commit
    assert result["source_immutability_status"] == "PASS"


def test_program_preflight_runs_sync_static_probe_outside_event_loop(tmp_path):
    from pscad_mcp.acceptance.preflight import run_program_preflight

    value = request(tmp_path)
    master_hash = hashlib.sha256(value.master_path.read_bytes()).hexdigest()
    compiler_hash = hashlib.sha256(
        value.compiler_configuration.read_bytes()
    ).hexdigest()
    compiler_executable_hash = hashlib.sha256(
        value.compiler_executable.read_bytes()
    ).hexdigest()

    async def nested_probe():
        return {
            "status": "PASS",
            "master_sha256": master_hash,
            "compiler_configuration_sha256": compiler_hash,
            "compiler_executable_sha256": compiler_executable_hash,
            "read_only_source_hashes": {},
        }

    def static_runner(candidate):
        assert candidate == value
        return asyncio.run(nested_probe())

    async def session_runner(service, *, workspace_root):
        return {"status": "PASS"}

    result = asyncio.run(
        run_program_preflight(
            value,
            object(),
            static_runner=static_runner,
            session_runner=session_runner,
        )
    )

    assert result["status"] == "PASS"


def test_program_preflight_detects_declared_source_mutation(tmp_path):
    from pscad_mcp.acceptance.preflight import run_program_preflight

    value = request(tmp_path)
    source = tmp_path / "official.pscx"
    source.write_text("before", encoding="utf-8")
    value = PreflightRequest(
        repository_root=value.repository_root,
        workspace_root=value.workspace_root,
        master_path=value.master_path,
        compiler_configuration=value.compiler_configuration,
        compiler_executable=value.compiler_executable,
        expected_commit=value.expected_commit,
        expected_branch=value.expected_branch,
        read_only_sources=(source,),
    )
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    def static_runner(candidate):
        return {
            "status": "PASS",
            "master_sha256": hashlib.sha256(
                value.master_path.read_bytes()
            ).hexdigest(),
            "compiler_configuration_sha256": hashlib.sha256(
                value.compiler_configuration.read_bytes()
            ).hexdigest(),
            "compiler_executable_sha256": hashlib.sha256(
                value.compiler_executable.read_bytes()
            ).hexdigest(),
            "read_only_source_hashes": {source.as_posix(): source_hash},
        }

    async def session_runner(service, *, workspace_root):
        source.write_text("after", encoding="utf-8")
        return {"status": "PASS"}

    result = asyncio.run(
        run_program_preflight(
            value,
            object(),
            static_runner=static_runner,
            session_runner=session_runner,
        )
    )

    assert result["status"] == "FAIL"
    assert result["source_immutability_status"] == "FAIL"
