import hashlib
import json
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.assets import (
    load_asset_set,
    load_packaged_asset_set,
    materialize_library,
    sha256_file,
)


def _blueprint():
    return {
        "schema_version": 1,
        "name": "cigre_lcc_monopole_v1",
        "topology": "lcc",
        "poles": 1,
        "terminals": 2,
        "settings": {
            "time_step_s": 5e-5,
            "output_step_s": 5e-5,
            "simulation_duration_s": 1.0,
            "compiler_target": "fortran",
            "output_enabled": True,
        },
        "components": [
            {
                "logical_id": "source",
                "definition": "master:source3",
                "location": {"x": 0, "y": 0},
                "ports": ["ac"],
            },
            {
                "logical_id": "bridge",
                "definition": "cigre_lcc_v1:LCC12PulseBridge",
                "location": {"x": 100, "y": 0},
                "ports": ["ac"],
            },
        ],
        "nets": [
            {
                "logical_id": "ac",
                "kind": "electrical",
                "endpoints": [
                    {"component": "source", "port": "ac"},
                    {"component": "bridge", "port": "ac"},
                ],
                "route": {"vertices": [[10, 0], [90, 0]]},
            }
        ],
        "outputs": [
            {
                "logical_id": "vdc",
                "path": "Main/VDC",
                "units": "kV",
                "role": "dc_voltage",
            }
        ],
    }


def _write_asset_files(root: Path) -> dict[str, bytes]:
    library = b"<pslx><definition name='cigre_lcc_v1:LCC12PulseBridge'/></pslx>"
    registry = {
        "schema_version": 1,
        "name": "test_master_bindings_v1",
        "pscad_version": "4.6.2",
        "bindings": [
            {
                "logical_name": "master:test",
                "physical_definition": "resistor",
                "shape": {"kind": "direct"},
                "ports": [
                    {
                        "logical": "IN",
                        "physical": "A",
                        "kind": "electrical",
                        "dimension": 1,
                        "occurrence": 0,
                    }
                ],
                "parameters": [],
                "fixed_parameters": [],
                "evidence_parameters": [],
            }
        ],
    }
    files = {
        "blueprint.json": json.dumps(_blueprint(), sort_keys=True).encode("utf-8"),
        "catalog-pscad-4.6.2.json": json.dumps(
            {
                "name": "catalog",
                "master_binding_registry": "master-bindings-pscad-4.6.2.json",
            },
            sort_keys=True,
        ).encode("utf-8"),
        "master-bindings-pscad-4.6.2.json": json.dumps(
            registry, sort_keys=True
        ).encode("utf-8"),
        "acceptance.json": b'{"checks":[]}',
        "golden.json": b'{"channels":{}}',
        "smoke.json": (
            b'{"identity":"cigre_lcc_monopole_v1/wp1b_smoke"}'
        ),
        "PROVENANCE.md": b"public source\n",
        "library/cigre_lcc_v1.pslx": library,
    }
    for relative, payload in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return files


