from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError

ASSET_ROOT = (
    Path(__file__).parents[1]
    / "pscad_mcp"
    / "assets"
    / "lcc"
    / "cigre_lcc_monopole_v1"
)


def _subject():
    return importlib.import_module("pscad_mcp.core.master_bindings")


def _minimal_binding(logical_name: str = "master:test") -> dict[str, object]:
    return {
        "logical_name": logical_name,
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
        "parameters": [
            {
                "logical": ["Resistance_ohm"],
                "physical": ["R"],
                "transform": {"kind": "identity"},
                "physical_contracts": {
                    "R": {"type": "Real", "unit": "ohm"}
                },
            }
        ],
        "fixed_parameters": [],
        "evidence_parameters": [],
    }


def _registry_payload(*bindings: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "test_master_bindings_v1",
        "pscad_version": "4.6.2",
        "bindings": list(bindings or (_minimal_binding(),)),
    }


def _g6p200_binding() -> dict[str, object]:
    return {
        "logical_name": "master:six_pulse_bridge",
        "physical_definition": "g6p200",
        "shape": {"kind": "direct"},
        "ports": [
            {
                "logical": "N",
                "physical": "N",
                "kind": "electrical",
                "dimension": 3,
                "occurrence": 0,
            },
            {
                "logical": "DP_RECT",
                "physical": "DP",
                "kind": "electrical",
                "dimension": 1,
                "occurrence": 2,
            },
            {
                "logical": "DN_RECT",
                "physical": "DN",
                "kind": "electrical",
                "dimension": 1,
                "occurrence": 3,
            },
            {
                "logical": "DP_INV",
                "physical": "DP",
                "kind": "electrical",
                "dimension": 1,
                "occurrence": 3,
            },
            {
                "logical": "DN_INV",
                "physical": "DN",
                "kind": "electrical",
                "dimension": 1,
                "occurrence": 2,
            },
            {
                "logical": "AO",
                "physical": "AO",
                "kind": "data",
                "dimension": 1,
                "occurrence": 1,
            },
            {
                "logical": "AM",
                "physical": "AM",
                "kind": "data",
                "dimension": 1,
                "occurrence": 1,
            },
            {
                "logical": "GM",
                "physical": "GM",
                "kind": "data",
                "dimension": 1,
                "occurrence": 1,
            },
            {
                "logical": "KB",
                "physical": "KB",
                "kind": "data",
                "dimension": 1,
                "occurrence": 1,
            },
            {
                "logical": "CB",
                "physical": "CB",
                "kind": "data",
                "dimension": 1,
                "occurrence": 1,
            },
        ],
        "parameters": [],
        "fixed_parameters": [
            {
                "physical": "FP",
                "value": 0,
                "contract": {
                    "type": "Choice",
                    "unit": None,
                    "choices": ["0", "1", "2", "3"],
                },
            },
            {
                "physical": "View",
                "value": 1,
                "contract": {
                    "type": "Choice",
                    "unit": None,
                    "choices": ["0", "1"],
                },
            },
        ],
        "evidence_parameters": [],
    }


def _registry_payload_v2(
    *companion_bindings: dict[str, object],
) -> dict[str, object]:
    payload = _registry_payload()
    payload["schema_version"] = 2
    payload["companion_bindings"] = list(
        companion_bindings or (_g6p200_binding(),)
    )
    return payload


