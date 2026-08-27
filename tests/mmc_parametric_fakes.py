from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from pscad_mcp.hvdc.scanner import scan_project
from pscad_mcp.hvdc.builders.mmc.assets import load_packaged_asset_set
from pscad_mcp.hvdc.builders.mmc.derivation import derive_mmc_parameters
from pscad_mcp.hvdc.builders.mmc.parametric_models import MmcEnginePlan
from pscad_mcp.hvdc.builders.mmc.parametric_planner import create_parametric_plan
from pscad_mcp.hvdc.builders.mmc.template_audit import build_template_audit
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy


FIXTURES = Path(__file__).parent / "fixtures" / "mmc_synthetic"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_request(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "model_fidelity": "both",
        "topology": "two_terminal_symmetrical_monopole",
        "converter": "half_bridge",
        "dc_voltage_kv": 640.0,
        "active_power_mw": 1000.0,
        "reactive_power_mvar": 0.0,
        "frequency_hz": 60.0,
        "station_p": {"ac_voltage_kv": 230.0, "short_circuit_ratio": 5.0, "x_over_r": 10.0},
        "station_vdc": {"ac_voltage_kv": 230.0, "short_circuit_ratio": 5.0, "x_over_r": 10.0},
        "dc_link": {"kind": "overhead_line", "length_km": 200.0},
        "power_reversal_time_s": 0.5,
        "engineering_overrides": {},
    }
    payload.update(overrides)
    return payload


def load_mmc_synthetic_evidence(name: str):
    return scan_project(FIXTURES / f"{name}.pscx")


