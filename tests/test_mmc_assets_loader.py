from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.assets import load_asset_set, load_packaged_asset_set, materialize_library, sha256_file


ASSET_ROOT = Path(__file__).parents[1] / "pscad_mcp" / "assets" / "mmc" / "cigre_b4_p2p_avm_v1"


def test_packaged_mmc_asset_loader_verifies_manifest_and_schema():
    asset = load_packaged_asset_set()

    assert asset.name == "cigre_b4_p2p_avm_v1"
    assert asset.pscad_version == "4.6.2"
    assert asset.companion_library in asset.hashes
    assert len(asset.blueprint.stations) == 2
    assert len(asset.blueprint.outputs) > 0


@pytest.mark.parametrize("mutation", ["extra", "changed"])
def test_mmc_asset_loader_fails_closed_on_manifest_drift(tmp_path, mutation):
    copied = tmp_path / "asset"
    shutil.copytree(ASSET_ROOT, copied)
    if mutation == "extra":
        (copied / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    else:
        acceptance = copied / "acceptance.json"
        value = json.loads(acceptance.read_text(encoding="utf-8"))
        value["drift"] = True
        acceptance.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(BackendError) as raised:
        load_asset_set(copied)
    assert raised.value.code == "MMC_ASSET_MISMATCH"


def test_mmc_library_materialization_is_hash_checked_and_idempotent(tmp_path):
    asset = load_packaged_asset_set()

    first = materialize_library(asset, tmp_path)
    second = materialize_library(asset, tmp_path)

    assert first == second
    assert sha256_file(first) == asset.hashes[asset.companion_library]