def _g6p200_master_xml() -> str:
    return """<?xml version='1.0'?>
<pslx>
  <Definition name='g6p200'>
    <paramlist><param name='Description' value='6 Pulse Bridge'/></paramlist>
    <form><category>
      <parameter name='FP' type='Choice'><value>0</value><choice>0 = Angle in Radians</choice><choice>1 = Array of 6 Pulses</choice><choice>2 = 6 Pulses + 6 Interp. times</choice><choice>3 = Angle in Degrees</choice></parameter>
      <parameter name='View' type='Choice'><value>1</value><choice>0 = detailed</choice><choice>1 = compact</choice></parameter>
    </category></form>
    <svg>
      <port model='Natural' name='DP' x='0' y='-108' dim='1' type='Switched'><![CDATA[(UP)&&(View==0)]]></port>
      <port model='Natural' name='DN' x='0' y='108' dim='1' type='Switched'><![CDATA[!(UP)&&(View==0)]]></port>
      <port model='Natural' name='DN' x='0' y='-108' dim='1' type='Switched'><![CDATA[(UP)&&(View==0)]]></port>
      <port model='Natural' name='DP' x='0' y='108' dim='1' type='Switched'><![CDATA[!(UP)&&(View==0)]]></port>
      <port model='Transfer' name='AM' x='144' y='-72' dim='1' mode='Output' type='Real'><![CDATA[(View==0)]]></port>
      <port model='Transfer' name='GM' x='144' y='-36' dim='1' mode='Output' type='Real'><![CDATA[(View==0)]]></port>
      <port model='Transfer' name='KB' x='144' y='72' dim='1' mode='Input' type='Integer'><![CDATA[(View==0)]]></port>
      <port model='Transfer' name='CB' x='-72' y='-108' dim='1' mode='Input' type='Integer'><![CDATA[(View==0)]]></port>
      <port model='Transfer' name='AO' x='144' y='36' dim='1' mode='Input' type='Real'><![CDATA[((FP==0)||(FP==3))&&(View==0)]]></port>
      <port model='Transfer' name='FPN' x='144' y='36' dim='6' mode='Input' type='Integer'><![CDATA[((FP==1)||(FP==2))&&(View==0)]]></port>
      <port model='Transfer' name='FDT' x='144' y='0' dim='6' mode='Input' type='Real'><![CDATA[(FP==2)&&(View==0)]]></port>
      <port model='Natural' name='N' x='-36' y='0' dim='3' type='Switched'><![CDATA[(View==1)]]></port>
      <port model='Natural' name='DP' x='0' y='-90' dim='1' type='Switched'><![CDATA[(UP)&&(View==1)]]></port>
      <port model='Natural' name='DN' x='0' y='-90' dim='1' type='Switched'><![CDATA[!(UP)&&(View==1)]]></port>
      <port model='Natural' name='DP' x='0' y='90' dim='1' type='Switched'><![CDATA[!(UP)&&(View==1)]]></port>
      <port model='Natural' name='DN' x='0' y='90' dim='1' type='Switched'><![CDATA[(UP)&&(View==1)]]></port>
      <port model='Transfer' name='AM' x='54' y='-54' dim='1' mode='Output' type='Real'><![CDATA[(View==1)]]></port>
      <port model='Transfer' name='GM' x='54' y='-36' dim='1' mode='Output' type='Real'><![CDATA[(View==1)]]></port>
      <port model='Transfer' name='KB' x='54' y='54' dim='1' mode='Input' type='Integer'><![CDATA[(View==1)]]></port>
      <port model='Transfer' name='CB' x='-18' y='-90' dim='1' mode='Input' type='Integer'><![CDATA[(View==1)]]></port>
      <port model='Transfer' name='AO' x='54' y='36' dim='1' mode='Input' type='Real'><![CDATA[((FP==0)||(FP==3))&&(View==1)]]></port>
      <port model='Transfer' name='FPN' x='54' y='36' dim='6' mode='Input' type='Integer'><![CDATA[((FP==1)||(FP==2))&&(View==1)]]></port>
      <port model='Transfer' name='FDT' x='54' y='0' dim='6' mode='Input' type='Real'><![CDATA[(FP==2)&&(View==1)]]></port>
    </svg>
  </Definition>
</pslx>
"""


def _write_g6p200_master_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "master-g6p200.pslx"
    path.write_text(_g6p200_master_xml(), encoding="utf-8")
    return path


def _packaged_registry(module):
    payload = json.loads(
        (ASSET_ROOT / "master-bindings-pscad-4.6.2.json").read_text(
            encoding="utf-8"
        )
    )
    return module.parse_master_binding_registry(payload)


