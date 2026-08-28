from __future__ import annotations

import json
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.journal import WorkspaceBuildLease as LccWorkspaceBuildLease
from pscad_mcp.hvdc.builders.mmc.journal import AtomicJournal, WorkspaceBuildLease


def test_mmc_journal_is_atomic_and_workspace_scoped(tmp_path):
    journal = AtomicJournal(tmp_path, "build-1")
    path = journal.write({"build_id": "build-1", "state": "validated"})

    assert path == tmp_path / ".pscad-mcp" / "mmc-builds" / "build-1" / "journal.json"
    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "validated"


def test_mmc_journal_rejects_path_traversal(tmp_path):
    with pytest.raises(BackendError) as raised:
        AtomicJournal(tmp_path, "../escape")
    assert raised.value.code == "MMC_JOURNAL_INVALID"
    assert not (tmp_path.parent / "escape" / "journal.json").exists()


def test_mmc_lease_conflicts_with_mmc_and_lcc_builds(tmp_path):
    mmc = WorkspaceBuildLease.acquire(tmp_path, "mmc-1")
    with pytest.raises(BackendError) as raised:
        WorkspaceBuildLease.acquire(tmp_path, "mmc-2")
    assert raised.value.code == "MMC_BUILD_CONFLICT"
    assert mmc.release() is True

    lcc = LccWorkspaceBuildLease.acquire(tmp_path, "lcc-1")
    try:
        with pytest.raises(BackendError) as raised:
            WorkspaceBuildLease.acquire(tmp_path, "mmc-3")
        assert raised.value.code == "MMC_BUILD_CONFLICT"
    finally:
        assert lcc.release() is True


def test_lcc_lease_conflicts_with_mmc_builds(tmp_path):
    mmc = WorkspaceBuildLease.acquire(tmp_path, "mmc-1")
    try:
        with pytest.raises(BackendError) as raised:
            LccWorkspaceBuildLease.acquire(tmp_path, "lcc-1")
        assert raised.value.code == "LCC_BUILD_CONFLICT"
    finally:
        assert mmc.release() is True
