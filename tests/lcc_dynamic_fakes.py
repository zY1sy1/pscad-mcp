from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

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