def _master_fixture_xml(
    *,
    duplicate_source: bool = False,
    source_a_model: str = "Natural",
    inductor_type: str = "Real",
) -> str:
    duplicate = (
        "<Definition name='source3'><svg><port model='Natural' name='A' "
        "x='0' y='0' dim='1' type='NonRemovable'/></svg></Definition>"
        if duplicate_source
        else ""
    )
    return f"""<?xml version='1.0'?>
<pslx>
  <Definition name='source3'>
    <form><category>
      <parameter name='Vm' desc='Base Voltage (L-L, RMS)' type='Real' unit='kV' intent='Input'><value>230</value></parameter>
      <parameter name='F' desc='Base Frequency' type='Real' unit='Hz' intent='Input'><value>60</value></parameter>
      <parameter name='Es' desc='Voltage Magnitude (L-L, RMS)' type='Real' unit='kV' intent='Input'><value>230</value></parameter>
      <parameter name='F0' desc='Frequency' type='Real' unit='Hz' intent='Input'><value>60</value></parameter>
      <parameter name='Ph' type='Real' unit='deg' intent='Input'><value>0</value></parameter>
      <parameter name='View' type='Choice'><value>1</value><choice>0 = 3 phase</choice><choice>1 = single</choice></parameter>
      <parameter name='Ctrl' type='Choice'><value>0</value><choice>0 = Fixed</choice><choice>2 = External</choice><choice>3 = Auto</choice></parameter>
      <parameter name='Term' type='Choice'><value>0</value><choice>0 = Behind the Source Impedance</choice><choice>1 = At the Terminal</choice></parameter>
    </category></form>
    <svg>
      <port model='{source_a_model}' name='A' x='36' y='-36' dim='1' type='NonRemovable'/>
      <port model='Natural' name='B' x='36' y='0' dim='1' type='NonRemovable'/>
      <port model='Natural' name='C' x='36' y='36' dim='1' type='NonRemovable'/>
    </svg>
  </Definition>
  {duplicate}
  <Definition name='xfmr-3p2w'>
    <form><category>
      <parameter name='Tmva' type='Real' unit='MVA' intent='Input'><value>100</value></parameter>
      <parameter name='V1' type='Real' unit='kV' intent='Input'><value>230</value></parameter>
      <parameter name='V2' type='Real' unit='kV' intent='Input'><value>230</value></parameter>
      <parameter name='f' type='Real' unit='Hz' intent='Input'><value>50</value></parameter>
      <parameter name='YD1' type='Choice'><value>0</value><choice>0 = Y</choice><choice>1 = Delta</choice></parameter>
      <parameter name='YD2' type='Choice'><value>1</value><choice>0 = Y</choice><choice>1 = Delta</choice></parameter>
      <parameter name='Lead' type='Choice'><value>1</value><choice>1 = Lags</choice><choice>2 = Leads</choice></parameter>
      <parameter name='View' type='Choice'><value>1</value><choice>0 = phase</choice><choice>1 = single</choice><choice>2 = winding</choice></parameter>
    </category></form>
    <svg>
      <port model='Natural' name='A1' x='-72' y='-36' dim='1' type='NonRemovable'/>
      <port model='Natural' name='B1' x='-72' y='0' dim='1' type='NonRemovable'/>
      <port model='Natural' name='C1' x='-72' y='36' dim='1' type='NonRemovable'/>
      <port model='Natural' name='A2' x='72' y='-36' dim='1' type='NonRemovable'/>
      <port model='Natural' name='B2' x='72' y='0' dim='1' type='NonRemovable'/>
      <port model='Natural' name='C2' x='72' y='36' dim='1' type='NonRemovable'/>
      <port model='Natural' name='G1' x='-18' y='36' dim='1' mode='Electrical' type='NonRemovable'>(YD1==0)&amp;&amp;(View!=0)</port>
      <port model='Natural' name='G2' x='0' y='36' dim='1' mode='Electrical' type='NonRemovable'>(YD2==0)&amp;&amp;(View!=0)</port>
      <port model='Natural' name='G2' x='0' y='0' dim='1' mode='Electrical' type='Ground'>(YD2==1)</port>
      <port model='Natural' name='G1' x='-18' y='0' dim='1' mode='Electrical' type='Ground'>(YD1==1)</port>
      <port model='Natural' name='G1' x='-36' y='72' dim='1' mode='Electrical' type='NonRemovable'>(YD1==0)&amp;&amp;(View==0)</port>
      <port model='Natural' name='G2' x='36' y='72' dim='1' mode='Electrical' type='NonRemovable'>(YD2==0)&amp;&amp;(View==0)</port>
    </svg>
  </Definition>
  <Definition name='cfilter'>
    <form><category>
      <parameter name='Q' type='Real' unit='MVA' intent='Input'><value>49</value></parameter>
      <parameter name='h' type='Real' unit='' intent='Input'><value>3</value></parameter>
      <parameter name='dentry' type='Choice'><value>1</value><choice>0 = RLC</choice><choice>1 = rated</choice></parameter>
      <parameter name='f0' type='Real' unit='Hz' intent='Input'><value>50</value></parameter>
      <parameter name='V' type='Real' unit='kV' intent='Input'><value>315</value></parameter>
    </category></form>
    <svg>
      <port model='Natural' name='A' x='0' y='-54' dim='0' type='NonRemovable'/>
      <port model='Natural' name='B' x='0' y='54' dim='0' type='NonRemovable'/>
      <port model='Natural' name='N' x='0' y='-36' dim='0' type='NonRemovable'/>
    </svg>
  </Definition>
  <Definition name='inductor'>
    <form><category><parameter name='L' type='{inductor_type}' unit='H' intent='Input'><value>0.1</value></parameter></category></form>
    <svg>
      <port model='Natural' name='A' x='0' y='0' dim='0' type='Removable'/>
      <port model='Natural' name='B' x='36' y='0' dim='0' type='Removable'/>
    </svg>
  </Definition>
  <Definition name='resistor'>
    <form><category><parameter name='R' type='Real' unit='ohm' intent='Input'><value>1</value></parameter></category></form>
    <svg>
      <port model='Natural' name='A' x='0' y='0' dim='0' type='Removable'/>
      <port model='Natural' name='B' x='36' y='0' dim='0' type='Removable'/>
    </svg>
  </Definition>
  <Definition name='multimeter'>
    <form><category>
      <parameter name='MeasV' type='Choice'><value>0</value><choice>0 = No</choice><choice>1 = Yes</choice></parameter>
      <parameter name='MeasI' type='Choice'><value>0</value><choice>0 = No</choice><choice>1 = Yes</choice></parameter>
      <parameter name='MeasP' type='Choice'><value>0</value><choice>0 = No</choice><choice>1 = Yes</choice></parameter>
      <parameter name='MeasQ' type='Choice'><value>0</value><choice>0 = No</choice><choice>1 = Yes</choice></parameter>
      <parameter name='Freq' type='Real' unit='Hz' intent='Input'><value>50</value></parameter>
      <parameter name='BaseV' type='Real' unit='kV' intent='Input'><value>230</value></parameter>
      <parameter name='CurI' type='Text'><value>IDC</value></parameter>
      <parameter name='VolI' type='Text'><value>VDC</value></parameter>
      <parameter name='P' type='Text'><value></value></parameter>
      <parameter name='Q' type='Text'><value></value></parameter>
    </category></form>
    <svg>
      <port model='Natural' name='A' x='-18' y='0' dim='0' type='Removable'>MeasV+MeasP+MeasQ==0</port>
      <port model='Natural' name='A' x='-18' y='0' dim='0' type='NonRemovable'>MeasV+MeasP+MeasQ!=0</port>
      <port model='Natural' name='B' x='18' y='0' dim='0' type='NonRemovable'>MeasP+MeasQ+MeasI==0</port>
      <port model='Natural' name='B' x='18' y='0' dim='0' type='Removable'>MeasP+MeasQ+MeasI!=0</port>
    </svg>
  </Definition>
  <Definition name='ground'>
    <svg><port model='Natural' name='A' x='0' y='0' dim='1' type='Ground'/></svg>
  </Definition>
  <Definition name='datalabel'>
    <form><category><parameter name='Name' type='Text'><value>IMPORT</value></parameter></category></form>
    <svg><port model='Transfer' name='A' x='0' y='0' dim='0' mode='Input' type='Real'/></svg>
  </Definition>
  <Definition name='import'>
    <form><category><parameter name='Name' type='Text'><value>IMPORT</value></parameter></category></form>
    <svg><port model='Transfer' name='N' x='36' y='0' dim='0' mode='Output' type='Real'>true</port></svg>
  </Definition>
  <Definition name='breaker1'>
    <form><category>
      <parameter name='NAME' type='Real'><value>0</value></parameter>
      <parameter name='OPCUR' type='Choice'><value>0</value><choice>0 = off</choice><choice>1 = on</choice></parameter>
      <parameter name='ENAB' type='Choice'><value>0</value><choice>0 = off</choice><choice>1 = on</choice></parameter>
      <parameter name='ViewB' type='Choice'><value>1</value><choice>0 = hidden</choice><choice>1 = shown</choice></parameter>
      <parameter name='CLVL' type='Real' unit='kA'><value>0</value></parameter>
      <parameter name='ROFF' type='Real' unit='ohm'><value>1000000</value></parameter>
      <parameter name='RON' type='Real' unit='ohm'><value>0.01</value></parameter>
      <parameter name='PostIns' type='Choice'><value>0</value><choice>0 = off</choice><choice>1 = on</choice></parameter>
      <parameter name='BOpen' type='Choice'><value>0</value><choice>0 = closed</choice><choice>2 = open</choice></parameter>
    </category></form>
    <svg>
      <port model='Natural' name='A' x='36' y='0' dim='1' type='NonRemovable'/>
      <port model='Natural' name='B' x='-36' y='0' dim='1' type='NonRemovable'/>
    </svg>
  </Definition>
  <Definition name='tfault'>
    <form><category>
      <parameter name='TF' type='Real' unit='s'><value>0.8</value></parameter>
      <parameter name='DF' type='Real' unit='s'><value>0.1</value></parameter>
      <parameter name='REP' type='Choice'><value>0</value><choice>0 = off</choice><choice>1 = on</choice></parameter>
    </category></form>
    <svg><port model='Transfer' name='Y' x='-36' y='0' dim='1' mode='Output' type='Integer'/></svg>
  </Definition>
  <Definition name='unity'>
    <form><category>
      <parameter name='IType' type='Choice'><value>2</value><choice>0 = Logical</choice><choice>1 = Integer</choice><choice>2 = Real</choice></parameter>
      <parameter name='OType' type='Choice'><value>1</value><choice>0 = Logical</choice><choice>1 = Integer (NINT)</choice><choice>2 = Real</choice><choice>3 = Integer (INT)</choice><choice>4 = Short Integer Signed</choice><choice>5 = Short Integer Unsigned</choice></parameter>
      <parameter name='Dim' type='Integer' unit=''><value>1</value></parameter>
    </category></form>
    <svg>
      <port model='Transfer' name='A:Dim' x='-36' y='0' dim='0' mode='Input' type='Real'>IType==2</port>
      <port model='Transfer' name='B:Dim' x='0' y='0' dim='0' mode='Output' type='Real'>OType==2</port>
      <port model='Transfer' name='B:Dim' x='0' y='0' dim='0' mode='Output' type='Logical'>OType==0</port>
      <port model='Transfer' name='B:Dim' x='0' y='0' dim='0' mode='Output' type='Integer'>(OType!=0)&amp;&amp;(OType!=2)</port>
      <port model='Transfer' name='A:Dim' x='-36' y='0' dim='0' mode='Input' type='Integer'>IType==1</port>
      <port model='Transfer' name='A:Dim' x='-36' y='0' dim='0' mode='Input' type='Logical'>IType==0</port>
    </svg>
  </Definition>
  <Definition name='inv'>
    <form><category>
      <parameter name='INTR' type='Choice'><value>0</value><choice>0 = Disabled</choice><choice>1 = Enabled</choice></parameter>
    </category></form>
    <svg>
      <port model='Transfer' name='IN' x='0' y='0' dim='1' mode='Input' type='Integer'>!(INTR==1)</port>
      <port model='Transfer' name='OUT' x='36' y='0' dim='1' mode='Output' type='Integer'>!(INTR==1)</port>
      <port model='Transfer' name='IN' x='0' y='0' dim='2' mode='Input' type='Real'>!(INTR==0)</port>
      <port model='Transfer' name='OUT' x='36' y='0' dim='2' mode='Output' type='Real'>!(INTR==0)</port>
    </svg>
  </Definition>
  <Definition name='pgb'>
    <form><category>
      <parameter name='Name' type='Text'><value>Untitled</value></parameter>
      <parameter name='Group' type='Text'><value></value></parameter>
      <parameter name='UseSignalName' type='Choice'><value>0</value><choice>0 = No</choice><choice>1 = Yes</choice></parameter>
      <parameter name='enab' type='Choice'><value>1</value><choice>0 = No</choice><choice>1 = Yes</choice></parameter>
      <parameter name='Display' type='Choice'><value>1</value><choice>0 = No</choice><choice>1 = Yes</choice></parameter>
      <parameter name='Scale' type='Real' unit=''><value>1.0</value></parameter>
      <parameter name='Units' type='Text'><value></value></parameter>
      <parameter name='mrun' type='Choice'><value>0</value><choice>0 = Last run only</choice><choice>1 = All runs</choice></parameter>
      <parameter name='Pol' type='Choice'><value>0</value><choice>0 = No</choice><choice>1 = Yes</choice></parameter>
      <parameter name='Max' type='Real' unit=''><value>2.0</value></parameter>
      <parameter name='Min' type='Real' unit=''><value>-2.0</value></parameter>
    </category></form>
    <svg><port model='Transfer' name='Signl' x='0' y='0' dim='0' mode='Input' type='Real'>true</port></svg>
  </Definition>
</pslx>
"""


