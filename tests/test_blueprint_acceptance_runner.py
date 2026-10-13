import pytest

from scripts.run_blueprint_acceptance import run


@pytest.mark.asyncio
async def test_blueprint_runner_requires_license_optin_before_creating_or_reading_inputs(tmp_path, monkeypatch):
    monkeypatch.delenv("PSCAD_MCP_ACCEPTANCE", raising=False)
    workspace = tmp_path / "new-workspace"
    with pytest.raises(ValueError, match="PSCAD_MCP_ACCEPTANCE=1"):
        await run(workspace, tmp_path / "missing-reference.pscx")
    assert not workspace.exists()


@pytest.mark.asyncio
async def test_blueprint_runner_rejects_source_overlap_before_mutating_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE", "1")
    reference = tmp_path / "reference.pscx"
    reference.write_text("immutable", encoding="utf-8")
    workspace = tmp_path / "workspace"
    with pytest.raises(ValueError, match="disjoint"):
        await run(workspace, reference)
    assert not workspace.exists()
    assert reference.read_text(encoding="utf-8") == "immutable"
