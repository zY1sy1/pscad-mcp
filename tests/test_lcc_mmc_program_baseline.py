from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError

ROOT = Path(__file__).parents[1]
PROGRAM_BASELINE = ROOT / "docs" / "acceptance" / "lcc-mmc-program-baseline.json"


def valid_baseline() -> dict[str, object]:
    return {
        "schema_version": 1,
        "baseline_id": "lcc-mmc-program-2026-08-30",
        "generated_at_utc": "2026-08-30T00:00:00Z",
        "repository": {
            "base_commit": "dadd739e2abc14dcc7de73149da7fd7f0c0ca763",
            "branch": "main",
            "worktree_clean": True,
        },
        "environment": {
            "backend": "legacy",
            "pscad_version": "4.6.2",
            "x64": True,
            "automation_module": "mhrc.automation",
            "master_path": "C:/Program Files (x86)/PSCAD46/master.pslx",
            "master_sha256": "0" * 64,
            "compiler": {
                "identity": "gfortran",
                "configuration_path": (
                    "C:/Program Files (x86)/PSCAD46/fortran_compilers.xml"
                ),
                "configuration_sha256": "1" * 64,
                "executable_path": (
                    "C:/Program Files (x86)/GFortran/4.6/bin/gfortran.exe"
                ),
                "executable_sha256": "3" * 64,
            },
        },
        "sources": [],
        "assets": [],
        "reports": [
            {
                "run_id": "master-binding-20260829-173320-618412",
                "scope": "lcc.master_bindings",
                "builder_path": "lcc.master_binding_registry",
                "kind": "licensed_compile",
                "capability_state": "compiled",
                "status": "PASS",
                "commit": "dadd739e2abc14dcc7de73149da7fd7f0c0ca763",
                "generated_at_utc": "2026-08-29T17:33:20Z",
                "path": (
                    "D:/PSCAD-Workspace/master-binding-acceptance/report.json"
                ),
                "sha256": "2" * 64,
                "availability": "verified_local",
            }
        ],
        "scopes": [
            {
                "scope": "lcc.master_bindings",
                "builder_path": "lcc.master_binding_registry",
                "owner_work_package": "WP1",
                "capability_state": "compiled",
                "licensed_status": "PASS",
                "evidence_run_id": "master-binding-20260829-173320-618412",
                "explicit_exclusions": ["full_lcc_waveform_acceptance"],
            }
        ],
    }


def write_transition_report(tmp_path: Path, **overrides: object) -> Path:
    report = copy.deepcopy(valid_baseline()["reports"][0])
    payload = {
        key: value
        for key, value in report.items()
        if key not in {"path", "sha256", "availability"}
    }
    payload.update(
        {
            "schema_version": 1,
            "run_id": "transition-run",
            "generated_at_utc": "2026-08-30T00:00:00Z",
            **overrides,
        }
    )
    path = tmp_path / f"{payload['run_id']}.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def subject():
    from pscad_mcp.acceptance.baseline import validate_program_baseline

    return validate_program_baseline


def test_valid_baseline_is_canonical_and_does_not_mutate_input():
    payload = valid_baseline()
    original = copy.deepcopy(payload)

    result = subject()(payload)

    assert payload == original
    assert result["schema_version"] == 1
    assert result["scopes"][0]["scope"] == "lcc.master_bindings"


@pytest.mark.parametrize(
    ("mutation", "field"),
    [
        (lambda value: value.update(extra=True), "baseline"),
        (lambda value: value["repository"].update(extra=True), "repository"),
        (lambda value: value["environment"].update(extra=True), "environment"),
        (lambda value: value["reports"][0].update(extra=True), "reports[0]"),
        (lambda value: value["scopes"][0].update(extra=True), "scopes[0]"),
    ],
)
def test_unknown_fields_are_rejected(mutation, field):
    payload = valid_baseline()
    mutation(payload)

    with pytest.raises(BackendError) as failure:
        subject()(payload)

    assert failure.value.code == "PROGRAM_BASELINE_INVALID"
    assert failure.value.details["field"] == field