def _write_master_fixture(tmp_path: Path, **options) -> Path:
    path = tmp_path / "master.pslx"
    path.write_text(_master_fixture_xml(**options), encoding="utf-8")
    return path


def test_schema_v2_keeps_project_and_companion_bindings_separate():
    module = _subject()
    payload = _registry_payload_v2()

    registry = module.parse_master_binding_registry(payload)

    assert len(registry.bindings) == 1
    assert registry.companion_by_logical_name[
        "master:six_pulse_bridge"
    ].physical_definition == "g6p200"
    assert registry.to_dict()["companion_bindings"] == payload[
        "companion_bindings"
    ]


def test_schema_v1_has_no_companion_bindings():
    module = _subject()

    registry = module.parse_master_binding_registry(_registry_payload())

    assert registry.schema_version == 1
    assert registry.companion_bindings == ()
    assert "companion_bindings" not in registry.to_dict()


def test_companion_logical_names_must_be_unique_and_disjoint():
    module = _subject()
    payload = _registry_payload_v2(copy.deepcopy(_minimal_binding()))

    with pytest.raises(BackendError) as failure:
        module.parse_master_binding_registry(payload)

    assert failure.value.code == "MASTER_BINDING_AMBIGUOUS"


def test_schema_v2_hash_binds_companion_records():
    module = _subject()
    first = module.parse_master_binding_registry(_registry_payload_v2())
    changed = _registry_payload_v2()
    changed["companion_bindings"][0]["fixed_parameters"][0]["value"] = 1

    second = module.parse_master_binding_registry(changed)

    assert first.sha256 != second.sha256