def _write_manifest(root: Path, files: dict[str, bytes], *, version="4.6.2", hashes_key="hashes"):
    hashes = {
        relative: hashlib.sha256(payload).hexdigest()
        for relative, payload in files.items()
    }
    manifest = {
        "schema_version": 1,
        "name": "cigre_lcc_monopole_v1",
        "pscad_version": version,
        "companion_library": "library/cigre_lcc_v1.pslx",
        hashes_key: hashes,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _asset_root(tmp_path):
    root = tmp_path / "asset"
    files = _write_asset_files(root)
    _write_manifest(root, files)
    return root, files


def _assert_error(call, code):
    with pytest.raises(BackendError) as raised:
        call()
    assert raised.value.code == code


def test_load_asset_set_validates_hashes_before_returning_records(tmp_path):
    root, files = _asset_root(tmp_path)

    asset_set = load_asset_set(root)

    library = root / "library/cigre_lcc_v1.pslx"
    assert asset_set.name == "cigre_lcc_monopole_v1"
    assert asset_set.blueprint.name == "cigre_lcc_monopole_v1"
    assert asset_set.hashes["library/cigre_lcc_v1.pslx"] == sha256_file(library)
    assert asset_set.library_bytes == files["library/cigre_lcc_v1.pslx"]
    assert asset_set.root is None


def test_load_asset_set_exposes_manifest_hashed_master_registry(tmp_path):
    root, _ = _asset_root(tmp_path)

    asset_set = load_asset_set(root)

    assert asset_set.master_bindings.schema_version == 1
    assert asset_set.master_bindings.pscad_version == "4.6.2"
    assert (
        asset_set.master_binding_hash
        == asset_set.hashes["master-bindings-pscad-4.6.2.json"]
    )


def test_packaged_asset_exposes_hashed_wp1b_smoke_contract():
    asset_set = load_packaged_asset_set()

    assert asset_set.smoke["identity"] == (
        "cigre_lcc_monopole_v1/wp1b_smoke"
    )
    assert asset_set.smoke["duration_s"] == pytest.approx(0.1)
    assert "smoke.json" in asset_set.hashes
    assert asset_set.master_bindings is not None
    assert asset_set.master_bindings.schema_version == 2
    assert set(asset_set.master_bindings.companion_by_logical_name) == {
        "master:six_pulse_bridge",
        "master:control_sum",
        "master:control_pi",
        "master:control_limiter",
        "master:control_minimum",
        "master:control_product",
        "master:real_constant",
        "master:integer_constant",
        "master:signal_import",
        "master:electrical_pin",
        "master:signal_export",
        "master:integer_sum",
        "master:three_phase_breakout",
        "master:integer_to_real",
        "master:output_channel",
        "master:real_to_integer",
    }


def test_catalog_registry_reference_mismatch_is_rejected(tmp_path):
    root, files = _asset_root(tmp_path)
    files["catalog-pscad-4.6.2.json"] = json.dumps(
        {"name": "catalog", "master_binding_registry": "wrong.json"},
        sort_keys=True,
    ).encode("utf-8")
    (root / "catalog-pscad-4.6.2.json").write_bytes(
        files["catalog-pscad-4.6.2.json"]
    )
    _write_manifest(root, files)

    _assert_error(lambda: load_asset_set(root), "LCC_ASSET_MISMATCH")


def test_text_asset_hashes_are_stable_across_line_endings(tmp_path):
    root, files = _asset_root(tmp_path)
    for relative, payload in files.items():
        (root / relative).write_bytes(payload.replace(b"\n", b"\r\n"))

    asset_set = load_asset_set(root)

    assert asset_set.library_bytes == files["library/cigre_lcc_v1.pslx"]


def test_mutated_file_is_rejected(tmp_path):
    root, _ = _asset_root(tmp_path)
    path = root / "library/cigre_lcc_v1.pslx"
    path.write_bytes(path.read_bytes() + b"x")

    _assert_error(lambda: load_asset_set(root), "LCC_ASSET_MISMATCH")


def test_missing_file_is_rejected(tmp_path):
    root, _ = _asset_root(tmp_path)
    (root / "golden.json").unlink()

    _assert_error(lambda: load_asset_set(root), "LCC_ASSET_MISMATCH")


def test_unmanifested_file_is_rejected(tmp_path):
    root, _ = _asset_root(tmp_path)
    (root / "library/unexpected.pslx").write_bytes(b"unexpected")

    _assert_error(lambda: load_asset_set(root), "LCC_ASSET_MISMATCH")


def test_manifest_path_escape_is_rejected(tmp_path):
    root, files = _asset_root(tmp_path)
    _write_manifest(root, files)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["hashes"]["../escape.json"] = "0" * 64
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    _assert_error(lambda: load_asset_set(root), "LCC_ASSET_MISMATCH")


def test_unsupported_pscad_version_is_rejected_before_parsing(tmp_path):
    root, files = _asset_root(tmp_path)
    _write_manifest(root, files, version="5.0")

    _assert_error(lambda: load_asset_set(root), "LCC_VERSION_UNSUPPORTED")


def test_materialize_library_is_atomic_and_reuses_matching_file(tmp_path):
    root, _ = _asset_root(tmp_path)
    asset_set = load_asset_set(root)
    workspace = tmp_path / "workspace"

    first = materialize_library(asset_set, workspace)
    second = materialize_library(asset_set, workspace)

    assert first == second
    assert first.read_bytes() == asset_set.library_bytes
    assert not list(first.parent.glob("*.tmp"))


def test_materialize_library_does_not_replace_mismatched_file(tmp_path):
    root, _ = _asset_root(tmp_path)
    asset_set = load_asset_set(root)
    workspace = tmp_path / "workspace"
    target = workspace / ".pscad-mcp" / "libraries" / "cigre_lcc_v1.pslx"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"user file")

    _assert_error(lambda: materialize_library(asset_set, workspace), "LCC_ASSET_MISMATCH")
    assert target.read_bytes() == b"user file"


def test_materialize_library_rejects_workspace_symlink_target(tmp_path):
    root, _ = _asset_root(tmp_path)
    asset_set = load_asset_set(root)
    workspace = tmp_path / "workspace"
    target = workspace / ".pscad-mcp" / "libraries" / "cigre_lcc_v1.pslx"
    outside = tmp_path / "outside.pslx"
    outside.write_bytes(b"outside")
    target.parent.mkdir(parents=True)
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    _assert_error(lambda: materialize_library(asset_set, workspace), "LCC_ASSET_MISMATCH")
    assert outside.read_bytes() == b"outside"


def test_materialize_library_rejects_non_file_target(tmp_path):
    root, _ = _asset_root(tmp_path)
    asset_set = load_asset_set(root)
    workspace = tmp_path / "workspace"
    target = workspace / ".pscad-mcp" / "libraries" / "cigre_lcc_v1.pslx"
    target.mkdir(parents=True)

    _assert_error(lambda: materialize_library(asset_set, workspace), "LCC_ASSET_MISMATCH")
