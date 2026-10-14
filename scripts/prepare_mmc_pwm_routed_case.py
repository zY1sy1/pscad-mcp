"""Prepare immutable routed PWM scenario inputs; no licensed acceptance claim."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pscad_mcp.hvdc.builders.mmc.derivation import derive_mmc_parameters
from pscad_mcp.hvdc.builders.mmc.pwm_channels import routed_pwm_profile
from pscad_mcp.hvdc.builders.mmc.pwm_preparation import prepare_routed_pwm_case
from pscad_mcp.hvdc.builders.mmc.pwm_routed_engine import require_supported_request
from pscad_mcp.hvdc.builders.mmc.pwm_scenarios import prepare_routed_scenario_source
from pscad_mcp.hvdc.builders.mmc.scenarios import (
    prepare_timed_scenario,
    recommend_scenarios,
)
from pscad_mcp.hvdc.profiles import register_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    require_supported_request(request)
    directory = args.workspace.resolve()
    prepared = prepare_routed_pwm_case(
        args.source, args.library, args.master, directory
    )
    profile = routed_pwm_profile(prepared)
    profile_file = directory / "profile.json"
    profile_file.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    profile_name = "mmc_pwm_routed_640kv_v1"
    register_profile(profile_name, str(profile_file), workspace_root=directory)
    (directory / "request.json").write_text(
        json.dumps(request, indent=2), encoding="utf-8"
    )
    for item in recommend_scenarios(derive_mmc_parameters(request)):
        scenario = item.to_dict()["scenario"]
        scenario["profile"] = profile_name
        folder = directory / scenario["name"]
        folder.mkdir()
        scenario = prepare_routed_scenario_source(
            prepared["project"], folder / "H_MMC_Mono_DC.pscx", scenario
        )
        scenario["timed_control_options"] = {
            "master_path": str(args.master.resolve()),
            "max_timing_error_s": scenario["time_step_s"] + scenario["output_step_s"],
        }
        scenario = prepare_timed_scenario(
            scenario["project"], scenario, workspace_root=directory
        )
        (folder / "scenario.json").write_text(
            json.dumps(scenario, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {"project": prepared["project"], "scenarios": 11, "model_accepted": False}
        )
    )


if __name__ == "__main__":
    main()