def test_companion_audit_selects_fp0_view1_ao_and_dc_profiles(tmp_path):
    module = _subject()
    registry = module.parse_master_binding_registry(_registry_payload_v2())

    audited = module.audit_companion_bindings(
        _write_g6p200_master_fixture(tmp_path), registry
    )

    bridge = audited.definitions["master:six_pulse_bridge"]
    selected = bridge["selected_ports"]
    assert selected["AO"]["dimension"] == 1
    assert "FP==0" in selected["AO"]["condition"]
    assert "View==1" in selected["AO"]["condition"]
    assert "FPN" not in selected
    assert "FDT" not in selected
    assert selected["DP_RECT"]["occurrence"] == 2
    assert selected["DN_RECT"]["occurrence"] == 3
    assert selected["DP_INV"]["occurrence"] == 3
    assert selected["DN_INV"]["occurrence"] == 2


def test_companion_audit_rejects_swapped_inverter_dc_profile(tmp_path):
    module = _subject()
    payload = _registry_payload_v2()
    bridge = payload["companion_bindings"][0]
    next(
        port for port in bridge["ports"] if port["logical"] == "DP_INV"
    )["occurrence"] = 2
    registry = module.parse_master_binding_registry(payload)

    with pytest.raises(BackendError) as failure:
        module.audit_companion_bindings(
            _write_g6p200_master_fixture(tmp_path), registry
        )

    assert failure.value.code == "MASTER_PORT_MISMATCH"
    assert failure.value.details["logical_port"] == "DP_INV"


def test_companion_audit_requires_six_pulse_bridge_identity(tmp_path):
    module = _subject()
    other = _g6p200_binding()
    other["logical_name"] = "master:other_bridge"
    registry = module.parse_master_binding_registry(
        _registry_payload_v2(other)
    )

    with pytest.raises(BackendError) as failure:
        module.audit_companion_bindings(
            _write_g6p200_master_fixture(tmp_path),
            registry,
        )

    assert failure.value.code == "MASTER_BINDING_MISSING"
    assert failure.value.details["logical_name"] == "master:six_pulse_bridge"


def test_registry_rejects_unknown_top_level_fields():
    module = _subject()
    payload = _registry_payload()
    payload["unexpected"] = True

    with pytest.raises(BackendError) as failure:
        module.parse_master_binding_registry(payload)

    assert failure.value.code == "MASTER_BINDING_MISSING"
    assert failure.value.details["unknown_fields"] == ["unexpected"]


def test_registry_rejects_duplicate_logical_names():
    module = _subject()
    payload = _registry_payload(_minimal_binding(), _minimal_binding())

    with pytest.raises(BackendError) as failure:
        module.parse_master_binding_registry(payload)

    assert failure.value.code == "MASTER_BINDING_AMBIGUOUS"
    assert failure.value.details["logical_name"] == "master:test"


