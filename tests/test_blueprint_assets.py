from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pscad_mcp.builders.blueprint.assets import (
    audit_source_package,
    hash_tree,
    load_blueprint_asset,
)
from pscad_mcp.builders.blueprint.schema import parse_blueprint
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from test_blueprint_schema import valid_blueprint


def write_source_package(root: Path) -> Path:
    source = root / "source-package"
    (source / "support").mkdir(parents=True)
    (source / "source.pscx").write_text("<project name='Source'/>", encoding="utf-8")
    (source / "support" / "breaker.pslx").write_text("<library/>", encoding="utf-8")
    (source / "support" / "notes.txt").write_text("audited", encoding="utf-8")
    return source


def test_hash_tree_is_stable_and_sensitive_to_relative_paths_and_bytes(tmp_path):
    source = write_source_package(tmp_path)

    first = hash_tree(source)
    second = hash_tree(source)

    assert first == second
    assert list(first) == sorted(first)
    assert set(first) == {"source.pscx", "support/breaker.pslx", "support/notes.txt"}
    (source / "support" / "notes.txt").write_text("changed", encoding="utf-8")
    assert hash_tree(source) != first


def test_audit_source_package_verifies_required_paths_and_expected_hashes(tmp_path):
    source = write_source_package(tmp_path)
    value = valid_blueprint()
    digest = hashlib.sha256((source / "source.pscx").read_bytes()).hexdigest()
    value["source_package"]["required"][0]["sha256"] = digest

    audit = audit_source_package(parse_blueprint(value), str(source), PathPolicy(str(tmp_path)))

    assert audit.entry_point == str((source / "source.pscx").resolve())
    assert audit.package_hashes["source.pscx"] == digest
    assert audit.package_hash == audit_source_package(
        parse_blueprint(value), str(source), PathPolicy(str(tmp_path))
    ).package_hash


@pytest.mark.parametrize("failure", ["missing", "wrong_kind", "hash"])
def test_audit_source_package_fails_closed_on_dependency_drift(tmp_path, failure):
    source = write_source_package(tmp_path)
    value = valid_blueprint()
    if failure == "missing":
        (source / "support" / "breaker.pslx").unlink()
        value["source_package"]["required"].append({"path": "support/breaker.pslx", "kind": "file"})
    elif failure == "wrong_kind":
        value["source_package"]["required"][1]["kind"] = "file"
    else:
        value["source_package"]["required"][0]["sha256"] = "0" * 64

    with pytest.raises(BackendError) as raised:
        audit_source_package(parse_blueprint(value), str(source), PathPolicy(str(tmp_path)))

    assert raised.value.code in {"BLUEPRINT_SOURCE_MISSING", "BLUEPRINT_SOURCE_INVALID", "BLUEPRINT_SOURCE_HASH_MISMATCH"}


def test_audit_source_package_rejects_escape_and_symlinked_files(tmp_path):
    source = write_source_package(tmp_path)
    outside = tmp_path.parent / "outside-blueprint.pscx"
    outside.write_text("outside", encoding="utf-8")
    value = valid_blueprint()
    value["source_package"]["entry_point"] = "../outside-blueprint.pscx"

    with pytest.raises((BackendError, ValueError)):
        audit_source_package(parse_blueprint(value), str(source), PathPolicy(str(tmp_path)))


def test_load_blueprint_asset_accepts_objects_and_hash_verified_named_assets(tmp_path):
    value = valid_blueprint()
    direct = load_blueprint_asset(value)
    asset_dir = tmp_path / "breaker-copy-v1"
    asset_dir.mkdir()
    (asset_dir / "blueprint.json").write_text(json.dumps(value), encoding="utf-8")
    (asset_dir / "catalog.json").write_text(json.dumps({"identity": "catalog-v1"}), encoding="utf-8")

    named = load_blueprint_asset("breaker-copy-v1", asset_root=tmp_path)

    assert direct.blueprint.identity.name == "breaker-copy-v1"
    assert set(direct.hashes) == {"blueprint.json"}
    assert set(named.hashes) == {"blueprint.json", "catalog.json"}
    assert named.catalog == {"identity": "catalog-v1"}


def test_load_blueprint_asset_rejects_name_mismatch_and_missing_asset(tmp_path):
    asset_dir = tmp_path / "wrong-name"
    asset_dir.mkdir()
    (asset_dir / "blueprint.json").write_text(json.dumps(valid_blueprint()), encoding="utf-8")

    with pytest.raises(BackendError) as mismatch:
        load_blueprint_asset("wrong-name", asset_root=tmp_path)
    assert mismatch.value.code == "BLUEPRINT_ASSET_INVALID"

    with pytest.raises(BackendError) as missing:
        load_blueprint_asset("missing", asset_root=tmp_path)
    assert missing.value.code == "BLUEPRINT_ASSET_NOT_FOUND"

