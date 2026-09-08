import asyncio
import json
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.engines.pwm import (
    _copy_library_support,
    _legacy_output_settings,
    execute_pwm_candidate,
)
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


class SanitizingProjectNameService(ProductionOutputShapeService):
    async def list_projects(self) -> list[dict[str, str]]:
        self._record("list_projects")
        return [
            {"name": "master", "type": "Library"},
            {"name": "MMC_CASE_pwm__pwm_0", "type": "Case"},
        ]


class RootParameterOnlyService(ProductionOutputShapeService):
    async def get_project_settings(self, project_name: str) -> dict[str, object]:
        self._record("get_project_settings", project_name)
        return {"VdcBase": 640.0, "Sbase": 1000.0}

    async def set_project_settings(
        self, project_name: str, settings: dict[str, object]
    ) -> str:
        self._record("set_project_settings", project_name, settings)
        assert set(settings) <= {"VdcBase", "Sbase"}
        return "set"


class LegacyOutputSettingsService(ProductionOutputShapeService):
    def __init__(self, workspace: Path) -> None:
        super().__init__(workspace)
        self.settings = {
            "PlotType": "0",
            "output_filename": "noname.out",
            "time_step": "50",
            "sample_step": "250",
        }

    async def get_project_settings(self, project_name: str) -> dict[str, object]:
        self._record("get_project_settings", project_name)
        return dict(self.settings)

    async def set_project_settings(
        self, project_name: str, settings: dict[str, object]
    ) -> str:
        self._record("set_project_settings", project_name, settings)
        self.settings.update(settings)
        return "set"


class NoScenarioService(RecordingMmcService):
    run_scenario = None
    analyze_results = None


class MutatingFailedScenarioDomain(CompletedScenarioDomain):
    async def run_scenario(
        self, project_name: str, scenario: dict[str, object], *, confirm: bool = False
    ) -> dict[str, object]:
        Path(project_name).write_text("mutated during scenario", encoding="utf-8")
        return await super().run_scenario(project_name, scenario, confirm=confirm)

    async def scenario_status(self, scenario_id: str) -> dict[str, object]:
        scenario = self.scenarios[scenario_id]
        self.calls.append(("scenario_status", str(scenario["name"])))
        return {
            "scenario_id": scenario_id,
            "status": "failed",
            "output_files": [],
        }


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


def test_pwm_bound_scenario_plans_embedded_control_against_staged_source(tmp_path):
    from pscad_mcp.hvdc.builders.mmc.engines.pwm import _bound_scenarios
    from tests.test_mmc_timed_control import MASTER, PROJECT

    project, library = make_synthetic_official_shape(tmp_path / "source")
    plan = replace(pwm_plan(project, library, tmp_path), scenarios=("pulse",))
    staged = tmp_path / "scenario_source.pscx"
    staged.write_text(PROJECT)
    master = tmp_path / "master.pslx"
    master.write_text(MASTER)
    directory = tmp_path / ".pscad-mcp" / "hvdc-profiles"
    directory.mkdir(parents=True)
    (directory / "pulse.json").write_text(json.dumps({
        "profile_version": 2, "required_assets": [], "project_fingerprints": [], "mappings": [],
        "command_bindings": [{"canonical": "probe", "component": {"canvas": "Main", "component_id": "17", "definition": "master:const"},
            "parameter_name": "Value", "allowed_values": [0, 1], "semantics": "active_high", "read_back": True}],
        "result_channels": [], "metric_roles": {}, "sequences": [],
    }))
    scenario = {"name": "pulse", "profile": "pulse", "events": [{"event_id": "pulse", "time_s": 0.02, "end_time_s": 0.03,
        "target": "probe", "before_value": 0, "value": 1, "after_value": 0, "units": "1"}],
        "time_step_s": 1e-5, "output_step_s": 1e-5, "duration_s": 0.05,
        "timed_control_options": {"master_path": str(master), "max_timing_error_s": 2e-5}}
    bound = _bound_scenarios(plan, [scenario], staged, tmp_path / "candidate.pscx")[0]
    assert bound["timed_control"]["scenario_source"]["sha256"] == sha256(staged)
    assert bound["timed_control"]["events"][0]["target"]["owner"] == "17"
    assert bound["timed_control"]["source_hashes"]["project"]["sha256"] == plan.source_hashes["project"]
    assert bound["derived_project"] != str(tmp_path / "candidate.pscx")
    assert not Path(bound["derived_project"]).exists()