def test_pass_requires_same_scope_same_commit_durable_report():
    payload = valid_baseline()
    payload["reports"][0]["commit"] = "f" * 40

    with pytest.raises(BackendError) as failure:
        subject()(payload)

    assert failure.value.code == "PROGRAM_BASELINE_INVALID"
    assert failure.value.details["reason"] == "pass_commit_mismatch"


def test_pass_rejects_non_durable_report_availability():
    payload = valid_baseline()
    payload["reports"][0]["availability"] = "historical_commit_unknown"

    with pytest.raises(BackendError) as failure:
        subject()(payload)

    assert failure.value.details["reason"] == "pass_evidence_not_durable"


def test_compile_report_cannot_claim_accepted_capability():
    payload = valid_baseline()
    payload["reports"][0]["capability_state"] = "accepted"
    payload["scopes"][0]["capability_state"] = "accepted"

    with pytest.raises(BackendError) as failure:
        subject()(payload)

    assert failure.value.details["reason"] == "kind_state_mismatch"


@pytest.mark.parametrize(
    "field",
    ["baseline", "report"],
)
def test_generated_timestamps_must_be_utc_rfc3339(field):
    payload = valid_baseline()
    if field == "baseline":
        payload["generated_at_utc"] = "yesterday"
    else:
        payload["reports"][0]["generated_at_utc"] = "2026-08-30 00:00:00"

    with pytest.raises(BackendError) as failure:
        subject()(payload)

    assert failure.value.details["reason"] == "invalid_timestamp"


def test_duplicate_scope_and_run_id_are_rejected():
    payload = valid_baseline()
    payload["reports"].append(copy.deepcopy(payload["reports"][0]))

    with pytest.raises(BackendError) as failure:
        subject()(payload)

    assert failure.value.details["reason"] == "duplicate_run_id"


def transition_subject():
    from pscad_mcp.acceptance.baseline import apply_scope_report

    return apply_scope_report


def test_report_updates_only_its_owned_scope(tmp_path):
    baseline = valid_baseline()
    report = write_transition_report(
        tmp_path,
        run_id="master-binding-20260830-new",
        status="INCOMPLETE_ANALYSIS",
    )

    updated = transition_subject()(
        baseline,
        report,
        owner_work_package="WP1",
    )

    assert updated["scopes"][0]["licensed_status"] == "INCOMPLETE_ANALYSIS"
    assert baseline["scopes"][0]["licensed_status"] == "PASS"


def test_cross_scope_or_wrong_owner_transition_is_rejected(tmp_path):
    baseline = valid_baseline()
    cross_scope = write_transition_report(
        tmp_path,
        run_id="cross-scope",
        scope="mmc.parametric",
        builder_path="mmc.parametric_orchestrator",
    )

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, cross_scope, owner_work_package="WP1")

    assert failure.value.code == "PROGRAM_SCOPE_CONFLICT"

    wrong_owner = write_transition_report(tmp_path, run_id="wrong-owner")
    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, wrong_owner, owner_work_package="WP2")

    assert failure.value.details["reason"] == "scope_owner_mismatch"


def test_cross_builder_transition_is_rejected(tmp_path):
    baseline = valid_baseline()
    report = write_transition_report(
        tmp_path,
        run_id="cross-builder",
        builder_path="lcc.parametric",
    )

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, report, owner_work_package="WP1")

    assert failure.value.details["reason"] == "builder_path_mismatch"


def test_historical_commit_never_updates_current_scope(tmp_path):
    baseline = valid_baseline()
    report = write_transition_report(
        tmp_path,
        run_id="historical-commit",
        commit="f" * 40,
    )

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, report, owner_work_package="WP1")

    assert failure.value.details["reason"] == "historical_commit"