@pytest.mark.parametrize(
    "cases",
    [
        [
            {"logical": ["A"], "physical": [0]},
            {"logical": ["A"], "physical": [1]},
        ],
        [
            {"logical": ["A"], "physical": [0]},
            {"logical": ["B"], "physical": [0]},
        ],
        [
            {"logical": [1], "physical": [0]},
            {"logical": ["1"], "physical": [1]},
        ],
        [
            {"logical": ["A"], "physical": [1]},
            {"logical": ["B"], "physical": ["1"]},
        ],
    ],
)
def test_registry_rejects_ambiguous_lookup_bundles(cases):
    module = _subject()
    binding = _minimal_binding()
    binding["parameters"][0]["transform"] = {
        "kind": "lookup_bundle",
        "cases": cases,
    }

    with pytest.raises(BackendError) as failure:
        module.parse_master_binding_registry(_registry_payload(binding))

    assert failure.value.code == "MASTER_BINDING_AMBIGUOUS"
    assert failure.value.details["field"] == "transform.cases"


@pytest.mark.parametrize(
    ("mutation", "field"),
    [
        (lambda binding: binding["ports"][0].update(dimension=0), "dimension"),
        (lambda binding: binding["ports"][0].update(occurrence=-1), "occurrence"),
        (lambda binding: binding["shape"].update(kind="unknown"), "shape.kind"),
        (
            lambda binding: binding["parameters"][0]["transform"].update(
                kind="unknown"
            ),
            "transform.kind",
        ),
    ],
)
def test_registry_rejects_invalid_port_and_transform_contracts(mutation, field):
    module = _subject()
    binding = _minimal_binding()
    mutation(binding)

    with pytest.raises(BackendError) as failure:
        module.parse_master_binding_registry(_registry_payload(binding))

    assert failure.value.code == "MASTER_BINDING_MISSING"
    assert failure.value.details["field"] == field


def test_registry_rejects_non_finite_transform_constants():
    module = _subject()
    binding = _minimal_binding()
    binding["parameters"][0]["transform"] = {
        "kind": "scale",
        "factor": float("nan"),
    }

    with pytest.raises(BackendError) as failure:
        module.parse_master_binding_registry(_registry_payload(binding))

    assert failure.value.code == "MASTER_BINDING_MISSING"
    assert failure.value.details["field"] == "transform.factor"


def test_packaged_registry_contains_exact_fixed_catalog_bindings():
    module = _subject()
    payload = json.loads(
        (ASSET_ROOT / "master-bindings-pscad-4.6.2.json").read_text(
            encoding="utf-8"
        )
    )

    registry = module.parse_master_binding_registry(payload)

    assert set(registry.by_logical_name) == {
        "master:three_phase_source",
        "master:converter_transformer",
        "master:ac_filter_branch",
        "master:smoothing_reactor",
        "master:dc_line_section",
        "master:fault_resistor",
        "master:ac_meter",
        "master:dc_meter",
        "master:ground",
        "master:main_signal_import",
        "master:signal_import",
        "master:breaker1",
        "master:tfault",
        "master:fault_state_integer_to_real",
        "master:fault_control_not",
        "master:dynamic_output_channel",
    }
    assert (
        registry.by_logical_name["master:converter_transformer"].physical_definition
        == "xfmr-3p2w"
    )
    assert (
        registry.by_logical_name["master:dc_line_section"].physical_definition
        == "resistor"
    )
    assert (
        registry.by_logical_name["master:dc_meter"].physical_definition
        == "multimeter"
    )
    assert (
        registry.by_logical_name["master:main_signal_import"].physical_definition
        == "datalabel"
    )
    assert (
        registry.by_logical_name["master:signal_import"].physical_definition
        == "import"
    )


def test_filter_expansion_offsets_are_pscad_grid_aligned():
    module = _subject()
    registry = _packaged_registry(module)
    shape = registry.by_logical_name["master:ac_filter_branch"].shape

    assert all(
        coordinate % 18 == 0
        for instance in shape["instances"]
        for coordinate in instance["offset"]
    )
    assert all(
        coordinate % 18 == 0
        for coordinate in shape["neutral"]["ground_offset"]
    )


def test_filter_expansion_is_a_shunt_with_distinct_phase_buses():
    module = _subject()
    registry = _packaged_registry(module)
    binding = registry.by_logical_name["master:ac_filter_branch"]
    instance_offsets = {
        item["name"]: tuple(item["offset"])
        for item in binding.shape["instances"]
    }
    port_offsets = {"A": (0, -54), "B": (0, 54)}
    points = {
        port.logical: (
            instance_offsets[port.instance][0] + port_offsets[port.physical][0],
            instance_offsets[port.instance][1] + port_offsets[port.physical][1],
        )
        for port in binding.ports
    }

    assert binding.shape["neutral"]["physical_port"] == "B"
    assert binding.shape["neutral"]["ground_offset"] == (54, 54)
    for phase in "ABC":
        assert points[f"IN_{phase}"] == points[f"OUT_{phase}"]
    assert len({points[f"IN_{phase}"] for phase in "ABC"}) == 3


def test_registry_hash_is_stable_for_key_order():
    module = _subject()
    payload = _registry_payload()
    reordered = {
        "bindings": payload["bindings"],
        "pscad_version": payload["pscad_version"],
        "name": payload["name"],
        "schema_version": payload["schema_version"],
    }

    first = module.parse_master_binding_registry(payload)
    second = module.parse_master_binding_registry(reordered)

    assert first.sha256 == second.sha256


