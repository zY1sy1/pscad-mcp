"""Offline integrity checks must never create a licensed acceptance verdict."""

import hashlib
import json

import pytest

from scripts.audit_acceptance_inventory import audit_inventory


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def inventory(tmp_path):
    report = tmp_path / "report.json"
    digest = write_json(report, {"status": "PASS", "commit": "a" * 40})
    manifest = tmp_path / "inventory.json"
    write_json(manifest, {"schema_version": 1, "scopes": [{
        "scope": "test_scope", "licensed_status": "PASS",
        "evidence": {"report_path": str(report), "sha256": digest, "commit": "a" * 40},
        "evidence_checks": [{"pointer": "/status", "equals": "PASS"}],
    }]})
    return manifest, report


def test_historical_integrity_does_not_become_current_acceptance(inventory):
    result = audit_inventory(inventory[0], checkout_commit="b" * 40)
    assert result["integrity_status"] == "VERIFIED"
    assert result["licensed_acceptance_run"] is False
    assert result["release_complete"] is False
    assert result["scopes"][0]["evidence_matches_checkout"] is False


@pytest.mark.parametrize("change", ["mutate", "missing", "wrong_verdict"])
def test_changed_missing_or_mislabelled_report_is_rejected(inventory, change):
    manifest, report = inventory
    if change == "missing":
        report.unlink()
    else:
        digest = write_json(report, {"status": "FAIL"})
        if change == "wrong_verdict":
            payload = json.loads(manifest.read_text())
            payload["scopes"][0]["evidence"]["sha256"] = digest
            write_json(manifest, payload)
    result = audit_inventory(manifest)
    assert result["integrity_status"] == "INVALID"
    assert result["scopes"][0]["errors"]


def test_missing_evidence_is_explicit_not_success(inventory):
    manifest, _ = inventory
    payload = json.loads(manifest.read_text())
    payload["scopes"][0]["evidence"] = {"report_path": None, "sha256": None, "commit": None}
    payload["scopes"][0]["licensed_status"] = "NOT_RUN_ON_INTEGRATED_COMMIT"
    write_json(manifest, payload)
    result = audit_inventory(manifest)
    assert result["integrity_status"] == "INCOMPLETE"
    assert result["scopes"][0]["integrity_status"] == "NO_DURABLE_REPORT"


def test_suite_child_and_accepted_artifact_hashes_are_checked(inventory, tmp_path):
    manifest, report = inventory
    child = tmp_path / "child.json"
    child_hash = write_json(child, {"status": "PASS"})
    model = tmp_path / "model.pscx"
    model.write_text("saved model")
    payload = json.loads(manifest.read_text())
    payload["scopes"][0]["evidence"]["sha256"] = write_json(report, {
        "status": "PASS",
        "reports": {"normal": {"path": str(child), "sha256": child_hash, "status": "PASS", "exit_code": 0}},
        "accepted_hashes": {str(model): hashlib.sha256(model.read_bytes()).hexdigest()},
    })
    write_json(manifest, payload)
    assert audit_inventory(manifest)["scopes"][0]["verified_files"] == 3
    model.write_text("modified model")
    assert audit_inventory(manifest)["integrity_status"] == "INVALID"


def test_pass_without_report_or_verdict_assertion_is_invalid(inventory):
    manifest, _ = inventory
    payload = json.loads(manifest.read_text())
    payload["scopes"][0].pop("evidence_checks")
    write_json(manifest, payload)
    assert audit_inventory(manifest)["integrity_status"] == "INVALID"
