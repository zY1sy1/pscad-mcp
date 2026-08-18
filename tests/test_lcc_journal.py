import asyncio
import json
import os
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc import journal as journal_module
from pscad_mcp.hvdc.builders.lcc.journal import AtomicJournal, WorkspaceBuildLease


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_backend_code(call, code: str):
    with pytest.raises(BackendError) as raised:
        call()
    assert raised.value.code == code
    assert raised.value.backend == "hvdc"


def test_atomic_journal_writes_valid_json_through_same_directory_temp(tmp_path, monkeypatch):
    calls = []
    original = journal_module.tempfile.NamedTemporaryFile

    def recording_named_tempfile(*args, **kwargs):
        calls.append(kwargs.copy())
        return original(*args, **kwargs)

    monkeypatch.setattr(journal_module.tempfile, "NamedTemporaryFile", recording_named_tempfile)
    journal = AtomicJournal(tmp_path, "build-1")

    path = journal.write({"build_id": "build-1", "state": "validated", "history": [{"step": 1}]})

    assert path == tmp_path / ".pscad-mcp" / "lcc-builds" / "build-1" / "journal.json"
    assert calls
    assert calls[0]["delete"] is False
    assert Path(calls[0]["dir"]) == path.parent
    assert _read_json(path) == {"build_id": "build-1", "state": "validated", "history": [{"step": 1}]}
    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "validated"


@pytest.mark.parametrize(
    "bad_value",
    [
        Path("runtime-path"),
        RuntimeError("runtime-exception"),
        asyncio.Lock(),
        object(),
    ],
)
def test_atomic_journal_rejects_runtime_objects_without_replacing_previous_journal(tmp_path, bad_value):
    journal = AtomicJournal(tmp_path, "build-1")
    path = journal.write({"build_id": "build-1", "state": "validated"})

    _assert_backend_code(
        lambda: journal.write({"build_id": "build-1", "state": "failed", "runtime": bad_value}),
        "LCC_JOURNAL_INVALID",
    )

    assert _read_json(path) == {"build_id": "build-1", "state": "validated"}


def test_atomic_journal_cleans_temp_file_and_preserves_previous_on_dump_failure(tmp_path, monkeypatch):
    journal = AtomicJournal(tmp_path, "build-1")
    path = journal.write({"build_id": "build-1", "state": "validated"})
    temp_paths = []
    original_tempfile = journal_module.tempfile.NamedTemporaryFile

    def recording_named_tempfile(*args, **kwargs):
        handle = original_tempfile(*args, **kwargs)
        temp_paths.append(Path(handle.name))
        return handle

    def failing_dump(*args, **kwargs):
        raise TypeError("forced serialization failure")

    monkeypatch.setattr(journal_module.tempfile, "NamedTemporaryFile", recording_named_tempfile)
    monkeypatch.setattr(journal_module.json, "dump", failing_dump)

    _assert_backend_code(lambda: journal.write({"build_id": "build-1", "state": "failed"}), "LCC_JOURNAL_INVALID")

    assert _read_json(path) == {"build_id": "build-1", "state": "validated"}
    assert temp_paths
    assert all(not candidate.exists() for candidate in temp_paths)


def test_workspace_build_lease_acquires_metadata_and_releases_matching_token(tmp_path):
    lease = WorkspaceBuildLease.acquire(tmp_path, "build-1")
    lock_path = tmp_path / ".pscad-mcp" / "lcc-build.lock"
    metadata = _read_json(lock_path)

    assert metadata["build_id"] == "build-1"
    assert metadata["pid"] == os.getpid()
    assert isinstance(metadata["token"], str) and metadata["token"]
    assert metadata["created_at_utc"].endswith("Z")
    assert metadata["journal_path"] == str(AtomicJournal(tmp_path, "build-1").path)
    assert lease.token == metadata["token"]

    assert lease.release() is True
    assert not lock_path.exists()
    assert lease.release() is False


def test_workspace_build_lease_rejects_live_owner_and_corrupt_or_malformed_metadata(tmp_path, monkeypatch):
    lease = WorkspaceBuildLease.acquire(tmp_path, "build-1")
    lock_path = tmp_path / ".pscad-mcp" / "lcc-build.lock"

    monkeypatch.setattr(journal_module.psutil, "pid_exists", lambda pid: True)
    _assert_backend_code(lambda: WorkspaceBuildLease.acquire(tmp_path, "build-2"), "LCC_BUILD_CONFLICT")
    assert _read_json(lock_path)["token"] == lease.token
    assert lease.release() is True

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("{not-json", encoding="utf-8")
    _assert_backend_code(lambda: WorkspaceBuildLease.acquire(tmp_path, "build-3"), "LCC_BUILD_CONFLICT")
    assert lock_path.exists()

    lock_path.write_text(
        json.dumps(
            {
                "build_id": "other",
                "pid": "not-an-int",
                "token": "other-token",
                "created_at_utc": "2026-08-19T00:00:00Z",
                "journal_path": str(AtomicJournal(tmp_path, "other").path),
            }
        ),
        encoding="utf-8",
    )
    _assert_backend_code(lambda: WorkspaceBuildLease.acquire(tmp_path, "build-4"), "LCC_BUILD_CONFLICT")
    assert _read_json(lock_path)["token"] == "other-token"


