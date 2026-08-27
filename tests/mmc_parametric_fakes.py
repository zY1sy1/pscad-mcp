from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from pscad_mcp.hvdc.scanner import scan_project
from pscad_mcp.hvdc.builders.mmc.assets import load_packaged_asset_set
from pscad_mcp.hvdc.builders.mmc.parametric_models import MmcEnginePlan
from pscad_mcp.hvdc.builders.mmc.parametric_planner import create_parametric_plan
from pscad_mcp.hvdc.builders.mmc.template_audit import build_template_audit


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


class RecordingMmcService:
    def __init__(
        self,
        workspace: Path,
        *,
        fail_on: str | None = None,
        mismatch_readback: bool = False,
    ) -> None:
        self.workspace = workspace.resolve()
        self.fail_on = fail_on
        self.mismatch_readback = mismatch_readback
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.parameters: dict[tuple[str, str], dict[str, Any]] = {}
        self.settings: dict[str, Any] = {}
        self.written_paths: list[Path] = []

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
        return {"state": "completed", "name": scenario["name"]}

    async def get_project_output(self, project_name: str, structured: bool = False) -> dict[str, Any]:
        self._record("get_project_output", project_name, structured)
        return {"verdict": "PASS", "channels": ["VDC", "IDC"]}