def test_audit_resolves_all_packaged_bindings_and_preserves_source_hash(tmp_path):
    module = _subject()
    registry = _packaged_registry(module)
    master = _write_master_fixture(tmp_path)

    audited = module.audit_master_bindings(master, registry)

    assert audited.master_sha256 == hashlib.sha256(master.read_bytes()).hexdigest()
    assert set(audited.definitions) == set(registry.by_logical_name)
    assert audited.definitions["master:dc_line_section"]["physical_definition"] == "resistor"
    selected = audited.definitions["master:ac_meter"]["selected_ports"]
    assert selected["A"]["occurrence"] == 1
    assert selected["A"]["raw_dimension"] == 0
    assert selected["A"]["dimension"] == 1
    assert selected["A"]["kind"] == "electrical"


def test_transformer_binding_selects_primary_y_neutral_in_three_phase_view(tmp_path):
    module = _subject()
    registry = _packaged_registry(module)
    audited = module.audit_master_bindings(_write_master_fixture(tmp_path), registry)
    selected = audited.definitions["master:converter_transformer"]["selected_ports"]

    assert "HV_N" in selected
    assert selected["HV_N"]["physical"] == "G1"
    assert selected["HV_N"]["occurrence"] == 2
    assert selected["HV_N"]["kind"] == "electrical"
    assert selected["HV_N"]["dimension"] == 1
    assert selected["HV_N"]["offset"] == (-36, 72)
    assert selected["HV_N"]["condition"] == "(YD1==0)&&(View==0)"
    assert all(port["physical"] != "G2" for port in selected.values())


def test_fault_control_not_uses_native_scalar_integer_inversion(tmp_path):
    module = _subject()
    registry = _packaged_registry(module)
    audited = module.audit_master_bindings(_write_master_fixture(tmp_path), registry)
    binding = audited.resolve_component("master:fault_control_not", {})

    assert binding.physical_definition == "inv"
    assert binding.physical_parameters == {"INTR": 0}
    ports = audited.definitions["master:fault_control_not"]["selected_ports"]
    for name, offset in {"IN": (0, 0), "OUT": (36, 0)}.items():
        assert ports[name]["physical"] == name
        assert ports[name]["occurrence"] == 0
        assert ports[name]["dimension"] == 1
        assert ports[name]["type"] == "Integer"
        assert ports[name]["offset"] == offset
        assert ports[name]["condition"] == "!(INTR==1)"
    breaker = registry.by_logical_name["master:breaker1"]
    assert next(item.value for item in breaker.fixed_parameters if item.physical == "BOpen") == 2


def test_audit_rejects_duplicate_physical_definitions(tmp_path):
    module = _subject()
    registry = _packaged_registry(module)
    master = _write_master_fixture(tmp_path, duplicate_source=True)

    with pytest.raises(BackendError) as failure:
        module.audit_master_bindings(master, registry)

    assert failure.value.code == "MASTER_BINDING_AMBIGUOUS"
    assert failure.value.details["physical_definition"] == "source3"


def test_audit_rejects_wrong_port_kind_before_resolution(tmp_path):
    module = _subject()
    registry = _packaged_registry(module)
    master = _write_master_fixture(tmp_path, source_a_model="Transfer")

    with pytest.raises(BackendError) as failure:
        module.audit_master_bindings(master, registry)

    assert failure.value.code == "MASTER_PORT_MISMATCH"
    assert failure.value.details["logical_port"] == "A"
    assert failure.value.details["observed_kind"] == "data"


def test_audit_rejects_wrong_parameter_type(tmp_path):
    module = _subject()
    registry = _packaged_registry(module)
    master = _write_master_fixture(tmp_path, inductor_type="Text")

    with pytest.raises(BackendError) as failure:
        module.audit_master_bindings(master, registry)

    assert failure.value.code == "MASTER_PARAMETER_MISMATCH"
    assert failure.value.details["physical_parameter"] == "L"
    assert failure.value.details["expected_type"] == "Real"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("ground_definition", "missing_ground", "MASTER_BINDING_MISSING"),
        ("ground_port", "MISSING", "MASTER_BINDING_MISSING"),
        ("ground_occurrence", 99, "MASTER_BINDING_AMBIGUOUS"),
    ],
)
def test_audit_rejects_invalid_filter_ground_contract(
    tmp_path,
    field,
    value,
    code,
):
    module = _subject()
    payload = json.loads(
        (ASSET_ROOT / "master-bindings-pscad-4.6.2.json").read_text(
            encoding="utf-8"
        )
    )
    filter_binding = next(
        item
        for item in payload["bindings"]
        if item["logical_name"] == "master:ac_filter_branch"
    )
    filter_binding["shape"]["neutral"][field] = value
    registry = module.parse_master_binding_registry(payload)

    with pytest.raises(BackendError) as failure:
        module.audit_master_bindings(
            _write_master_fixture(tmp_path),
            registry,
        )

    assert failure.value.code == code
    assert failure.value.details["ground_definition"] == filter_binding["shape"][
        "neutral"
    ]["ground_definition"]


