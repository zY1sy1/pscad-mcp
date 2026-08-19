from __future__ import annotations

import json
from pathlib import Path

from pscad_mcp.hvdc.builders.mmc.schema import parse_blueprint
from scripts.audit_mmc_assets import audit_asset_root


ASSET_ROOT = Path(__file__).parents[1] / "pscad_mcp" / "assets" / "mmc" / "cigre_b4_p2p_avm_v1"


def test_production_mmc_asset_set_is_exact_and_audited():
    report = audit_asset_root(ASSET_ROOT)
    assert report["valid"] is True, report
    assert report["pscad_version"] == "4.6.2"
    assert report["definitions"] == [
        "cigre_mmc_avm_v1:MMCAverageArm",
        "cigre_mmc_avm_v1:MMCDimensionedSignal",
        "cigre_mmc_avm_v1:MMCEnergyControl",
        "cigre_mmc_avm_v1:MMCInitialization",
        "cigre_mmc_avm_v1:MMCSequenceSignal",
        "cigre_mmc_avm_v1:MMCStationControl",
    ]
    assert set(report["manifest_files"]) == {
        "PROVENANCE.md", "acceptance.json", "blueprint.json", "catalog-pscad-4.6.2.json",
        "controls.json", "golden.json", "operating-sequence.json", "library/cigre_mmc_avm_v1.pslx",
    }

    blueprint = json.loads((ASSET_ROOT / "blueprint.json").read_text(encoding="utf-8"))
    parsed = parse_blueprint(blueprint)
    assert parsed.profile == "cigre_b4_p2p_avm_v1"
    assert len(parsed.stations) == 2
    assert sum(len(station.arms) for station in parsed.stations) == 12

