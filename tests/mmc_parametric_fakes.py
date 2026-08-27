from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from pscad_mcp.hvdc.scanner import scan_project


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