def make_synthetic_official_shape(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    project = root / "H_MMC_Mono_DC.pscx"
    library = root / "intermediate.pslx"
    shutil.copy2(FIXTURES / "official_shape.pscx", project)
    shutil.copy2(FIXTURES / "official_shape.pslx", library)
    return project, library


def pwm_audit():
    report = build_template_audit(FIXTURES / "official_shape.pscx", FIXTURES / "official_shape.pslx")
    paths = tuple(
        {
            **item,
            "repair_policy": "verified_rebind" if item["kind"] in {"line_database", "line_constants"} else item["repair_policy"],
        }
        for item in report.absolute_paths
    )
    return replace(report, absolute_paths=paths)


def avm_assets():
    return load_packaged_asset_set()


def pwm_plan(project: Path, library: Path, workspace: Path) -> MmcEnginePlan:
    audit = build_template_audit(project, library)
    audit = replace(
        audit,
        absolute_paths=tuple(
            item
            for item in audit.absolute_paths
            if item["kind"] == "startup_snapshot"
        ),
    )
    parent = create_parametric_plan(
        valid_request(model_fidelity="detailed_pwm"),
        "MMC_CASE",
        workspace,
        audit,
        avm_assets(),
    )
    return replace(
        parent.engine_plans[0],
        source_paths={"project": str(project), "library": str(library)},
        scenarios=("startup", "forward_steady"),
    )


def pwm_plan_with_unresolved_line_constants(workspace: Path) -> MmcEnginePlan:
    project, library = make_synthetic_official_shape(workspace / "source")
    plan = pwm_plan(project, library, workspace)
    return replace(
        plan,
        dependencies=(
            {
                "kind": "line_constants",
                "owner": "converter-vdc",
                "parameter": "line_constants",
                "value": r"C:\synthetic\line_constants.tlo",
                "exists": False,
                "repair_policy": "requires_verified_rebind",
            },
        ),
    )


def avm_parametric_plan(
    workspace: Path,
    dc_voltage_kv: float = 500.0,
    active_power_mw: float = 750.0,
) -> MmcEnginePlan:
    ac_voltage_kv = 230.0 * dc_voltage_kv / 640.0
    parent = create_parametric_plan(
        valid_request(
            model_fidelity="average_value",
            dc_voltage_kv=dc_voltage_kv,
            active_power_mw=active_power_mw,
            station_p={
                "ac_voltage_kv": ac_voltage_kv,
                "short_circuit_ratio": 5.0,
                "x_over_r": 10.0,
            },
            station_vdc={
                "ac_voltage_kv": ac_voltage_kv,
                "short_circuit_ratio": 5.0,
                "x_over_r": 10.0,
            },
        ),
        "MMC_CASE",
        workspace,
        pwm_audit(),
        avm_assets(),
    )
    return parent.engine_plans[0]


def pwm_design():
    audit = pwm_audit()
    return derive_mmc_parameters(
        valid_request(model_fidelity="detailed_pwm"),
        pwm_reference={
            "evidence": f"audited-template:{audit.source_hashes['project']}",
            "reference_cells_per_arm": 400,
            "arm_inductance_h": 0.05,
            "arm_resistance_ohm": 0.15,
            "stored_energy_mj": 40.0,
            "switching_frequency_hz": 1350.0,
            "control_sample_time_s": 50e-6,
            "control_bandwidth_hz": 100.0,
        },
    )


def avm_design():
    assets = avm_assets()
    return derive_mmc_parameters(
        valid_request(model_fidelity="average_value"),
        avm_reference={
            "evidence": f"repository-asset:{assets.name}",
            "reference_cells_per_arm": 400,
            "arm_inductance_h": 0.05,
            "arm_resistance_ohm": 0.15,
            "stored_energy_mj": 40.0,
            "control_sample_time_s": 200e-6,
            "control_bandwidth_hz": 80.0,
        },
    )


def error_with_code(code: str) -> BackendError:
    return BackendError(code, f"synthetic {code}", "fake", "execute_candidate")


def numerical_failure() -> BackendError:
    return BackendError(
        "MMC_NUMERICAL_UNSTABLE",
        "The EMTDC solution diverged.",
        "fake",
        "run_scenario",
        {"phase": "forward_steady", "evidence": "non_finite_output"},
    )


def repeated_failure() -> BackendError:
    from pscad_mcp.hvdc.builders.mmc.diagnostics import classify_mmc_failure

    base = numerical_failure()
    signature = classify_mmc_failure(base).signature
    return BackendError(
        base.code,
        str(base),
        base.backend,
        base.operation,
        {
            **base.details,
            "candidate_id": "pwm-1",
            "previous_failure_signatures": [signature],
        },
    )


def parent_plan_with_four_candidates():
    return create_parametric_plan(
        valid_request(model_fidelity="both"),
        "MMC_CASE",
        FIXTURES,
        pwm_audit(),
        avm_assets(),
    )


class RecordingMmcService:
    def __init__(
        self,
        workspace: Path,
        *,
        fail_on: str | None = None,
        mismatch_readback: bool = False,
    ) -> None:
        self.workspace = workspace.resolve()
        self.path_policy = PathPolicy(workspace_root=str(self.workspace))
        self.fail_on = fail_on
        self.mismatch_readback = mismatch_readback
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.parameters: dict[tuple[str, str], dict[str, Any]] = {}
        self.settings: dict[str, Any] = {}
        self.written_paths: list[Path] = []
        self.scenarios: dict[str, dict[str, Any]] = {}

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        if self.fail_on == name:
            raise RuntimeError(f"injected failure at {name}")

    def _write(self, path: Path) -> None:
        resolved = path.resolve()
        resolved.relative_to(self.workspace)
        self.written_paths.append(resolved)

    async def load_projects(self, filenames: list[str]) -> str:
        self._record("load_projects", filenames)
        for filename in filenames:
            assert Path(filename).resolve().is_relative_to(self.workspace)
        return "loaded"

    async def set_component_parameters(
        self, project_name: str, component_id: str, parameters: dict[str, Any]
    ) -> str:
        self._record("set_component_parameters", project_name, component_id, parameters)
        current = self.parameters.setdefault((project_name, str(component_id)), {})
        current.update(parameters)
        return "set"

    async def get_component_parameters(
        self, project_name: str, component_id: str
    ) -> dict[str, Any]:
        self._record("get_component_parameters", project_name, component_id)
        values = dict(self.parameters.get((project_name, str(component_id)), {}))
        if self.mismatch_readback and values:
            values[next(iter(values))] = "mismatch"
        return values

    async def set_project_settings(self, project_name: str, settings: dict[str, Any]) -> str:
        self._record("set_project_settings", project_name, settings)
        self.settings.update(settings)
        return "set"

    async def get_project_settings(self, project_name: str) -> dict[str, Any]:
        self._record("get_project_settings", project_name)
        return dict(self.settings)

    async def save_project(self, project_name: str, *, confirm: bool = False) -> str:
        self._record("save_project", project_name, confirm)
        return "saved"

    async def build_project(self, project_name: str) -> str:
        self._record("build_project", project_name)
        return "built"

    async def run_scenario(
        self, project_name: str, scenario: dict[str, Any], *, confirm: bool = False
    ) -> dict[str, Any]:
        self._record("run_scenario", project_name, scenario, confirm)
        scenario_id = f"scenario-{len(self.scenarios)}"
        self.scenarios[scenario_id] = dict(scenario)
        return {"scenario_id": scenario_id, "status": "validated"}

    async def scenario_status(self, scenario_id: str) -> dict[str, Any]:
        self._record("scenario_status", scenario_id)
        return {
            "scenario_id": scenario_id,
            "status": "completed",
            "output_files": [f"{scenario_id}.out"],
        }

    async def analyze_results(self, scenario_id: str) -> dict[str, Any]:
        self._record("analyze_results", scenario_id)
        return {
            "scenario_id": scenario_id,
            "verdict": "PASS",
            "resolved_channels": [{"canonical": "dc_voltage"}],
            "metrics": [{"name": "dc_voltage", "status": "observed"}],
        }

    async def get_project_output(self, project_name: str, structured: bool = False) -> dict[str, Any]:
        self._record("get_project_output", project_name, structured)
        return {"verdict": "PASS", "channels": ["VDC", "IDC"]}


class RecordingParametricEngine:
    def __init__(
        self,
        name: str,
        verdict: str,
        calls: list[tuple[str, str]],
    ) -> None:
        self.name = name
        self.verdict = verdict
        self.calls = calls

    async def execute_candidate(
        self,
        plan: MmcEnginePlan,
        service: object,
        *,
        candidate_id: str | None = None,
        **_kwargs: Any,
    ) -> dict[str, object]:
        selected = candidate_id or plan.candidates[0].candidate_id
        self.calls.append((self.name, selected))
        if self.verdict == "NUMERICAL_ONCE" and selected.endswith("-0"):
            raise BackendError(
                "MMC_NUMERICAL_UNSTABLE",
                "synthetic numerical failure",
                "fake",
                "execute_candidate",
                {"candidate_id": selected, "phase": "forward_steady"},
            )
        if self.verdict not in {"PASS", "NUMERICAL_ONCE", "TAMPERED_LIBRARY"}:
            raise BackendError(
                "MMC_ACCEPTANCE_FAILED",
                "synthetic acceptance failure",
                "fake",
                "execute_candidate",
                {"candidate_id": selected},
            )
        candidate_root = (
            Path(plan.workspace)
            / ".test-mmc-candidates"
            / self.name
            / selected
        )
        candidate_root.mkdir(parents=True, exist_ok=False)
        project = candidate_root / f"{plan.target_name}.pscx"
        project.write_text(
            "<project version='4.6.2'><definitions><Definition name='Main'/></definitions></project>",
            encoding="utf-8",
        )
        result: dict[str, object] = {
            "state": "accepted",
            "engine": self.name,
            "candidate_id": selected,
            "candidate_path": str(candidate_root),
            "project_path": str(project),
            "written_paths": [str(project)],
            "validation": {"verdict": "PASS"},
            "capability_level": "accepted",
        }
        if self.name == "detailed_pwm":
            source_library = Path(plan.source_paths["library"])
            library = candidate_root / "intermediate.pslx"
            shutil.copy2(source_library, library)
            result["library_path"] = str(library)
            result["source_hashes"] = dict(plan.source_hashes)
            result["written_paths"] = [str(project), str(library)]
            if self.verdict == "TAMPERED_LIBRARY":
                library.write_text("tampered candidate library", encoding="utf-8")
                result["source_hashes"]["library"] = sha256(library)
        return result

    def validate(
        self,
        plan: MmcEnginePlan,
        project_path: Path,
        outputs: dict[str, object],
    ) -> dict[str, object]:
        return {"verdict": "PASS", "project_path": str(project_path)}


def make_parametric_service(
    workspace: Path,
    pwm_verdict: str = "PASS",
    avm_verdict: str = "PASS",
):
    from pscad_mcp.hvdc.builders.mmc.parametric_service import (
        ParametricMmcBuilderService,
    )

    calls: list[tuple[str, str]] = []
    pscad_service = RecordingMmcService(workspace)
    service = ParametricMmcBuilderService(
        pscad_service,
        workspace_root=workspace,
        pwm_engine=RecordingParametricEngine(
            "detailed_pwm", pwm_verdict, calls
        ),
        avm_engine=RecordingParametricEngine(
            "average_value", avm_verdict, calls
        ),
        audit_loader=lambda *_args, **_kwargs: pwm_audit(),
        asset_loader=lambda: avm_assets(),
    )
    service.recorded_engine_calls = calls
    return service


def wait_for_terminal(service: object, build_id: str) -> dict[str, Any]:
    terminal_states = {"published", "failed", "interrupted"}
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        status = service.get_status(build_id)
        if status["state"] in terminal_states:
            return status
        time.sleep(0.01)
    raise TimeoutError(f"MMC build {build_id} did not reach a terminal state")


def built_wheel_names() -> set[str]:
    repository = Path(__file__).parents[1]
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--outdir",
                str(output),
                str(repository),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        wheels = list(output.glob("*.whl"))
        assert len(wheels) == 1
        with zipfile.ZipFile(wheels[0]) as archive:
            return set(archive.namelist())
