from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_lcc_assets import audit_asset_root


def _library(*, extra: str = "", absolute: str = "") -> str:
    valves = "".join(
        f'<valve id="V{index:02d}" definition="master:thyristor_valve" group="{"upper" if index <= 6 else "lower"}" />'
        for index in range(1, 13)
    )
    return f'''<?xml version="1.0" encoding="utf-8"?>
<pslx>
  <definition name="cigre_lcc_v1:LCC12PulseBridge" path="{absolute}">
    <external_ports>
      <port name="ACY_A" kind="electrical" dimension="1" group="acy" />
      <port name="ACY_B" kind="electrical" dimension="1" group="acy" />
      <port name="ACY_C" kind="electrical" dimension="1" group="acy" />
      <port name="ACD_A" kind="electrical" dimension="1" group="acd" />
      <port name="ACD_B" kind="electrical" dimension="1" group="acd" />
      <port name="ACD_C" kind="electrical" dimension="1" group="acd" />
      <port name="DC_POS" kind="electrical" dimension="1" />
      <port name="DC_NEG" kind="electrical" dimension="1" />
      <port name="GATES" kind="data" dimension="12" />
    </external_ports>
    <six_pulse_group name="upper" />
    <six_pulse_group name="lower" />
    <valves>{valves}</valves>
    <dc_series_path common="true" />
    <gate_interface port="GATES" dimension="12" />
  </definition>
  <definition name="cigre_lcc_v1:RectifierControl"><external_ports><port name="VDC" /><port name="IDC" /><port name="IORDER" /><port name="ENABLE" /><port name="GATES" dimension="12" /><port name="ALPHA" /></external_ports><control_block definition="master:cc_controller" role="constant_current" /></definition>
  <definition name="cigre_lcc_v1:InverterControl"><external_ports><port name="VDC" /><port name="IDC" /><port name="GAMMA_ORDER" /><port name="ENABLE" /><port name="GATES" dimension="12" /><port name="GAMMA" /></external_ports><control_block definition="master:cc_controller" role="constant_extinction_angle" /></definition>
  <definition name="cigre_lcc_v1:SignalInterface" />
  <definition name="cigre_lcc_v1:Initialization" />
  {extra}
</pslx>'''


def _asset_root(tmp_path: Path, library: str, provenance: str | None = None) -> Path:
    root = tmp_path / "asset"
    (root / "library").mkdir(parents=True)
    (root / "library" / "cigre_lcc_v1.pslx").write_text(library, encoding="utf-8")
    (root / "PROVENANCE.md").write_text(
        provenance or "Szechtman, Wess, and Thio, Electra. Table 1, Figure 2, and equation (3). Breaker projects were not sources.",
        encoding="utf-8",
    )
    return root


def test_audit_accepts_repository_authored_library(tmp_path):
    report = audit_asset_root(_asset_root(tmp_path, _library()))

    assert report["valid"] is True
    assert report["definitions"] == [
        "cigre_lcc_v1:Initialization",
        "cigre_lcc_v1:InverterControl",
        "cigre_lcc_v1:LCC12PulseBridge",
        "cigre_lcc_v1:RectifierControl",
        "cigre_lcc_v1:SignalInterface",
    ]
    assert report["valve_count"] == 12


def test_audit_rejects_foreign_scope_absolute_path_and_incomplete_provenance(tmp_path):
    root = _asset_root(
        tmp_path,
        _library(extra='<definition name="local_project:Copied" />', absolute="C:\\Users\\author\\library.pslx"),
        provenance="local source",
    )

    report = audit_asset_root(root)

    assert report["valid"] is False
    reasons = {error["reason"] for error in report["errors"]}
    assert {"foreign_scope", "absolute_path", "provenance_incomplete"} <= reasons