@pytest.mark.parametrize(
    ("logical_name", "physical_parameter", "invalid_value"),
    [
        ("master:three_phase_source", "View", 999),
        ("master:converter_transformer", "YD2", 999),
    ],
)
def test_audit_rejects_fixed_or_lookup_values_outside_live_contract(
    tmp_path,
    logical_name,
    physical_parameter,
    invalid_value,
):
    module = _subject()
    payload = json.loads(
        (ASSET_ROOT / "master-bindings-pscad-4.6.2.json").read_text(
            encoding="utf-8"
        )
    )
    binding = next(
        item for item in payload["bindings"] if item["logical_name"] == logical_name
    )
    fixed = next(
        (
            item
            for item in binding["fixed_parameters"]
            if item["physical"] == physical_parameter
        ),
        None,
    )
    if fixed is not None:
        fixed["value"] = invalid_value
    else:
        parameter = next(
            item
            for item in binding["parameters"]
            if physical_parameter in item["physical"]
        )
        index = parameter["physical"].index(physical_parameter)
        parameter["transform"]["cases"][0]["physical"][index] = invalid_value
    registry = module.parse_master_binding_registry(payload)

    with pytest.raises(BackendError) as failure:
        module.audit_master_bindings(
            _write_master_fixture(tmp_path),
            registry,
        )

    assert failure.value.code == "MASTER_PARAMETER_MISMATCH"
    assert failure.value.details["physical_parameter"] == physical_parameter


def test_resolver_uses_active_source_values_and_fixed_bases(tmp_path):
    module = _subject()
    audited = module.audit_master_bindings(
        _write_master_fixture(tmp_path), _packaged_registry(module)
    )
    requested = {"Amplitude_kV": 345.0, "Frequency_Hz": 47.5, "Phase_deg": 12.0}
    resolved = audited.resolve_component("master:three_phase_source", requested)

    assert resolved.physical_parameters == {
        "Es": 345.0,
        "F0": 47.5,
        "Ph": 12.0,
        "Vm": 230.0,
        "F": 50.0,
        "View": 0,
        "Ctrl": 0,
        "Term": 0,
    }
    assert resolved.logical_parameters(resolved.physical_parameters) == requested


def test_resolver_round_trips_reactor_transform(tmp_path):
    module = _subject()
    audited = module.audit_master_bindings(
        _write_master_fixture(tmp_path), _packaged_registry(module)
    )

    resolved = audited.resolve_component(
        "master:smoothing_reactor", {"Inductance_mH": 100.0}
    )

    assert resolved.physical_definition == "inductor"
    assert resolved.physical_parameters == {"L": pytest.approx(0.1)}
    assert resolved.logical_parameters({"L": 0.1}) == {
        "Inductance_mH": pytest.approx(100.0)
    }


def test_resolver_maps_transformer_lookup_and_fixed_voltage_base(tmp_path):
    module = _subject()
    audited = module.audit_master_bindings(
        _write_master_fixture(tmp_path), _packaged_registry(module)
    )

    resolved = audited.resolve_component(
        "master:converter_transformer",
        {"Ratio": 1.0, "Rating_MVA": 325.2691193458119, "Connection": "Y-delta", "PhaseShift_deg": 30.0},
    )

    assert resolved.physical_parameters == {
        "Tmva": 325.2691193458119,
        "V1": 230.0,
        "V2": 230.0,
        "f": 50.0,
        "View": 0,
        "YD1": 0,
        "YD2": 1,
        "Lead": 1,
    }
    assert resolved.logical_parameters(
        {"Tmva": 325.2691193458119, "V2": 230.0, "YD1": 0, "YD2": 1, "Lead": 1}
    ) == {
        "Rating_MVA": 325.2691193458119,
        "Ratio": 1.0,
        "Connection": "Y-delta",
        "PhaseShift_deg": 30.0,
    }


def test_resolver_rejects_unreviewed_transformer_tuple(tmp_path):
    module = _subject()
    audited = module.audit_master_bindings(
        _write_master_fixture(tmp_path), _packaged_registry(module)
    )

    with pytest.raises(BackendError) as failure:
        audited.resolve_component(
            "master:converter_transformer",
            {"Ratio": 1.0, "Rating_MVA": 325.2691193458119, "Connection": "Y-delta", "PhaseShift_deg": -30.0},
        )

    assert failure.value.code == "MASTER_TRANSFORM_UNSUPPORTED"


def test_filter_resolution_is_per_phase_and_uses_harmonic_order(tmp_path):
    module = _subject()
    audited = module.audit_master_bindings(
        _write_master_fixture(tmp_path), _packaged_registry(module)
    )

    resolved = audited.resolve_component(
        "master:ac_filter_branch",
        {"Branch_MVAR": 50.0, "Tuning_Hz": 300.0},
    )

    assert resolved.instances == ("A", "B", "C")
    assert resolved.physical_parameters["Q"] == pytest.approx(50.0 / 3.0)
    assert resolved.physical_parameters["f0"] == 50.0
    assert resolved.physical_parameters["h"] == 6.0
    assert resolved.logical_parameters({"Q": 50.0 / 3.0, "h": 6.0}) == {
        "Branch_MVAR": pytest.approx(50.0),
        "Tuning_Hz": pytest.approx(300.0),
    }


def test_line_length_is_explicit_evidence_not_a_physical_parameter(tmp_path):
    module = _subject()
    audited = module.audit_master_bindings(
        _write_master_fixture(tmp_path), _packaged_registry(module)
    )

    resolved = audited.resolve_component(
        "master:dc_line_section",
        {"Length_km": 300.0, "Resistance_ohm": 10.0},
    )

    assert resolved.physical_definition == "resistor"
    assert resolved.physical_parameters == {"R": 10.0}
    assert resolved.evidence_parameters == {"Length_km": 300.0}
    assert resolved.logical_parameters({"R": 10.0}) == {
        "Resistance_ohm": 10.0,
        "Length_km": 300.0,
    }
