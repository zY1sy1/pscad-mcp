from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError

COMMIT = "dadd739e2abc14dcc7de73149da7fd7f0c0ca763"


def descriptor(path: Path) -> dict[str, str]:
    return {"path": str(path)}


def write_report(
    path: Path,
    status: str = "PASS",
    *,
    commit: str | None = COMMIT,
) -> None:
    payload = {
        "schema_version": 1,
        "run_id": "run-1",
        "scope": "lcc.master_bindings",
        "builder_path": "lcc.master_binding_registry",
        "kind": "licensed_compile",
        "capability_state": "compiled",
        "generated_at_utc": "2026-08-29T17:33:20Z",
        "status": status,
    }
    if commit is not None:
        payload["commit"] = commit
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def subject():
    from pscad_mcp.acceptance.evidence import index_explicit_reports

    return index_explicit_reports


def test_explicit_report_is_hashed_and_indexed(tmp_path):
    report = tmp_path / "report.json"
    write_report(report)

    indexed = subject()([descriptor(report)])

    assert indexed[0]["status"] == "PASS"
    assert indexed[0]["builder_path"] == "lcc.master_binding_registry"
    assert indexed[0]["availability"] == "verified_local"
    assert len(indexed[0]["sha256"]) == 64


def test_missing_symlink_and_duplicate_run_ids_are_rejected(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(BackendError) as failure:
        subject()([descriptor(missing)])
    assert failure.value.code == "PROGRAM_EVIDENCE_INVALID"

    target = tmp_path / "target.json"
    write_report(target)
    alias = tmp_path / "alias.json"
    try:
        alias.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")
    with pytest.raises(BackendError):
        subject()([descriptor(alias)])

    with pytest.raises(BackendError) as failure:
        subject()([descriptor(target), descriptor(target)])
    assert failure.value.details["reason"] == "duplicate_run_id"


def test_report_without_self_attested_commit_is_historical_only(tmp_path):
    report = tmp_path / "report.json"
    write_report(report, commit=None)

    with pytest.raises(BackendError) as failure:
        subject()([descriptor(report)])

    assert failure.value.details["reason"] == "missing_durable_commit"


def test_descriptor_cannot_supply_or_override_report_commit(tmp_path):
    report = tmp_path / "report.json"
    write_report(report)
    value = descriptor(report)
    value["commit"] = COMMIT

    with pytest.raises(BackendError) as failure:
        subject()([value])

    assert failure.value.details["reason"] == "field_set"


def test_report_commit_must_be_full_lowercase_git_identity(tmp_path):
    report = tmp_path / "report.json"
    write_report(report, commit="dadd739")

    with pytest.raises(BackendError) as failure:
        subject()([descriptor(report)])

    assert failure.value.details["reason"] == "invalid_durable_commit"


def test_report_owned_scope_and_builder_path_must_match(tmp_path):
    report = tmp_path / "report.json"
    write_report(report)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["builder_path"] = "lcc.parametric"
    report.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BackendError) as failure:
        subject()([descriptor(report)])

    assert failure.value.details["reason"] == "builder_path_mismatch"


def test_shared_run_metadata_owns_scope_commit_and_builder_path():
    from pscad_mcp.acceptance.evidence import build_run_metadata

    metadata = build_run_metadata(
        run_id="run-2",
        scope="mmc.detailed_pwm_full_bridge",
        kind="licensed_simulation",
        capability_state="simulated",
        commit=COMMIT,
        generated_at_utc="2026-08-30T00:00:00Z",
    )

    assert metadata == {
        "schema_version": 1,
        "run_id": "run-2",
        "scope": "mmc.detailed_pwm_full_bridge",
        "builder_path": "mmc.detailed_pwm_full_bridge",
        "kind": "licensed_simulation",
        "capability_state": "simulated",
        "commit": COMMIT,
        "generated_at_utc": "2026-08-30T00:00:00Z",
    }


def test_shared_run_metadata_rejects_kind_state_mismatch():
    from pscad_mcp.acceptance.evidence import build_run_metadata

    with pytest.raises(BackendError) as failure:
        build_run_metadata(
            run_id="run-3",
            scope="mmc.detailed_pwm_full_bridge",
            kind="licensed_compile",
            capability_state="accepted",
            commit=COMMIT,
            generated_at_utc="2026-08-30T00:00:00Z",
        )

    assert failure.value.details["reason"] == "kind_state_mismatch"


def test_shared_run_metadata_rejects_non_utc_timestamp():
    from pscad_mcp.acceptance.evidence import build_run_metadata

    with pytest.raises(BackendError) as failure:
        build_run_metadata(
            run_id="run-4",
            scope="lcc.master_bindings",
            kind="licensed_compile",
            capability_state="compiled",
            commit=COMMIT,
            generated_at_utc="2026-08-30T08:00:00+08:00",
        )

    assert failure.value.details["reason"] == "invalid_timestamp"


def test_report_beneath_symlinked_parent_is_rejected(tmp_path):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    report = real_parent / "report.json"
    write_report(report)
    alias_parent = tmp_path / "alias"
    try:
        alias_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink creation unavailable: {error}")

    with pytest.raises(BackendError) as failure:
        subject()([descriptor(alias_parent / "report.json")])

    assert failure.value.details["reason"] == "reparse_path_component"


def test_report_replaced_during_parse_is_rejected(monkeypatch, tmp_path):
    from pscad_mcp.acceptance import evidence

    report = tmp_path / "report.json"
    write_report(report)
    original = report.read_bytes()
    original_loads = evidence.json.loads

    def replace_during_parse(value):
        payload = original_loads(value)
        replacement = dict(payload)
        replacement["status"] = "FAIL"
        report.write_text(json.dumps(replacement), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence.json, "loads", replace_during_parse)

    with pytest.raises(BackendError) as failure:
        subject()([descriptor(report)])

    assert failure.value.details["reason"] == "evidence_changed"
    assert hashlib.sha256(original).hexdigest() != hashlib.sha256(
        report.read_bytes()
    ).hexdigest()