def test_pwm_copies_declared_compiler_library_tree(tmp_path):
    source = tmp_path / "original"
    source.mkdir()
    library = source / "intermediate.pslx"
    library.write_text('<project><paramlist name="Libs"><param name="0" value=".\\lib\\$(Compiler)\\intermediate.lib"/></paramlist></project>')
    binary = source / "lib" / "gf42" / "intermediate.lib"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"compiler library fixture")
    stage = tmp_path / "stage"
    stage.mkdir()
    result = _copy_library_support(library, stage)
    assert result == stage / "lib"
    assert (stage / "lib" / "gf42" / "intermediate.lib").read_bytes() == binary.read_bytes()


def test_pwm_rejects_unplanned_compiler_support_before_staging(tmp_path):
    project, library = make_synthetic_official_shape(tmp_path / "source")
    root = ET.parse(library)
    params = ET.SubElement(root.getroot(), "paramlist", name="Libs")
    ET.SubElement(params, "param", name="0", value=".\\lib\\$(Compiler)\\intermediate.lib")
    root.write(library)
    binary = library.parent / "lib" / "gf42" / "intermediate.lib"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"frozen compiler input")
    plan = replace(pwm_plan(project, library, tmp_path), asset_hashes={})
    service = RecordingMmcService(tmp_path)
    with pytest.raises(BackendError) as raised:
        asyncio.run(execute_pwm_candidate(plan, service))
    assert raised.value.code == "MMC_SOURCE_HASH_MISMATCH"
    assert not (tmp_path / ".mmc-candidates").exists()


def test_pwm_planner_hashes_audited_compiler_support_inputs(tmp_path):
    from pscad_mcp.hvdc.builders.mmc.parametric_planner import create_parametric_plan
    from tests.mmc_parametric_fakes import avm_assets, pwm_audit, valid_request

    binary = tmp_path / "intermediate.lib"
    binary.write_bytes(b"frozen compiler input")
    identity = {"path": str(binary.resolve()), "relative_path": "lib/gf42/intermediate.lib", "sha256": sha256(binary)}
    audit = replace(pwm_audit(), compiler_support={"required": True, "present": True, "files": [identity]})
    parent = create_parametric_plan(valid_request(model_fidelity="detailed_pwm"), "CASE", tmp_path, audit, avm_assets())
    assert dict(parent.engine_plans[0].asset_hashes) == {identity["path"]: identity["sha256"]}


