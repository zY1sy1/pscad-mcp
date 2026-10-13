"""Opt-in independent verification of a durable three-scenario licensed sweep.

PSCAD_MCP_SWEEP_ACCEPTANCE_SPEC points to a JSON object containing `spec` and
`expected_states`. At least three scenarios, a middle deliberate failure and
a later success are required. Source must be inside PSCAD_MCP_WORKSPACE.
"""

import asyncio
import json
import math
import os
from pathlib import Path

import pytest

from pscad_mcp.tools.sweep_tools import _new_session
from pscad_mcp.workflows.sweep.service import SweepService
from pscad_mcp.workflows.sweep.store import atomic_json, file_hash, tree_inventory


@pytest.mark.skipif(
    os.getenv("PSCAD_MCP_ACCEPTANCE") != "1",
    reason="PSCAD_MCP_ACCEPTANCE=1 is required for licensed sweep acceptance.",
)
def test_licensed_parameter_sweep():
    supplied = os.getenv("PSCAD_MCP_SWEEP_ACCEPTANCE_SPEC")
    assert supplied and Path(supplied).is_absolute(), (
        "An absolute reviewed PSCAD_MCP_SWEEP_ACCEPTANCE_SPEC is required."
    )
    contract = json.loads(Path(supplied).read_text(encoding="utf-8"))
    from pscad_mcp.core.connection_manager import pscad_manager
    from pscad_mcp.core.path_policy import PathPolicy

    root = os.getenv("PSCAD_MCP_WORKSPACE")
    assert root and Path(root).is_absolute(), (
        "An absolute independent PSCAD_MCP_WORKSPACE is required."
    )
    policy = PathPolicy(root)
    pscad_manager.service.path_policy = policy
    service = SweepService(policy, session_factory=_new_session)
    spec = contract["spec"]
    plan = service.plan(spec)
    source = Path(plan["spec"]["source_root"])
    before = tree_inventory(source)
    expected = contract["expected_states"]
    ordered_names = [item["name"] for item in spec["scenarios"]]
    assert len(ordered_names) >= 3 and set(expected) == set(ordered_names)
    failures = [i for i, name in enumerate(ordered_names) if expected[name] == "failed"]
    assert failures and any(
        expected[name] == "succeeded" for name in ordered_names[max(failures) + 1 :]
    )
    assert expected[spec["baseline_scenario"]] == "succeeded"
    cid = service.create(spec, expected_plan_hash=plan["plan_hash"], confirm=True)[
        "campaign_id"
    ]

    async def execute():
        try:
            await service.start(cid, confirm=True)
            await service.wait(
                cid,
                timeout=sum(
                    plan["spec"]["run_timeout_seconds"] + 360 for _ in ordered_names
                ),
            )
        finally:
            await service.shutdown(timeout_s=30)

    asyncio.run(execute())
    status = service.status(cid, include_report=True)
    evidence = service.store.campaign_path(cid) / "licensed-acceptance.json"
    checks = []

    def check(name, condition):
        checks.append({"name": name, "passed": bool(condition)})

    check("source_immutable", tree_inventory(source) == before)
    check(
        "scenario_states",
        {s["name"]: s["state"] for s in status["scenarios"]} == expected,
    )
    check(
        "finished_with_expected_failure", status["state"] == "completed_with_failures"
    )
    check("no_active_attempt", status["active_attempt"] is None)
    for scenario in status["report"]["scenarios"]:
        check(
            f"{scenario['name']}:owned_cleanup",
            scenario.get("cleanup", {}).get("session_absent")
            and scenario.get("cleanup", {}).get("parameters_restored"),
        )
        check(
            f"{scenario['name']}:process_absent",
            not service.process_alive(scenario.get("owned_session")),
        )
        if scenario["state"] != "succeeded":
            continue
        for output in scenario["outputs"]:
            primary = next(
                Path(a["path"])
                for a in scenario["artifacts"]
                if Path(a["path"]).name == Path(output["path"]).name
            )
            assert primary.suffix.casefold() == ".out", (
                "This independent acceptance calculator currently requires OUT/INF."
            )
            # Independently read every raw row; do not call the production sweep reader.
            metadata = next(
                Path(a["path"])
                for a in scenario["artifacts"]
                if Path(a["path"]).suffix.casefold() == ".inf"
                and Path(a["path"]).parent == primary.parent
            )
            import re

            entries = []
            for line in metadata.read_text(encoding="utf-8").splitlines():
                if not re.match(r"\s*PGB\(\d+\)", line):
                    continue
                fields = dict(re.findall(r'(\w+)="([^"]*)"', line))
                entries.append(f"{fields['Group']}/{fields['Desc']}".strip("/"))
            for channel in output["channels"]:
                index = entries.index(channel["path"])
                part = metadata.with_name(f"{metadata.stem}_{index // 10 + 1:02d}.out")
                lines = [line for line in part.read_text().splitlines() if line.strip()]
                # The independent calculator handles PSCAD's optional title
                # before converting every data row with ordinary float().
                try:
                    float(lines[0].split()[0])
                except ValueError:
                    lines = lines[1:]
                rows = [list(map(float, line.split())) for line in lines]
                n = min(len(rows), spec.get("max_samples", 10000))
                indices = (
                    [0]
                    if n == 1
                    else [i * (len(rows) - 1) // (n - 1) for i in range(n)]
                )
                values = [rows[i][index % 10 + 1] for i in indices]
                independent = {
                    "count": n,
                    "min": min(values),
                    "max": max(values),
                    "mean": math.fsum(values) / n,
                    "first": values[0],
                    "last": values[-1],
                    "rms": math.sqrt(math.fsum(v * v for v in values) / n),
                    "peak_abs": max(map(abs, values)),
                }
                for metric, value in independent.items():
                    check(
                        f"{scenario['name']}:{channel['path']}:{metric}",
                        math.isclose(
                            value,
                            channel["statistics"][metric],
                            rel_tol=1e-12,
                            abs_tol=1e-12,
                        ),
                    )
    report = {
        "status": "PASS" if all(item["passed"] for item in checks) else "FAIL",
        "workflow_accepted": all(item["passed"] for item in checks),
        "model_accepted": False,
        "scope": "sweep_serial_failure_continuation_and_out_statistics",
        "campaign_id": cid,
        "request_sha256": file_hash(Path(supplied)),
        "source_hash": plan["source_hash"],
        "checks": checks,
        "report_path": str(evidence),
    }
    atomic_json(evidence, report)
    print(f"SWEEP_ACCEPTANCE_REPORT={evidence}", flush=True)
    assert report["status"] == "PASS", json.dumps(checks)
