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


class CompletedScenarioDomain:
    def __init__(self, *, verdict: str = "PASS") -> None:
        self.verdict = verdict
        self.calls: list[tuple[str, str]] = []
        self.scenarios: dict[str, dict[str, object]] = {}

    async def run_scenario(
        self, project_name: str, scenario: dict[str, object], *, confirm: bool = False
    ) -> dict[str, object]:
        scenario_id = f"scenario-{len(self.scenarios)}"
        self.calls.append(("run_scenario", str(scenario["name"])))
        self.scenarios[scenario_id] = dict(scenario)
        return {"scenario_id": scenario_id, "status": "validated"}

    async def scenario_status(self, scenario_id: str) -> dict[str, object]:
        scenario = self.scenarios[scenario_id]
        self.calls.append(("scenario_status", str(scenario["name"])))
        return {
            "scenario_id": scenario_id,
            "status": "completed",
            "output_files": [f"{scenario_id}.out"],
        }

    async def analyze_results(self, scenario_id: str) -> dict[str, object]:
        scenario = self.scenarios[scenario_id]
        self.calls.append(("analyze_results", str(scenario["name"])))
        return {
            "scenario_id": scenario_id,
            "verdict": self.verdict,
            "resolved_channels": [{"canonical": "dc_voltage"}],
            "metrics": [{"name": "dc_voltage", "status": "observed"}],
        }


class ProductionOutputShapeService(RecordingMmcService):
    async def get_project_output(
        self, project_name: str, structured: bool = False
    ) -> list[dict[str, object]]:
        self._record("get_project_output", project_name, structured)
        return [{"severity": "info", "text": "Build completed", "source": None}]


def _scenario_payloads(plan) -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "profile": "mmc_detailed_pwm_v2",
            "project": "MMC_CASE_pwm_scenario_source",
            "derived_project": "MMC_CASE_pwm",
            "parameter_changes": [],
            "events": [],
            "analysis": {"metrics": ["dc_voltage"]},
        }
        for name in plan.scenarios
    ]


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


def test_pwm_engine_accepts_only_terminal_analyzed_scenario_evidence(
    tmp_path: Path,
) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    plan = pwm_plan(project, library, tmp_path)
    service = ProductionOutputShapeService(tmp_path)
    domain = CompletedScenarioDomain()

    result = asyncio.run(
        execute_pwm_candidate(
            plan,
            service,
            scenario_service=domain,
            scenarios=_scenario_payloads(plan),
        )
    )

    assert result["state"] == "accepted"
    assert result["capability_level"] == "accepted"
    assert [name for name, _ in domain.calls] == [
        "run_scenario",
        "scenario_status",
        "analyze_results",
    ] * len(plan.scenarios)
    assert "get_project_output" not in [name for name, _ in service.calls]


def test_pwm_engine_rejects_incomplete_analysis_even_when_runs_complete(
    tmp_path: Path,
) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    plan = pwm_plan(project, library, tmp_path)
    service = ProductionOutputShapeService(tmp_path)

    with pytest.raises(BackendError) as raised:
        asyncio.run(
            execute_pwm_candidate(
                plan,
                service,
                scenario_service=CompletedScenarioDomain(
                    verdict="INCOMPLETE_ANALYSIS"
                ),
                scenarios=_scenario_payloads(plan),
            )
        )

    assert raised.value.code == "MMC_ACCEPTANCE_FAILED"
    assert "get_project_output" not in [name for name, _ in service.calls]


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
        "scenario_status",
        "analyze_results",
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
