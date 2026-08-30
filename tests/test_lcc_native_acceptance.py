from __future__ import annotations

import copy
import hashlib
import json

import pytest

from pscad_mcp.core.backend.base import BackendError

COMMIT = "a" * 40
HASH = "b" * 64
PREFLIGHT_SNAPSHOT = {"status": "PASS", "checks": {"repository": "PASS"}}
PREFLIGHT_HASH = hashlib.sha256(
    json.dumps(
        PREFLIGHT_SNAPSHOT,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
).hexdigest()
SUCCESS_HISTORY = [
    "validated",
    "staging_created",
    "compiled",
    "simulated",
    "acceptance_passed",
    "published",
]


def valid_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": "native-run-1",
        "scope": "lcc.blank_native",
        "builder_path": "lcc.blank_native",
        "kind": "licensed_simulation",
        "capability_state": "simulated",
        "commit": COMMIT,
        "generated_at_utc": "2026-08-30T01:00:00Z",
        "status": "PASS",
        "repository": {
            "branch": "codex/lcc-wp1a",
            "commit": COMMIT,
            "clean": True,
        },
        "preflight": {
            "status": "PASS",
            "sha256": PREFLIGHT_HASH,
            "snapshot": PREFLIGHT_SNAPSHOT,
        },
        "sources": {
            "template": {
                "path": "D:/official.pscx",
                "before": HASH,
                "after": HASH,
            },
            "master": {
                "path": "C:/PSCAD46/master.pslx",
                "before": HASH,
                "after": HASH,
            },
            "registry": {
                "path": "D:/repo/master-bindings.json",
                "file_sha256": HASH,
                "registry_sha256": "c" * 64,
            },
            "asset_manifest": {"path": "D:/repo/manifest.json", "sha256": HASH},
        },
        "build": {
            "project_name": "WP1A_NATIVE_LCC",
            "workspace": "D:/PSCAD-Workspace/lcc-wp1a/run-1",
            "build_id": "build-1",
            "plan_hash": HASH,
            "journal_path": "D:/run/journal.json",
            "journal_sha256": HASH,
            "history": SUCCESS_HISTORY,
            "terminal_state": "published",
        },
        "artifacts": {
            "project": {"path": "D:/run/case.pscx", "sha256": HASH},
            "library": {"path": "D:/run/cigre_lcc_v1.pslx", "sha256": HASH},
            "scenario": {
                "path": "D:/run/case_scenario_source.pscx",
                "sha256": HASH,
            },
            "selected_output": {"path": "D:/run/case_01.out", "sha256": HASH},
            "output_parts": [{"path": "D:/run/case_01.out", "sha256": HASH}],
            "output_metadata": [],
        },
        "acceptance": {
            "verdict": "PASS",
            "checks": {
                "disturbance": True,
                "failure_indication": True,
                "bounded_dc_response": True,
                "recovered": True,
            },
            "evidence": {
                "fault_time_s": 0.8,
                "fault_duration_s": 0.1,
                "current_limit_pu": 3.0,
                "dc_current_peak_pu": 2.5,
                "recovery_window_s": 0.5,
                "channels": {
                    "fault_active": {
                        "path": "Fault/LCC Fault Active",
                        "units": "state",
                        "samples": 5,
                        "domain_start_s": 0.0,
                        "domain_end_s": 2.0,
                    },
                    "dc_current": {
                        "path": "Inverter/DC Current",
                        "units": "pu",
                        "samples": 5,
                        "domain_start_s": 0.0,
                        "domain_end_s": 2.0,
                    },
                    "failure_indicator": {
                        "path": "Inverter/Gamma",
                        "units": "deg",
                        "samples": 5,
                        "domain_start_s": 0.0,
                        "domain_end_s": 2.0,
                    },
                },
            },
        },
        "runtime": {
            "backend": "legacy",
            "version": "4.6.2",
            "x64": True,
            "licensed": True,
            "managed_pid": 1234,
            "quit_error": None,
            "remaining_processes": [],
        },
        "explicit_exclusions": [
            "fixed_autonomous",
            "parametric_lcc",
            "independent_golden",
            "final_accepted",
        ],
        "failure": None,
    }


def subject():
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        validate_native_lcc_acceptance_report,
    )

    return validate_native_lcc_acceptance_report


def test_valid_pass_report_is_normalized_without_mutation():
    payload = valid_report()
    original = copy.deepcopy(payload)
    assert subject()(payload)["status"] == "PASS"
    assert payload == original


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra=True),
        lambda value: value["build"].update(extra=True),
        lambda value: value["acceptance"]["checks"].pop("recovered"),
        lambda value: value["artifacts"].update(project=None),
        lambda value: value.update(capability_state="accepted"),
        lambda value: value["runtime"].update(quit_error="quit failed"),
        lambda value: value["build"].update(
            history=list(reversed(SUCCESS_HISTORY))
        ),
    ],
)
def test_pass_report_rejects_unknown_missing_or_false_claims(mutation):
    payload = valid_report()
    mutation(payload)
    with pytest.raises(BackendError) as failure:
        subject()(payload)
    assert failure.value.code == "LCC_NATIVE_REPORT_INVALID"


def test_fail_report_requires_failure_and_rejects_pass_artifacts():
    payload = valid_report()
    payload["status"] = "FAIL"
    payload["capability_state"] = "failed"
    payload["failure"] = {
        "stage": "compile",
        "code": "LCC_BUILD_FAILED",
        "message": "failed",
    }
    payload["build"]["terminal_state"] = "failed"
    payload["build"]["history"] = ["validated", "failed"]
    payload["artifacts"] = {
        "project": None,
        "library": None,
        "scenario": None,
        "selected_output": None,
        "output_parts": [],
        "output_metadata": [],
    }
    payload["acceptance"] = None

    assert subject()(payload)["failure"]["stage"] == "compile"


def test_native_promotion_revalidates_domain_report_before_generic_promotion(
    tmp_path,
):
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        promote_native_lcc_report,
    )

    payload = valid_report()
    payload["acceptance"]["checks"]["recovered"] = False
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    called = []

    with pytest.raises(BackendError):
        promote_native_lcc_report(
            tmp_path / "baseline.json",
            report,
            promotion_action=lambda *args, **kwargs: called.append((args, kwargs)),
        )

    assert called == []


def test_native_promotion_pins_validated_report_hash(monkeypatch, tmp_path):
    from pscad_mcp.hvdc.builders.lcc import native_acceptance

    report = tmp_path / "report.json"
    report.write_text(json.dumps(valid_report(), sort_keys=True), encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        native_acceptance,
        "_verify_native_report_files",
        lambda payload: None,
    )

    native_acceptance.promote_native_lcc_report(
        tmp_path / "baseline.json",
        report,
        promotion_action=lambda *args, **kwargs: calls.append((args, kwargs)) or {},
    )

    assert calls[0][1]["expected_report_sha256"] == hashlib.sha256(
        report.read_bytes()
    ).hexdigest()
