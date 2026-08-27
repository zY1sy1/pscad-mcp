import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.common import (
    AtomicJournal,
    JsonRecord,
    WorkspaceBuildLease,
    absolute_port,
    canonical_json,
    content_hash,
    route_intersects_rectangles,
    transform_offset,
    validate_orthogonal_route,
)
from pscad_mcp.hvdc.builders.lcc.assets import canonical_json as lcc_canonical_json
from pscad_mcp.hvdc.builders.lcc.journal import WorkspaceBuildLease as LccLease
from pscad_mcp.hvdc.builders.lcc.planner import LccPlanRequest, create_plan
from pscad_mcp.hvdc.builders.mmc.journal import WorkspaceBuildLease as MmcLease

from tests.test_lcc_planner import INVENTORY, _asset_set


_LCC_PLAN_BASELINE = Path(__file__).parent / "fixtures" / "lcc" / "lcc_plan_pre_common_baseline.json"


@dataclass(frozen=True)
class _CommonRecord(JsonRecord):
    payload: dict


def test_common_canonical_json_is_sorted_finite_and_hashed():
    payload = {"z": [1, 2.5], "a": {"b": True, "a": None}}

    serialized = canonical_json(payload)

    assert serialized == b'{"a":{"a":null,"b":true},"z":[1,2.5]}'
    assert content_hash(payload) == hashlib.sha256(serialized).hexdigest()
    assert lcc_canonical_json(payload) == serialized

    with pytest.raises(TypeError):
        canonical_json({"value": float("nan")})


def test_common_json_record_normalizes_nested_values():
    record = _CommonRecord({"items": [1, 2]})

    assert record.to_dict() == {"payload": {"items": [1, 2]}}


def test_common_routing_exports_lcc_compatible_geometry_primitives():
    assert transform_offset(12, 6, 1) == (-6, 12)
    assert absolute_port((100, 50), (12, 6), 1) == (94, 62)
    assert validate_orthogonal_route([(0, 0), (10, 0), (10, 5)]) == ((0, 0), (10, 0), (10, 5))
    assert route_intersects_rectangles([(0, 0), (4, 0)], [(4, -2, 6, 2)]) is None


def _read_line_with_timeout(process: subprocess.Popen[str], timeout: float = 5.0) -> str:
    lines: queue.Queue[str] = queue.Queue(maxsize=1)

    def read_line() -> None:
        assert process.stdout is not None
        lines.put(process.stdout.readline())

    threading.Thread(target=read_line, daemon=True).start()
    try:
        return lines.get(timeout=timeout)
    except queue.Empty as error:
        raise AssertionError("common lease child did not publish owner evidence in time") from error


def _subprocess_python() -> str:
    repository_root = Path(__file__).parents[1]
    candidates = [
        repository_root / ".venv" / "Scripts" / "python.exe",
        repository_root / ".venv" / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            subprocess.run(
                [str(candidate), "-c", "pass"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
        return str(candidate)
    raise AssertionError("no runnable Python interpreter is available for the lease process test")


def test_common_journal_and_lease_are_workspace_scoped(tmp_path):
    journal = AtomicJournal(tmp_path, "build-1")
    path = journal.write({"build_id": "build-1", "state": "validated"})

    assert path == tmp_path / ".pscad-mcp" / "builds" / "build-1" / "journal.json"
    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "validated"

    child_code = """
import json
import os
import sys

from pscad_mcp.hvdc.builders.common import AtomicJournal, WorkspaceBuildLease

root = sys.argv[1]
lease = WorkspaceBuildLease.acquire(root, "build-1")
print(json.dumps({"pid": os.getpid(), "build_id": lease.build_id, "journal_path": str(AtomicJournal(root, "build-1").path)}), flush=True)
sys.stdin.readline()
if not lease.release():
    raise SystemExit(3)
    """
    child = subprocess.Popen(
        [_subprocess_python(), "-c", child_code, str(tmp_path)],
        cwd=str(Path(__file__).parents[1]),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        owner = json.loads(_read_line_with_timeout(child))
        with pytest.raises(BackendError) as raised:
            WorkspaceBuildLease.acquire(tmp_path, "build-2")
        assert raised.value.code == "BUILDER_BUILD_CONFLICT"
        assert owner["pid"] != os.getpid()
        assert isinstance(owner["pid"], int) and owner["pid"] > 0
        assert owner["build_id"] == "build-1"
        assert owner["journal_path"] == str(AtomicJournal(tmp_path, "build-1").path)
        assert raised.value.details == {
            "build_id": owner["build_id"],
            "pid": owner["pid"],
            "journal_path": owner["journal_path"],
        }
    finally:
        if child.stdin is not None:
            child.stdin.write("release\n")
            child.stdin.close()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
        assert child.returncode == 0


def test_lcc_and_mmc_use_one_workspace_lock(tmp_path: Path) -> None:
    lcc = LccLease.acquire(tmp_path, "lcc-1")
    try:
        with pytest.raises(BackendError) as raised:
            MmcLease.acquire(tmp_path, "mmc-1")
        assert raised.value.code in {"BUILDER_BUILD_CONFLICT", "MMC_BUILD_CONFLICT"}
        assert raised.value.details["build_id"] == "lcc-1"
    finally:
        assert lcc.release(lcc.token) is True


def _lcc_plan_hash_payload(plan):
    return {
        "request": dict(plan.metadata),
        "target_path": plan.target_path,
        "staging_path": plan.staging_path,
        "pscad_version": plan.pscad_version,
        "asset_hashes": dict(plan.asset_hashes),
        "catalog_identity": plan.catalog_identity,
        "project_settings": dict(plan.blueprint.settings),
        "operations": [operation.to_dict() for operation in plan.operations],
        "acceptance_contract": [check.to_dict() for check in plan.acceptance_checks],
    }


def test_common_journal_normalizes_serialization_failures_without_replacing_previous(tmp_path):
    journal = AtomicJournal(tmp_path, "build-1")
    path = journal.write({"build_id": "build-1", "state": "validated"})

    with pytest.raises(BackendError) as raised:
        journal.write({"build_id": "build-1", "state": "failed", "runtime": object()})

    assert raised.value.code == "BUILDER_JOURNAL_INVALID"
    assert raised.value.backend == "hvdc"
    assert raised.value.operation == "write_builder_journal"
    assert json.loads(path.read_text(encoding="utf-8")) == {"build_id": "build-1", "state": "validated"}


def test_lcc_plan_payload_and_hash_match_pre_common_baseline():
    baseline_payload = _LCC_PLAN_BASELINE.read_bytes().rstrip(b"\r\n")
    baseline_hash = "96315762b0af90138249387c42836660b41734065c3de158a903d02f333b3296"

    request = LccPlanRequest("CIGRE_LCC")
    asset_set = _asset_set()
    workspace = Path("C:/pscad-mcp-task1-baseline")

    first = create_plan(request, asset_set, INVENTORY, workspace)
    second = create_plan(request, asset_set, INVENTORY, workspace)
    first_payload = _lcc_plan_hash_payload(first)
    second_payload = _lcc_plan_hash_payload(second)

    assert canonical_json(first_payload) == baseline_payload
    assert canonical_json(first_payload) == canonical_json(second_payload)
    assert content_hash(first_payload) == baseline_hash
    assert first.plan_hash == baseline_hash
    assert first.plan_hash == second.plan_hash