def test_run_id_cannot_be_reused_with_different_evidence(tmp_path):
    baseline = valid_baseline()
    report = write_transition_report(
        tmp_path,
        run_id="master-binding-20260829-173320-618412",
    )

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, report, owner_work_package="WP1")

    assert failure.value.details["reason"] == "run_id_reuse"


def test_compile_pass_does_not_promote_scope_to_accepted(tmp_path):
    baseline = valid_baseline()
    report = write_transition_report(tmp_path, run_id="compile-run-2")

    updated = transition_subject()(
        baseline,
        report,
        owner_work_package="WP1",
    )

    assert updated["scopes"][0]["licensed_status"] == "PASS"
    assert updated["scopes"][0]["capability_state"] == "compiled"


def test_transition_rejects_unindexed_fabricated_report(tmp_path):
    baseline = valid_baseline()
    report = tmp_path / "does-not-exist.json"

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, report, owner_work_package="WP1")

    assert failure.value.code == "PROGRAM_EVIDENCE_INVALID"
    assert failure.value.details["reason"] == "not_regular_file"


def test_checked_in_program_baseline_is_valid_and_scoped():
    payload = json.loads(PROGRAM_BASELINE.read_text(encoding="utf-8"))

    result = subject()(payload)
    scopes = {item["scope"]: item for item in result["scopes"]}

    assert set(scopes) == {
        "lcc.master_bindings",
        "lcc.blank_native",
        "lcc.fixed_autonomous",
        "lcc.parametric",
        "mmc.blank_native_full_bridge",
        "mmc.detailed_pwm_full_bridge",
        "mmc.avm_full_bridge",
        "mmc.avm_half_bridge",
        "mmc.parametric",
    }
    assert scopes["lcc.master_bindings"]["licensed_status"] == (
        "NOT_RUN_ON_CURRENT_COMMIT"
    )
    native = scopes["lcc.blank_native"]
    assert native["capability_state"] == "simulated"
    assert native["licensed_status"] == "PASS"
    assert isinstance(native["evidence_run_id"], str)
    reports = {item["run_id"]: item for item in result["reports"]}
    evidence = reports[native["evidence_run_id"]]
    assert evidence["scope"] == "lcc.blank_native"
    assert evidence["builder_path"] == "lcc.blank_native"
    assert evidence["kind"] == "licensed_simulation"
    assert evidence["status"] == "PASS"
    assert evidence["commit"] == result["repository"]["base_commit"]
    assert scopes["mmc.blank_native_full_bridge"]["licensed_status"] == (
        "NOT_RUN_ON_CURRENT_COMMIT"
    )
    assert scopes["mmc.parametric"]["licensed_status"] == "INCOMPLETE_ANALYSIS"
    assert all(
        item["evidence_run_id"] is None
        for name, item in scopes.items()
        if name != "lcc.blank_native"
    )


def test_program_baseline_does_not_replace_topology_status_manifest():
    topology = json.loads(
        (ROOT / "docs" / "acceptance-status.json").read_text(encoding="utf-8")
    )
    program = json.loads(PROGRAM_BASELINE.read_text(encoding="utf-8"))

    assert {item["scope"] for item in topology["scopes"]}.isdisjoint(
        {item["scope"] for item in program["scopes"]}
    )


def test_program_baseline_marks_non_durable_runs_as_historical_sources():
    program = json.loads(PROGRAM_BASELINE.read_text(encoding="utf-8"))
    sources = {item["source_id"]: item for item in program["sources"]}

    assert sources["history.master_binding_compile"]["availability"] == (
        "verified_local_historical_commit_unknown"
    )
    assert sources["history.blank_lcc_official_template"]["availability"] == (
        "verified_local_historical_commit_unknown"
    )
    assert sources["history.blank_mmc_official_template"]["availability"] == (
        "verified_local_historical_commit_unknown"
    )
    assert sources["history.mmc_parametric_orchestrator"]["availability"] == (
        "verified_local_historical_commit"
    )
