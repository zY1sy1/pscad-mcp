from __future__ import annotations

import asyncio
from pathlib import Path

from pscad_mcp.hvdc.builders.lcc.dynamic_runner import (
    DynamicLccRunRequest,
    run_fixed_lcc_dynamic_acceptance,
)
from tests.lcc_dynamic_fakes import PassingDynamicBuilder, PassingDynamicService


def valid_request(tmp_path: Path) -> tuple[DynamicLccRunRequest, Path]:
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    staging = workspace / "staging"
    repo.mkdir()
    staging.mkdir(parents=True)
    asset_root = repo / "pscad_mcp" / "assets" / "lcc" / "cigre_lcc_monopole_v1"
    (asset_root / "library").mkdir(parents=True)
    for name in ("blueprint.json", "catalog-pscad-4.6.2.json", "dynamic.json", "master-bindings-pscad-4.6.2.json", "manifest.json", "cigre_lcc_v1.pslx"):
        path = asset_root / ("library" if name.endswith(".pslx") else "") / name
        path.write_text((Path(__file__).parents[1] / "pscad_mcp" / "assets" / "lcc" / "cigre_lcc_monopole_v1" / name).read_text(encoding="utf-8") if name == "dynamic.json" else "{}", encoding="utf-8")
    master = repo / "Master.psdx"
    compiler_cfg = repo / "compiler.cfg"
    compiler_exe = repo / "compiler.exe"
    for path in (master, compiler_cfg, compiler_exe):
        path.write_text("x", encoding="utf-8")
    (staging / "run_01.out").write_text("out", encoding="utf-8")
    (staging / "run.inf").write_text("inf", encoding="utf-8")
    report = workspace / "report.json"
    request = DynamicLccRunRequest(
        repository_root=repo,
        workspace_root=workspace,
        master_path=master,
        compiler_configuration=compiler_cfg,
        compiler_executable=compiler_exe,
        report_path=report,
        commit="a" * 40,
        branch="codex/wp1c",
        preflight={"status": "PASS", "sha256": "a" * 64, "snapshot": {}},
    )
    return request, staging


def test_runner_rederives_output_and_persists_incomplete_success(tmp_path: Path):
    request, staging = valid_request(tmp_path)
    service = PassingDynamicService(staging)
    report = asyncio.run(
        run_fixed_lcc_dynamic_acceptance(
            request,
            service=service,
            builder=PassingDynamicBuilder(staging),
            process_reader=list,
            poll_interval_s=0,
        )
    )
    assert report["engineering_verdict"] == "PASS"
    assert report["golden_verdict"] == "INCOMPLETE_ANALYSIS"
    assert report["status"] == "INCOMPLETE_ANALYSIS"
    assert report["dynamic"]["evidence_source"] == "raw_pscad_output"
    assert report["runtime"]["remaining_processes"] == []
    assert report["artifacts"]["project"]["sha256"]
    assert report["artifacts"]["library"]["sha256"]
    assert ("output", True) in service.calls


def test_runner_static_preflight_failure_writes_fail_without_build(tmp_path: Path):
    request, staging = valid_request(tmp_path)
    request = DynamicLccRunRequest(**{**request.__dict__, "preflight": {"status": "FAIL", "sha256": "a" * 64, "snapshot": {}}})
    builder = PassingDynamicBuilder(staging)
    report = asyncio.run(run_fixed_lcc_dynamic_acceptance(request, service=PassingDynamicService(staging), builder=builder, process_reader=list, poll_interval_s=0))
    assert report["status"] == "FAIL"
    assert report["failure"]["stage"] == "setup"
    assert builder.plan_calls == []
