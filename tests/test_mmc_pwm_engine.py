import asyncio
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.engines.pwm import execute_pwm_candidate
from tests.mmc_parametric_fakes import (
    RecordingMmcService,
    make_synthetic_official_shape,
    pwm_plan,
    pwm_plan_with_unresolved_line_constants,
    sha256,
)


def test_pwm_engine_copies_then_mutates_only_staging(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    source_hashes = (sha256(project), sha256(library))
    service = RecordingMmcService(tmp_path)

    result = asyncio.run(execute_pwm_candidate(pwm_plan(project, library, tmp_path), service))

    assert result["state"] == "accepted"
    assert (sha256(project), sha256(library)) == source_hashes
    assert all(Path(path).is_relative_to(tmp_path) for path in result["written_paths"])
    assert all(Path(path).is_relative_to(tmp_path) for path in service.written_paths)
    assert Path(result["project_path"]).is_file()
    assert not (tmp_path / "MMC_CASE_pwm.pscx").exists()


def test_pwm_engine_stops_before_pscad_when_line_dependency_is_unresolved(tmp_path: Path) -> None:
    plan = pwm_plan_with_unresolved_line_constants(tmp_path)
    service = RecordingMmcService(tmp_path)

    with pytest.raises(BackendError) as raised:
        asyncio.run(execute_pwm_candidate(plan, service))

    assert raised.value.code == "MMC_ABSOLUTE_PATH_UNRESOLVED"
    assert service.calls == []


def test_pwm_engine_rejects_source_drift_before_copy_or_pscad(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    plan = pwm_plan(project, library, tmp_path)
    project.write_text(project.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    service = RecordingMmcService(tmp_path)

    with pytest.raises(BackendError) as raised:
        asyncio.run(execute_pwm_candidate(plan, service))

    assert raised.value.code == "MMC_TEMPLATE_SOURCE_CHANGED"
    assert service.calls == []


def test_pwm_engine_rejects_parameter_readback_mismatch(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    service = RecordingMmcService(tmp_path, mismatch_readback=True)

    with pytest.raises(BackendError) as raised:
        asyncio.run(execute_pwm_candidate(pwm_plan(project, library, tmp_path), service))

    assert raised.value.code == "MMC_POSTCONDITION_FAILED"
    assert "save_project" not in [name for name, _ in service.calls]
    assert not (tmp_path / "MMC_CASE_pwm.pscx").exists()


@pytest.mark.parametrize(
    "boundary",
    [
        "load_projects",
        "set_component_parameters",
        "set_project_settings",
        "save_project",
        "build_project",
        "run_scenario",
        "get_project_output",
    ],
)
def test_pwm_engine_stops_at_public_mutation_boundary(tmp_path: Path, boundary: str) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    service = RecordingMmcService(tmp_path, fail_on=boundary)

    with pytest.raises(RuntimeError, match=f"injected failure at {boundary}"):
        asyncio.run(execute_pwm_candidate(pwm_plan(project, library, tmp_path), service))

    names = [name for name, _ in service.calls]
    assert names[-1] == boundary
    assert not (tmp_path / "MMC_CASE_pwm.pscx").exists()
