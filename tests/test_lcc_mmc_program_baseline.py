from __future__ import annotations

import copy

import pytest

from pscad_mcp.core.backend.base import BackendError


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


def test_duplicate_scope_and_run_id_are_rejected():
    payload = valid_baseline()
    payload["reports"].append(copy.deepcopy(payload["reports"][0]))

    with pytest.raises(BackendError) as failure:
        subject()(payload)

    assert failure.value.details["reason"] == "duplicate_run_id"


def transition_subject():
    from pscad_mcp.acceptance.baseline import apply_scope_report

    return apply_scope_report


def test_report_updates_only_its_owned_scope():
    baseline = valid_baseline()
    report = copy.deepcopy(baseline["reports"][0])
    report["run_id"] = "master-binding-20260830-new"
    report["sha256"] = "3" * 64
    report["status"] = "INCOMPLETE_ANALYSIS"

    updated = transition_subject()(
        baseline,
        report,
        owner_work_package="WP1",
    )

    assert updated["scopes"][0]["licensed_status"] == "INCOMPLETE_ANALYSIS"
    assert baseline["scopes"][0]["licensed_status"] == "PASS"


def test_cross_scope_or_wrong_owner_transition_is_rejected():
    baseline = valid_baseline()
    report = copy.deepcopy(baseline["reports"][0])
    report["scope"] = "mmc.parametric"

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, report, owner_work_package="WP1")

    assert failure.value.code == "PROGRAM_SCOPE_CONFLICT"

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, baseline["reports"][0], owner_work_package="WP2")

    assert failure.value.details["reason"] == "scope_owner_mismatch"


def test_cross_builder_transition_is_rejected():
    baseline = valid_baseline()
    report = copy.deepcopy(baseline["reports"][0])
    report["builder_path"] = "lcc.parametric"

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, report, owner_work_package="WP1")

    assert failure.value.details["reason"] == "builder_path_mismatch"


def test_historical_commit_never_updates_current_scope():
    baseline = valid_baseline()
    report = copy.deepcopy(baseline["reports"][0])
    report["commit"] = "f" * 40

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, report, owner_work_package="WP1")

    assert failure.value.details["reason"] == "historical_commit"


def test_run_id_cannot_be_reused_with_different_evidence():
    baseline = valid_baseline()
    report = copy.deepcopy(baseline["reports"][0])
    report["sha256"] = "f" * 64

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, report, owner_work_package="WP1")

    assert failure.value.details["reason"] == "run_id_reuse"


def test_compile_pass_does_not_promote_scope_to_accepted():
    baseline = valid_baseline()
    report = copy.deepcopy(baseline["reports"][0])
    report["run_id"] = "compile-run-2"
    report["sha256"] = "4" * 64

    updated = transition_subject()(
        baseline,
        report,
        owner_work_package="WP1",
    )

    assert updated["scopes"][0]["licensed_status"] == "PASS"
    assert updated["scopes"][0]["capability_state"] == "compiled"
