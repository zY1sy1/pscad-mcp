import hashlib
import json
from dataclasses import dataclass

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
from pscad_mcp.hvdc.builders.lcc.planner import LccPlanRequest, create_plan

from tests.test_lcc_planner import INVENTORY, _asset_set


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


def test_common_journal_and_lease_are_workspace_scoped(tmp_path):
    journal = AtomicJournal(tmp_path, "build-1")
    path = journal.write({"build_id": "build-1", "state": "validated"})

    assert path == tmp_path / ".pscad-mcp" / "builds" / "build-1" / "journal.json"
    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "validated"

    lease = WorkspaceBuildLease.acquire(tmp_path, "build-1")
    try:
        with pytest.raises(BackendError) as raised:
            WorkspaceBuildLease.acquire(tmp_path, "build-2")
        assert raised.value.code == "BUILDER_BUILD_CONFLICT"
        assert raised.value.details["build_id"] == "build-1"
        assert raised.value.details["pid"]
        assert raised.value.details["journal_path"] == str(path)
    finally:
        assert lease.release() is True


def test_lcc_plan_payload_and_hash_remain_deterministic_after_extraction(tmp_path):
    request = LccPlanRequest("CIGRE_LCC")
    asset_set = _asset_set()

    first = create_plan(request, asset_set, INVENTORY, tmp_path)
    second = create_plan(request, asset_set, INVENTORY, tmp_path)

    assert canonical_json(first.to_dict()) == canonical_json(second.to_dict())
    assert first.plan_hash == second.plan_hash
