"""CLI for evaluating fixed LCC dynamic evidence exported from PSCAD."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from .dynamic_acceptance import (
    FAIL,
    INCOMPLETE,
    PASS,
    evaluate_fixed_lcc_dynamic_samples,
    validate_dynamic_lcc_acceptance_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--samples", type=Path, required=True)
    evaluate.add_argument("--golden", type=Path, required=True)
    evaluate.add_argument("--contract", type=Path, required=True)
    evaluate.add_argument("--report", type=Path, required=True)
    evaluate.add_argument("--commit", required=True)
    evaluate.add_argument("--branch", required=True)
    evaluate.add_argument("--project-name", default="WP1C_FIXED_LCC")
    evaluate.add_argument("--event-kind", default="inverter_ac_disturbance")
    evaluate.add_argument("--event-time", type=float, required=True)
    evaluate.add_argument("--event-duration", type=float, required=True)
    evaluate.add_argument("--recovery-window", type=float, required=True)
    return parser


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, allow_nan=False, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _required_channels(contract: Mapping[str, Any]) -> list[str]:
    value = contract.get("required_channels", ())
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ["Main/VDC_RECT"]
    result = [str(item) for item in value]
    return result or ["Main/VDC_RECT"]


def _report(
    arguments: argparse.Namespace,
    *,
    status: str,
    contract: Mapping[str, Any],
    golden: Mapping[str, Any],
    result: Mapping[str, Any] | None,
    failure: BaseException | None,
) -> dict[str, Any]:
    dynamic_result = result.get("dynamic", {}) if isinstance(result, Mapping) else {}
    physical_result = result.get("physical", {}) if isinstance(result, Mapping) else {}
    physical_verdict = (
        physical_result.get("verdict", INCOMPLETE)
        if isinstance(physical_result, Mapping)
        else INCOMPLETE
    )
    report = {
        "schema_version": 1,
        "run_id": arguments.report.parent.name,
        "scope": "lcc.fixed_autonomous",
        "builder_path": "lcc.fixed_autonomous",
        "kind": "licensed_acceptance",
        "capability_state": "simulated",
        "commit": arguments.commit,
        "generated_at_utc": "1970-01-01T00:00:00Z",
        "status": status,
        "repository": {
            "branch": arguments.branch,
            "commit": arguments.commit,
            "clean": True,
        },
        "dynamic": {
            "event": {
                "kind": arguments.event_kind,
                "time_s": arguments.event_time,
                "duration_s": arguments.event_duration,
            },
            "recovery": {
                "observed": bool(dynamic_result.get("checks", {}).get("recovered", False)),
                "window_s": arguments.recovery_window,
            },
            "required_channels": _required_channels(contract),
            "physical": {
                "verdict": physical_verdict,
                "event_checks": dynamic_result.get("checks", {}),
                "waveform_checks": physical_result.get("physical_checks", [])
                if isinstance(physical_result, Mapping)
                else [],
                "missing_channels": result.get("missing_channels", []) if isinstance(result, Mapping) else [],
            },
        },
        "golden": dict(golden),
        "explicit_exclusions": ["independent_golden", "final_accepted"],
        "failure": (
            {
                "stage": "input",
                "code": failure.code if isinstance(failure, BackendError) else type(failure).__name__,
                "message": str(failure)[:1024] or type(failure).__name__,
            }
            if failure is not None
            else None
        ),
    }
    return validate_dynamic_lcc_acceptance_report(report)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.action != "evaluate":
        raise SystemExit(f"Unsupported action: {arguments.action}")
    result: dict[str, Any] | None = None
    failure: BaseException | None = None
    contract: Mapping[str, Any] = {}
    golden: Mapping[str, Any] = {}
    try:
        samples = _load_json(arguments.samples)
        loaded_golden = _load_json(arguments.golden)
        loaded_contract = _load_json(arguments.contract)
        if not isinstance(loaded_golden, Mapping) or not isinstance(loaded_contract, Mapping):
            raise BackendError("LCC_DYNAMIC_INPUT_INVALID", "golden and contract must be objects.", "hvdc", "evaluate_fixed_lcc_dynamic")
        golden = loaded_golden
        contract = loaded_contract
        result = evaluate_fixed_lcc_dynamic_samples(samples, golden, contract)
        status = str(result["verdict"])
    except BaseException as error:  # noqa: BLE001 - persist every input failure
        failure = error
        status = FAIL
    report = _report(
        arguments,
        status=status,
        contract=contract,
        golden=golden,
        result=result,
        failure=failure,
    )
    _atomic_write(arguments.report, report)
    print(f"FIXED_LCC_DYNAMIC_ACCEPTANCE={status}")
    print(f"FIXED_LCC_DYNAMIC_REPORT={arguments.report.resolve()}")
    return 0 if status == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
