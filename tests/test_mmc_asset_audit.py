from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_mmc_assets import audit_asset_root, materialize_library


EXPECTED = {
    "cigre_mmc_avm_v1:MMCAverageArm",
    "cigre_mmc_avm_v1:MMCStationControl",
    "cigre_mmc_avm_v1:MMCEnergyControl",
    "cigre_mmc_avm_v1:MMCInitialization",
    "cigre_mmc_avm_v1:MMCDimensionedSignal",
    "cigre_mmc_avm_v1:MMCSequenceSignal",
}


def _library(*, extra: str = "", absolute: str = "", drift: bool = False, duplicate: bool = False) -> str:
    arm_ports = "<port name=\"AC\" kind=\"electrical\" dimension=\"1\" /><port name=\"DC_POS\" kind=\"electrical\" dimension=\"1\" /><port name=\"DC_NEG\" kind=\"electrical\" dimension=\"1\" /><port name=\"V_INSERTED\" kind=\"signal\" dimension=\"1\" /><port name=\"I_ARM\" kind=\"signal\" dimension=\"1\" /><port name=\"ENERGY\" kind=\"signal\" dimension=\"1\" />"
    if drift:
        arm_ports = arm_ports.replace('name="ENERGY"', 'name="ENERGY_DRIFT"')
    definitions = f'''
  <definition name="cigre_mmc_avm_v1:MMCAverageArm" path="{absolute}"><external_ports>{arm_ports}</external_ports><equations state="energy" /></definition>
  <definition name="cigre_mmc_avm_v1:MMCStationControl"><external_ports><port name="P_ORDER" /><port name="Q_ORDER" /><port name="VDC_ORDER" /><port name="GATES" dimension="6" /></external_ports><control_block definition="master:pi_controller" /></definition>
  <definition name="cigre_mmc_avm_v1:MMCEnergyControl"><external_ports><port name="ENERGY_REF" /><port name="ENERGY" /><port name="ICIRC" /></external_ports><equations state="energy" /></definition>
  <definition name="cigre_mmc_avm_v1:MMCInitialization"><external_ports><port name="RESET" /><port name="READY" /></external_ports><initialization mode="blocked_precharge" /></definition>
  <definition name="cigre_mmc_avm_v1:MMCDimensionedSignal"><external_ports><port name="SIGNAL" dimension="3" /></external_ports></definition>
  <definition name="cigre_mmc_avm_v1:MMCSequenceSignal"><external_ports><port name="STATE" dimension="1" /></external_ports></definition>
  {extra}
'''
    if duplicate:
        definitions += '<definition name="cigre_mmc_avm_v1:MMCAverageArm" />'
    return f'''<?xml version="1.0" encoding="utf-8"?>
<pslx><metadata schema_version="1" /><library scope="cigre_mmc_avm_v1">{definitions}</library></pslx>'''


def _asset_root(tmp_path: Path, library: str, provenance: str | None = None) -> Path:
    root = tmp_path / "asset"
    (root / "library").mkdir(parents=True)
    (root / "library" / "cigre_mmc_avm_v1.pslx").write_text(library, encoding="utf-8")
    (root / "catalog-pscad-4.6.2.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pscad_version": "4.6.2",
                "definitions": {
                    name: {"ports": ([
                        {"name": "AC", "kind": "electrical", "dimension": "1"},
                        {"name": "DC_POS", "kind": "electrical", "dimension": "1"},
                        {"name": "DC_NEG", "kind": "electrical", "dimension": "1"},
                        {"name": "V_INSERTED", "kind": "signal", "dimension": "1"},
                        {"name": "I_ARM", "kind": "signal", "dimension": "1"},
                        {"name": "ENERGY", "kind": "signal", "dimension": "1"},
                    ] if name.endswith("MMCAverageArm") else [])} for name in sorted(EXPECTED)
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "PROVENANCE.md").write_text(provenance or "Public source: CIGRE B4-derived engineering equations. Original derivation: AVM loss and signal dimensions. AVM limitations are recorded.", encoding="utf-8")
    _write_manifest(root)
    return root


def _write_manifest(root: Path) -> None:
    # The audit test fixture uses a generated manifest because hashes are the
    # contract under test; production assets carry the same fields statically.
    import hashlib

    files = {}
    for path in sorted(path for path in root.rglob("*") if path.is_file() and path.name != "manifest.json"):
        files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps({"schema_version": 1, "pscad_version": "4.6.2", "files": files}, sort_keys=True), encoding="utf-8")


def test_audit_accepts_structured_repository_authored_library(tmp_path):
    root = _asset_root(tmp_path, _library())
    report = audit_asset_root(root)
    assert report["valid"] is True
    assert set(report["definitions"]) == EXPECTED
    assert report["pscad_version"] == "4.6.2"

    destination = tmp_path / ".pscad-mcp" / "mmc-libraries" / "cigre_mmc_avm_v1.pslx"
    materialized = materialize_library(root, destination)
    assert materialized == destination
    assert destination.read_text(encoding="utf-8").startswith("<?xml")


def test_audit_rejects_missing_duplicate_foreign_absolute_and_port_drift(tmp_path):
    root = _asset_root(tmp_path, _library(extra='<definition name="foreign_scope:Copied" />', absolute="C:\\Users\\author\\library.pslx", drift=True, duplicate=True), provenance="incomplete")
    report = audit_asset_root(root)
    reasons = {error["reason"] for error in report["errors"]}
    assert report["valid"] is False
    assert {"duplicate_definition", "foreign_scope", "absolute_path", "port_drift", "provenance_incomplete"} <= reasons


def test_audit_rejects_unexpected_files_and_missing_provenance(tmp_path):
    root = _asset_root(tmp_path, _library())
    (root / "unexpected.bin").write_bytes(b"not an MMC asset")
    (root / "PROVENANCE.md").unlink()
    report = audit_asset_root(root)
    reasons = {error["reason"] for error in report["errors"]}
    assert {"unexpected_file", "provenance_missing_or_invalid"} <= reasons