def test_workspace_build_lease_recovers_dead_owner_after_marking_old_journal_interrupted(tmp_path, monkeypatch):
    old_journal = AtomicJournal(tmp_path, "old-build")
    old_path = old_journal.write({"build_id": "old-build", "state": "components_placed", "history": [{"state": "components_placed"}]})
    lock_path = tmp_path / ".pscad-mcp" / "lcc-build.lock"
    lock_path.write_text(
        json.dumps(
            {
                "build_id": "old-build",
                "pid": 987654,
                "token": "old-token",
                "created_at_utc": "2026-08-19T00:00:00Z",
                "journal_path": str(old_path),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(journal_module.psutil, "pid_exists", lambda pid: False)

    lease = WorkspaceBuildLease.acquire(tmp_path, "new-build")

    old_record = _read_json(old_path)
    new_lock = _read_json(lock_path)
    assert old_record["build_id"] == "old-build"
    assert old_record["state"] == "interrupted"
    assert old_record["history"][-1]["state"] == "interrupted"
    assert old_record["history"][-1]["reason"] == "stale_lock_recovered"
    assert new_lock["build_id"] == "new-build"
    assert new_lock["token"] == lease.token


def test_workspace_build_lease_release_with_mismatched_token_does_not_remove_another_owner(tmp_path):
    lease = WorkspaceBuildLease.acquire(tmp_path, "build-1")
    lock_path = tmp_path / ".pscad-mcp" / "lcc-build.lock"
    original = _read_json(lock_path)

    assert lease.release(token="wrong-token") is False
    assert _read_json(lock_path) == original
    _assert_backend_code(lambda: WorkspaceBuildLease.acquire(tmp_path, "build-2"), "LCC_BUILD_CONFLICT")

    assert lease.release() is True
    assert not lock_path.exists()


def test_workspace_build_lease_release_preserves_lock_replaced_after_owner_validation(tmp_path, monkeypatch):
    lease = WorkspaceBuildLease.acquire(tmp_path, "build-1")
    lock_path = tmp_path / ".pscad-mcp" / "lcc-build.lock"
    replacement = {
        "build_id": "replacement-build",
        "pid": os.getpid(),
        "token": "replacement-token",
        "created_at_utc": "2026-08-19T00:00:00Z",
        "journal_path": str(AtomicJournal(tmp_path, "replacement-build").path),
    }
    original_remove = journal_module._remove_matching_lock

    def replace_before_conditional_remove(path, expected_token):
        replacement_path = path.with_name("lcc-build.lock.replacement")
        replacement_path.write_text(json.dumps(replacement), encoding="utf-8")
        os.replace(replacement_path, path)
        return original_remove(path, expected_token)

    monkeypatch.setattr(journal_module, "_remove_matching_lock", replace_before_conditional_remove)

    assert lease.release() is False
    assert _read_json(lock_path)["token"] == "replacement-token"


def test_workspace_build_lease_stale_recovery_preserves_lock_replaced_before_removal(tmp_path, monkeypatch):
    old_journal = AtomicJournal(tmp_path, "old-build")
    old_path = old_journal.write({"build_id": "old-build", "state": "components_placed"})
    lock_path = tmp_path / ".pscad-mcp" / "lcc-build.lock"
    lock_path.write_text(
        json.dumps(
            {
                "build_id": "old-build",
                "pid": 987654,
                "token": "old-token",
                "created_at_utc": "2026-08-19T00:00:00Z",
                "journal_path": str(old_path),
            }
        ),
        encoding="utf-8",
    )
    replacement = {
        "build_id": "replacement-build",
        "pid": os.getpid(),
        "token": "replacement-token",
        "created_at_utc": "2026-08-19T00:00:00Z",
        "journal_path": str(AtomicJournal(tmp_path, "replacement-build").path),
    }
    original_remove = journal_module._remove_matching_lock

    def replace_before_conditional_remove(path, expected_token):
        replacement_path = path.with_name("lcc-build.lock.replacement")
        replacement_path.write_text(json.dumps(replacement), encoding="utf-8")
        os.replace(replacement_path, path)
        return original_remove(path, expected_token)

    monkeypatch.setattr(journal_module, "_remove_matching_lock", replace_before_conditional_remove)
    monkeypatch.setattr(journal_module.psutil, "pid_exists", lambda pid: pid == os.getpid())

    _assert_backend_code(lambda: WorkspaceBuildLease.acquire(tmp_path, "new-build"), "LCC_BUILD_CONFLICT")
    assert _read_json(lock_path)["token"] == "replacement-token"


def test_workspace_build_lease_release_preserves_replacement_installed_after_tombstone_move(tmp_path, monkeypatch):
    lease = WorkspaceBuildLease.acquire(tmp_path, "build-1")
    lock_path = tmp_path / ".pscad-mcp" / "lcc-build.lock"
    replacement = {
        "build_id": "replacement-build",
        "pid": os.getpid(),
        "token": "replacement-token",
        "created_at_utc": "2026-08-19T00:00:00Z",
        "journal_path": str(AtomicJournal(tmp_path, "replacement-build").path),
    }
    original_replace = journal_module.os.replace
    moved = False

    def replace_and_install_new_owner(source, destination):
        nonlocal moved
        original_replace(source, destination)
        if Path(source) == lock_path and Path(destination).name.endswith(".pending") and not moved:
            moved = True
            replacement_path = lock_path.with_name("lcc-build.lock.replacement")
            replacement_path.write_text(json.dumps(replacement), encoding="utf-8")
            original_replace(replacement_path, lock_path)

    monkeypatch.setattr(journal_module.os, "replace", replace_and_install_new_owner)

    assert lease.release() is True
    assert _read_json(lock_path)["token"] == "replacement-token"
