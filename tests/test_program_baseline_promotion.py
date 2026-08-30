from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from tests.test_lcc_mmc_program_baseline import valid_baseline

OLD_COMMIT = "dadd739e2abc14dcc7de73149da7fd7f0c0ca763"
NEW_COMMIT = "a" * 40
EXCLUSIONS = ("fixed_autonomous", "parametric_lcc", "independent_golden", "final_accepted")


def baseline_with_blank_scope():
    baseline = valid_baseline()
    baseline["scopes"].append(
        {
            "scope": "lcc.blank_native",
            "builder_path": "lcc.blank_native",
            "owner_work_package": "WP1",
            "capability_state": "simulated",
            "licensed_status": "NOT_RUN_ON_CURRENT_COMMIT",
            "evidence_run_id": None,
            "explicit_exclusions": ["current_commit_acceptance"],
        }
    )
    return baseline


def write_report(path: Path, status="PASS", commit=NEW_COMMIT):
    payload = {
        "schema_version": 1,
        "run_id": "native-run-1",
        "scope": "lcc.blank_native",
        "builder_path": "lcc.blank_native",
        "kind": "licensed_simulation",
        "capability_state": "simulated" if status == "PASS" else "failed",
        "commit": commit,
        "generated_at_utc": "2026-08-30T01:00:00Z",
        "status": status,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def subject():
    from pscad_mcp.acceptance.promotion import advance_and_apply_scope_report

    return advance_and_apply_scope_report


def test_promotion_advances_commit_invalidates_old_pass_and_updates_only_target(tmp_path):
    baseline = baseline_with_blank_scope()
    original = copy.deepcopy(baseline)
    report = write_report(tmp_path / "report.json")

    updated = subject()(  # type: ignore[call-arg]
        baseline,
        report,
        repository_commit=NEW_COMMIT,
        repository_branch="codex/lcc-wp1a-native-acceptance",
        expected_scope="lcc.blank_native",
        owner_work_package="WP1",
        explicit_exclusions=EXCLUSIONS,
    )

    assert baseline == original
    assert updated["repository"]["base_commit"] == NEW_COMMIT
    scopes = {item["scope"]: item for item in updated["scopes"]}
    assert scopes["lcc.master_bindings"]["licensed_status"] == "NOT_RUN_ON_CURRENT_COMMIT"
    assert scopes["lcc.master_bindings"]["evidence_run_id"] is None
    assert scopes["lcc.blank_native"]["licensed_status"] == "PASS"
    assert scopes["lcc.blank_native"]["capability_state"] == "simulated"
    assert scopes["lcc.blank_native"]["explicit_exclusions"] == list(EXCLUSIONS)


@pytest.mark.parametrize(
    ("status", "commit", "scope", "reason"),
    [
        ("FAIL", NEW_COMMIT, "lcc.blank_native", "report_not_pass"),
        ("PASS", OLD_COMMIT, "lcc.blank_native", "commit_mismatch"),
        ("PASS", NEW_COMMIT, "lcc.parametric", "scope_mismatch"),
    ],
)
def test_promotion_rejects_invalid_selected_report(tmp_path, status, commit, scope, reason):
    baseline = baseline_with_blank_scope()
    report = write_report(tmp_path / "report.json", status=status, commit=commit)
    if scope != "lcc.blank_native":
        payload = json.loads(report.read_text(encoding="utf-8"))
        payload["scope"] = scope
        payload["builder_path"] = "lcc.parametric"
        report.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BackendError) as failure:
        subject()(
            baseline,
            report,
            repository_commit=NEW_COMMIT,
            repository_branch="codex/lcc-wp1a-native-acceptance",
            expected_scope="lcc.blank_native",
            owner_work_package="WP1",
            explicit_exclusions=EXCLUSIONS,
        )

    assert failure.value.code == "PROGRAM_PROMOTION_REJECTED"
    assert failure.value.details["reason"] == reason


def test_promote_program_report_requires_clean_exact_checkout(tmp_path):
    from pscad_mcp.acceptance.promotion import promote_program_report

    baseline_path = tmp_path / "docs" / "acceptance" / "baseline.json"
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_text(json.dumps(baseline_with_blank_scope()), encoding="utf-8")
    report = write_report(tmp_path / "report.json")

    def git_reader(_root):
        return {"commit": NEW_COMMIT, "branch": "codex/lcc-wp1a-native-acceptance", "clean": False}

    with pytest.raises(BackendError) as failure:
        promote_program_report(
            baseline_path,
            report,
            expected_scope="lcc.blank_native",
            owner_work_package="WP1",
            explicit_exclusions=EXCLUSIONS,
            git_reader=git_reader,
        )
    assert failure.value.details["reason"] == "worktree_not_clean"


def test_promotion_rejects_report_hash_selected_before_domain_validation(tmp_path):
    baseline = baseline_with_blank_scope()
    report = write_report(tmp_path / "report.json", status="FAIL")

    with pytest.raises(BackendError) as failure:
        subject()(
            baseline,
            report,
            repository_commit=NEW_COMMIT,
            repository_branch="codex/lcc-wp1a-native-acceptance",
            expected_scope="lcc.blank_native",
            owner_work_package="WP1",
            explicit_exclusions=EXCLUSIONS,
            expected_report_sha256="f" * 64,
        )
    assert failure.value.details["reason"] == "report_hash_mismatch"
