from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

from pscad_mcp.hvdc.builders.lcc.dynamic_evidence import (
    derive_fixed_lcc_dynamic_evidence,
)

ROOT = Path(__file__).parents[1]
DYNAMIC_CONTRACT = (
    ROOT
    / "pscad_mcp"
    / "assets"
    / "lcc"
    / "cigre_lcc_monopole_v1"
    / "dynamic.json"
)


def dynamic_contract() -> dict[str, Any]:
    return json.loads(DYNAMIC_CONTRACT.read_text(encoding="utf-8"))


def passing_raw_channels(*, step_s: float = 0.00005, end_s: float = 1.5) -> dict[str, Any]:
    count = round(end_s / step_s) + 1
    time = [round(index * step_s, 10) for index in range(count)]
    fault = [1.0 if 0.8 <= item < 0.9 else 0.0 for item in time]
    disturbed = [0.8 <= item < 0.9 for item in time]

    def channel(path: str, units: str, values: list[float]) -> dict[str, Any]:
        return {"path": path, "units": units, "domain": time, "values": values}

    def constant(value: float) -> list[float]:
        return [float(value) for _item in time]

    return {
        "channels": [
            channel("Fault/LCC Fault Active", "state", fault),
            channel("Main/IDC", "kA", [1.5 if active else 1.0 for active in disturbed]),
            channel("Main/VDC_RECT", "kV", [350.0 if active else 500.0 for active in disturbed]),
            channel("Main/VDC_INV", "kV", [-250.0 if active else -480.0 for active in disturbed]),
            channel(
                "Main/GAMMA_INV",
                "rad",
                [math.radians(5.0 if active else 18.0) for active in disturbed],
            ),
            channel("Main/P_RECT", "MW", constant(500.0)),
            channel("Main/P_INV", "MW", constant(-480.0)),
            channel("Main/ALPHA_RECT", "rad", constant(math.radians(15.0))),
            channel("Main/MU_RECT", "rad", constant(math.radians(10.0))),
        ]
    }


def valid_wp1c_report() -> dict[str, Any]:
    """Runner-shaped durable report fixture shared by dynamic tests."""
    digest = "a" * 64
    commit = "a" * 40
    return {
        "schema_version": 1,
        "run_id": "dynamic-run-1",
        "scope": "lcc.fixed_autonomous",
        "builder_path": "lcc.fixed_autonomous",
        "kind": "licensed_simulation",
        "capability_state": "simulated",
        "commit": commit,
        "generated_at_utc": "2026-09-01T00:00:00Z",
        "engineering_verdict": "PASS",
        "golden_verdict": "INCOMPLETE_ANALYSIS",
        "status": "INCOMPLETE_ANALYSIS",
        "repository": {"branch": "codex/wp1c", "commit": commit, "clean": True},
        "preflight": {"status": "PASS", "sha256": digest, "snapshot": {name: {"path": f"/tmp/{name}", "sha256": digest} for name in ("blueprint", "catalog", "dynamic", "registry", "manifest", "companion", "master", "compiler_configuration", "compiler_executable")}},
        "sources": {
            name: {"path": f"/tmp/{name}", "before": digest, "after": digest}
            for name in ("blueprint", "catalog", "dynamic", "registry", "manifest", "companion", "master", "compiler_configuration", "compiler_executable")
        },
        "build": {
            "project_name": "WP1C_FIXED_LCC",
            "workspace": "/tmp",
            "build_id": "build-1",
            "plan_hash": digest,
            "verification_profile": "wp1c_dynamic",
            "history": ["validated", "dynamic_engineering_passed", "published"],
            "terminal_state": "published",
        },
        "artifacts": {
            "project": {"path": "/tmp/project.pscx", "sha256": digest},
            "library": {"path": "/tmp/library.pslx", "sha256": digest},
            "selected_output": {"path": "/tmp/staging/run_01.out", "sha256": digest},
            "output_parts": [{"path": "/tmp/staging/run_01.out", "sha256": digest}],
            "output_metadata": [{"path": "/tmp/staging/run.inf", "sha256": digest}],
            "normalized_samples": {"path": "/tmp/normalized-samples.json", "sha256": digest},
        },
        "dynamic": {
            "evidence_source": "raw_pscad_output",
            "engineering_verdict": "PASS",
            "checks": {"disturbance": {"outcome": "PASS", "selectors": ["Fault/LCC Fault Active"], "units": {"Fault/LCC Fault Active": "state"}, "window_s": [0.0, 1.0], "sample_count": 1, "metrics": {}}},
        },
        "physical": {"verdict": "PASS", "checks": []},
        "golden": {"source": "placeholder", "reviewed": False},
        "runtime": {
            "remaining_processes": [],
            "managed_pid": None,
            "backend": None,
            "version": None,
            "x64": None,
            "licensed": None,
            "quit_error": None,
        },
        "explicit_exclusions": ["independent_golden", "final_accepted"],
        "failure": None,
    }


class PassingDynamicService:
    def __init__(self, staging: Path):
        self.staging = staging
        self.attached = False
        self.quit_called = False
        self.calls: list[tuple[str, Any]] = []

    async def attach_local(self):
        self.attached = True
        self.calls.append(("attach", None))

    async def status(self):
        return {"backend": "legacy", "version": "4.6.2", "x64": True, "licensed": True, "session": {"managed_pid": None}}

    async def get_project_output(self, project_name: str, *, summary_only: bool = True):
        self.calls.append(("output", summary_only))
        raw = passing_raw_channels()
        return {
            "output_file": str(self.staging / "run_01.out"),
            "channels": raw,
            "executor_evidence": derive_fixed_lcc_dynamic_evidence(raw, dynamic_contract()),
        }

    async def quit_pscad(self, *, confirm: bool = False):
        self.quit_called = True
        self.calls.append(("quit", confirm))


class PassingDynamicBuilder:
    def __init__(self, staging: Path):
        self.staging = staging
        self.plan_calls: list[dict[str, Any]] = []
        self.build_calls: list[dict[str, Any]] = []
        self.shutdown_called = False

    def plan_model(self, **kwargs):
        self.plan_calls.append(kwargs)
        return {"plan_hash": "b" * 64}

    async def build_model(self, **kwargs):
        self.build_calls.append(kwargs)
        now = time.time()
        for output in (self.staging / "run_01.out", self.staging / "run.inf"):
            os.utime(output, (now, now))
        project = self.staging.parent / "WP1C_FIXED_LCC.pscx"
        library = self.staging.parent / "cigre_lcc_v1.pslx"
        project.write_text("project", encoding="utf-8")
        library.write_text("library", encoding="utf-8")
        import hashlib
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        return {"build_id": "build-1", "project_path": str(project), "project_sha256": digest(project), "library_path": str(library), "library_sha256": digest(library)}

    def get_build_status(self, build_id: str):
        raw = passing_raw_channels()
        return {"state": "published", "history": [{"state": "validated"}, {"state": "dynamic_engineering_passed"}, {"state": "published"}], "result": {"dynamic": derive_fixed_lcc_dynamic_evidence(raw, dynamic_contract()), "physical": {"verdict": "PASS", "checks": []}}}

    async def shutdown(self, *, timeout_s: float = 5.0):
        self.shutdown_called = True
