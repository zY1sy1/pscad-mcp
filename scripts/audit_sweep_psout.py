"""Independent real-file PSOUT reader/metric audit, without launching PSCAD.

This scope verifies existing vendor binary evidence, not fresh PSOUT generation
or execution of a PSCAD 5.x parameter sweep. Units are explicit audit declarations.
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from pscad_mcp.core.pscad_adapter import PscadAdapter
from pscad_mcp.workflows.sweep.retained_metrics import enrich_metrics
from pscad_mcp.workflows.sweep.store import atomic_json, file_hash
from scripts.run_sweep_recovery_acceptance import independent_integral


def audit(fixture: Path, workspace: Path):
    if not fixture.is_absolute() or not workspace.is_absolute():
        raise ValueError("Absolute fixture and workspace paths are required.")
    root = workspace / (
        "psout-audit-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    )
    root.mkdir(parents=True, exist_ok=False)
    original_hash = file_hash(fixture)
    copied = root / "attempts" / "vendor-fixture" / "outputs" / "Cigre.psout"
    copied.parent.mkdir(parents=True)
    shutil.copyfile(fixture, copied)
    checks = []
    report = {
        "status": "FAIL",
        "psout_file_verified": False,
        "workflow_accepted": False,
        "model_accepted": False,
        "scope": "vendor_psout_fixture_reader_and_physical_metric_replay",
        "fresh_simulation": False,
        "unit_certification": False,
        "fixture": str(fixture),
        "fixture_sha256": original_hash,
        "checks": checks,
    }

    def check(name, condition):
        checks.append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)

    try:
        import mhi.psout

        check("fixture_copy_hash", file_hash(copied) == original_hash)
        report["tested_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
        ).strip()
        report["runner_sha256"] = file_hash(Path(__file__))
        adapter = PscadAdapter(None, pscad_module=False, environ={})
        payload = adapter._read_psout_sync(copied, 0, 10000, None, False)
        selectors = {
            "voltage": "Root/Main/Inverter/DC Volts/Record/PGB:Data",
            "current": "Root/Main/Inverter/DC Current/Record/PGB:Data",
        }
        direct = {}
        with mhi.psout.File(str(copied)) as record:
            run = record.run(0)
            for role, node in (("voltage", "DC Volts"), ("current", "DC Current")):
                native_path = f"Root/Main/Inverter/{node}/Record/1"
                trace = run.trace(record.call(native_path))
                values, domain = list(trace.data), list(trace.domain.data)
                matches = [
                    c for c in payload["channels"] if c["path"] == selectors[role]
                ]
                check(role + ":unique_selector", len(matches) == 1)
                channel = matches[0]
                check(
                    role + ":every_real_sample",
                    channel["values"] == values
                    and channel["domain"] == domain
                    and len(values) == 2001,
                )
                direct[role] = {
                    "native_call_path": native_path,
                    "domain": domain,
                    "values": values,
                }
        domain, voltage, current = (
            direct["voltage"]["domain"],
            direct["voltage"]["values"],
            direct["current"]["values"],
        )
        check("matching_native_time_domains", domain == direct["current"]["domain"])
        artifact = {
            "path": str(copied),
            "relative_path": copied.relative_to(root).as_posix(),
            "sha256": original_hash,
        }
        manifest = {
            "spec": {
                "max_samples": 10000,
                "outputs": [
                    {"path": "Cigre.psout", "channels": list(selectors.values())}
                ],
            }
        }
        candidate = {
            "baseline_scenario": "vendor_fixture",
            "scenarios": [
                {
                    "name": "vendor_fixture",
                    "state": "succeeded",
                    "artifacts": [artifact],
                }
            ],
        }
        window = [domain[0], domain[-1]]
        definitions = [
            {
                "name": "energy",
                "kind": "energy",
                "output_path": "Cigre.psout",
                "voltage_channel": selectors["voltage"],
                "current_channel": selectors["current"],
                "voltage_units": "kV",
                "current_units": "kA",
                "mode": "signed",
                "window": window,
            },
            {
                "name": "i2t",
                "kind": "i2t",
                "output_path": "Cigre.psout",
                "current_channel": selectors["current"],
                "current_units": "kA",
                "window": window,
            },
        ]
        enriched, _ = enrich_metrics(candidate, definitions, manifest, root)
        result = {m["name"]: m for m in enriched["scenarios"][0]["metrics"]}
        check(
            "energy_independent_simpson",
            math.isclose(
                result["energy"]["value"],
                independent_integral(domain, voltage, current) * 1e6,
                rel_tol=1e-12,
                abs_tol=1e-6,
            ),
        )
        check(
            "i2t_independent_simpson",
            math.isclose(
                result["i2t"]["value"],
                independent_integral(domain, current, current) * 1e6,
                rel_tol=1e-12,
                abs_tol=1e-6,
            ),
        )
        check(
            "unit_declarations_preserved",
            all(
                m["inputs"][role]["units_source"] == "request"
                for m in result.values()
                for role in m["inputs"]
            ),
        )
        check(
            "input_hashes_preserved",
            file_hash(copied) == original_hash and file_hash(fixture) == original_hash,
        )
        report.update(
            status="PASS",
            psout_file_verified=True,
            metrics=list(result.values()),
            selected_channels=selectors,
            reader_warnings=payload["warnings"],
            skipped_channels=payload["skipped_channels"],
            native_calls={k: v["native_call_path"] for k, v in direct.items()},
            copied_artifact=artifact,
        )
    except Exception as error:  # noqa: BLE001 - retain a failed independent audit.
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    atomic_json(root / "report.json", report)
    print("SWEEP_PSOUT_AUDIT_REPORT=" + str(root / "report.json"), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    return 0 if audit(args.fixture, args.workspace)["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
