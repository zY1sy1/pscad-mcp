from pathlib import Path


def test_changelog_describes_current_release_boundary():
    text = (Path(__file__).parents[1] / "CHANGELOG.md").read_text(encoding="utf-8").lower()

    assert "## [0.2.0]" in text
    assert "60" in text
    assert "simulation set" in text
    assert "pscad 4.6.2" in text
    assert "pscad 5.x" in text
    assert "contract" in text
    assert "silent learning" in text
    assert "87" in text
    assert "blueprint builder" in text
def test_readmes_document_the_fixed_lcc_builder_boundary():
    root = Path(__file__).parents[1]
    english = (root / "README.md").read_text(encoding="utf-8").lower()
    chinese = (root / "docs" / "zh-CN" / "README.md").read_text(encoding="utf-8")

    for tool in ("plan_lcc_model", "build_lcc_model", "get_lcc_build_status", "validate_lcc_model"):
        assert tool in english
        assert tool in chinese
    for phrase in (
        "pscad 4.6.2",
        "fixed electrical parameters",
        "single-pole",
        "confirm=true",
        "plan hash",
        "original companion library",
        "workspace writes",
        "planned",
        "built",
        "simulated",
        "accepted",
        "licensed acceptance has not passed",
    ):
        assert phrase in english
    for phrase in ("PSCAD 4.6.2", "固定电气参数", "单极", "confirm=true", "工作区写入", "授权验收尚未通过"):
        assert phrase in chinese


def test_readmes_document_the_generic_blueprint_builder_boundary():
    root = Path(__file__).parents[1]
    english = (root / "README.md").read_text(encoding="utf-8")
    chinese = (root / "docs" / "zh-CN" / "README.md").read_text(encoding="utf-8")
    tools = (
        "plan_pscad_project_build",
        "build_pscad_project",
        "get_pscad_project_build_status",
        "validate_pscad_project_build",
    )
    for text in (english, chinese):
        for tool in tools:
            assert tool in text
        for phrase in ("plan_hash", "confirm=true", "run_through_acceptance", "physical_acceptance"):
            assert phrase in text
    assert "licensed acceptance has not been run" in english.lower()
    assert "尚未运行" in chinese


def test_breaker_workdoc_records_implemented_and_live_status_separately():
    text = (Path(__file__).parents[1] / "docs" / "zh-CN" / "2026-08-25-breaker-engineering-package-auto-modeling-workdoc.md").read_text(encoding="utf-8")
    for phrase in ("implemented", "test_verified", "live_verified", "通用 Blueprint Builder", "尚未完成 Breaker 实机验收"):
        assert phrase in text


def test_readmes_and_changelog_document_blueprint_corpus_boundaries():
    root = Path(__file__).parents[1]
    english = " ".join((root / "README.md").read_text(encoding="utf-8").lower().split())
    chinese = " ".join((root / "docs" / "zh-CN" / "README.md").read_text(encoding="utf-8").split())
    changelog = " ".join((root / "CHANGELOG.md").read_text(encoding="utf-8").lower().split())

    for command in ("build_blueprint_corpus.py generate", "build_blueprint_corpus.py verify", "build_blueprint_corpus.py compare"):
        assert command in english
        assert command in chinese
    for phrase in (
        "deterministic derived data",
        "original pscad models and simulation results are never committed",
        "independent of `pscad_mcp.learning`",
        "optional and read-only",
    ):
        assert phrase in english
    for phrase in ("确定性派生数据", "原始 PSCAD 模型和仿真结果永不提交", "独立于 `pscad_mcp.learning`", "可选且只读"):
        assert phrase in chinese
    for phrase in ("blueprint corpus", "implemented=true", "test_verified=true", "live_verified=false"):
        assert phrase in changelog