def test_pwm_engine_copies_then_mutates_only_staging(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    source_hashes = (sha256(project), sha256(library))
    service = RecordingMmcService(tmp_path)

    result = asyncio.run(
        execute_pwm_candidate(pwm_plan(project, library, tmp_path), service)
    )

    assert result["state"] == "accepted"
    assert (sha256(project), sha256(library)) == source_hashes
    assert all(Path(path).is_relative_to(tmp_path) for path in result["written_paths"])
    assert all(Path(path).is_relative_to(tmp_path) for path in service.written_paths)
    assert Path(result["project_path"]).is_file()
    assert not (tmp_path / "MMC_CASE_pwm.pscx").exists()


def test_legacy_output_settings_enable_disk_channels_and_convert_time_units() -> None:
    settings = _legacy_output_settings(
        {
            "PlotType": "0",
            "output_filename": "noname.out",
            "time_step": "50",
            "sample_step": "250",
        },
        {"time_step_s": 10e-6, "output_step_s": 50e-6},
        "MMC_CASE_pwm__pwm_0",
    )

    assert settings == {
        "PlotType": "1",
        "output_filename": "MMC_CASE_pwm__pwm_0.out",
        "time_step": "10",
        "sample_step": "50",
    }


def test_pwm_engine_configures_legacy_output_before_build(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    service = LegacyOutputSettingsService(tmp_path)

    result = asyncio.run(
        execute_pwm_candidate(pwm_plan(project, library, tmp_path), service)
    )

    assert result["state"] == "accepted"
    writes = [args[1] for name, args in service.calls if name == "set_project_settings"]
    assert writes
    assert writes[0]["PlotType"] == "1"
    assert writes[0]["output_filename"] == "MMC_CASE_pwm__pwm_0.out"
    assert writes[0]["time_step"] == "10"
    assert writes[0]["sample_step"] == "50"


def test_pwm_engine_accepts_an_explicitly_empty_scenario_plan(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    service = NoScenarioService(tmp_path)
    plan = replace(pwm_plan(project, library, tmp_path), scenarios=())

    result = asyncio.run(execute_pwm_candidate(plan, service))

    assert result["state"] == "accepted"
    assert result["scenario_results"] == []


def test_pwm_engine_copies_sibling_compiler_object_tree(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    support = library.parent / "Obj_Files_2016_03_25" / "gf42"
    support.mkdir(parents=True)
    (support / "MMC_2016_03_25_Exp.obj").write_bytes(b"object")
    stage = tmp_path / "stage"
    stage.mkdir()

    copied = _copy_library_support(library, stage)

    assert copied == stage / "Obj_Files_2016_03_25"
    assert (copied / "gf42" / "MMC_2016_03_25_Exp.obj").read_bytes() == b"object"


def test_pwm_engine_rejects_a_library_with_missing_compiler_object_tree(
    tmp_path: Path,
) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    text = library.read_text(encoding="utf-8").replace(
        "</library>",
        '<param name="object" value="Obj_Files_2016_03_25\\\\$(Compiler)\\\\x.obj" /></library>',
    )
    library.write_text(text, encoding="utf-8")
    stage = tmp_path / "stage"
    stage.mkdir()

    with pytest.raises(BackendError) as raised:
        _copy_library_support(library, stage)

    assert raised.value.code == "MMC_COMPILER_SUPPORT_MISSING"


def test_pwm_engine_uses_pscad_loaded_project_identity(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    service = SanitizingProjectNameService(tmp_path)

    result = asyncio.run(
        execute_pwm_candidate(pwm_plan(project, library, tmp_path), service)
    )

    assert result["state"] == "accepted"
    mutation_names = [
        args[0]
        for name, args in service.calls
        if name
        in {
            "set_component_parameters",
            "set_project_settings",
            "save_project",
            "build_project",
        }
    ]
    assert mutation_names
    assert all(name == "MMC_CASE_pwm__pwm_0" for name in mutation_names)


def test_pwm_engine_filters_abstract_settings_to_pscad_project_parameters(
    tmp_path: Path,
) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    service = RootParameterOnlyService(tmp_path)

    result = asyncio.run(
        execute_pwm_candidate(pwm_plan(project, library, tmp_path), service)
    )

    assert result["state"] == "accepted"
    settings_calls = [
        args for name, args in service.calls if name == "set_project_settings"
    ]
    assert settings_calls == [("MMC_CASE_pwm__pwm-0", {})]


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
                scenario_service=CompletedScenarioDomain(verdict="INCOMPLETE_ANALYSIS"),
                scenarios=_scenario_payloads(plan),
            )
        )

    assert raised.value.code == "MMC_ACCEPTANCE_FAILED"
    assert "get_project_output" not in [name for name, _ in service.calls]


def test_pwm_engine_reports_source_mutation_even_when_scenario_fails(
    tmp_path: Path,
) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    plan = pwm_plan(project, library, tmp_path)

    with pytest.raises(BackendError) as raised:
        asyncio.run(
            execute_pwm_candidate(
                plan,
                ProductionOutputShapeService(tmp_path),
                scenario_service=MutatingFailedScenarioDomain(),
                scenarios=_scenario_payloads(plan),
            )
        )

    assert raised.value.code == "MMC_POSTCONDITION_FAILED"


def test_pwm_engine_stops_before_pscad_when_line_dependency_is_unresolved(
    tmp_path: Path,
) -> None:
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
        asyncio.run(
            execute_pwm_candidate(pwm_plan(project, library, tmp_path), service)
        )

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
def test_pwm_engine_stops_at_public_mutation_boundary(
    tmp_path: Path, boundary: str
) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    service = RecordingMmcService(tmp_path, fail_on=boundary)

    with pytest.raises(RuntimeError, match=f"injected failure at {boundary}"):
        asyncio.run(
            execute_pwm_candidate(pwm_plan(project, library, tmp_path), service)
        )

    names = [name for name, _ in service.calls]
    assert names[-1] == boundary
    assert not (tmp_path / "MMC_CASE_pwm.pscx").exists()
