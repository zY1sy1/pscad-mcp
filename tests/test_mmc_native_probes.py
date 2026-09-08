from itertools import pairwise
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.native_probes import (
    _ProbeWriter,
    materialize_native_fault_probes,
)


def _sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "source.pscx"
    project.write_text(
        """<project name="source" version="4.6.2"><definitions>
      <Definition name="Main"><schematic>
        <User classid="UserCmp" id="1" defn="master:fault_sw" x="90" y="90" orient="0"><paramlist><param name="Name" value="DC_flt_Mid"/><param name="Iflt" value="IFlt_Mid"/></paramlist></User>
        <User classid="UserCmp" id="2" defn="master:nodelabel" x="90" y="180"><paramlist><param name="Name" value="T1P"/></paramlist></User>
        <User classid="UserCmp" id="3" defn="master:nodelabel" x="90" y="270"><paramlist><param name="Name" value="T1N"/></paramlist></User>
        <User classid="UserCmp" id="4" defn="master:nodelabel" x="360" y="180"><paramlist><param name="Name" value="T2P"/></paramlist></User>
        <User classid="UserCmp" id="5" defn="master:nodelabel" x="360" y="270"><paramlist><param name="Name" value="T2N"/></paramlist></User>
      </schematic></Definition>
      <Definition name="MMC_Hb_Pole_PWM"><schematic>
        <User classid="UserCmp" id="6" defn="intermediate:FullCellR_n" x="846" y="396" orient="0"/>
        <User classid="UserCmp" id="7" defn="intermediate:FullCellR_n" x="846" y="684" orient="0"/>
        <User classid="UserCmp" id="8" defn="intermediate:FiringHBridge" x="2178" y="1368" orient="0"/>
        <User classid="UserCmp" id="9" defn="intermediate:FiringHBridge" x="2178" y="1818" orient="0"/>
      </schematic></Definition>
    </definitions></project>""",
        encoding="utf-8",
    )
    root = ET.parse(project).getroot()
    pole = root.find(".//Definition[@name='MMC_Hb_Pole_PWM']/schematic")
    for index, (x, y) in enumerate(
        (
            (846, 342),
            (846, 432),
            (900, 378),
            (846, 630),
            (846, 720),
            (900, 666),
            (2196, 1440),
            (2196, 1890),
        )
    ):
        wire = ET.SubElement(
            pole,
            "Wire",
            {"classid": "Wire", "id": str(100 + index), "x": str(x), "y": str(y)},
        )
        ET.SubElement(wire, "vertex", {"x": "0", "y": "0"})
        ET.SubElement(wire, "vertex", {"x": "18", "y": "0"})
    ET.ElementTree(root).write(project)
    master = tmp_path / "master.pslx"
    master.write_text(
        """<project name="master" version="4.6.2"><definitions>
      <Definition name="fault_sw"><svg><port name="A" model="Natural" x="0" y="0" dim="1">true</port><port name="B" model="Natural" x="36" y="0" dim="1">true</port></svg></Definition>
      <Definition name="nodelabel"><svg><port name="A" model="Natural" x="0" y="0" dim="0">true</port></svg></Definition>
      <Definition name="voltmeter"><svg><port name="N1" model="Natural" x="0" y="0" dim="0">true</port><port name="N2" model="Natural" x="0" y="36" dim="0">true</port></svg></Definition>
      <Definition name="pgb"><svg><port name="Signl" model="Transfer" x="0" y="0" dim="0">true</port></svg></Definition>
      <Definition name="datalabel"><svg><port name="A" model="Transfer" x="0" y="0" dim="0">true</port></svg></Definition>
    </definitions></project>""",
        encoding="utf-8",
    )
    library = tmp_path / "intermediate.pslx"
    library.write_text(
        """<project name="intermediate" version="4.6.2"><definitions>
      <Definition name="FullCellR_n"><form><parameter name="SumVc0" type="Real" unit="kV"><value>640</value></parameter></form><svg><port name="Ntop" model="Natural" x="0" y="-54" dim="1">true</port><port name="Nbtm" model="Natural" x="0" y="36" dim="1">true</port><port name="Vc:DimC" model="Transfer" x="54" y="-18" dim="0">true</port></svg></Definition>
      <Definition name="FiringHBridge"><svg><port name="Block" model="Transfer" x="18" y="72" dim="1">true</port></svg></Definition>
    </definitions></project>""",
        encoding="utf-8",
    )
    return project, master, library


def test_native_probes_measure_physical_terminals_and_gate_inputs(
    tmp_path: Path,
) -> None:
    source, master, library = _sources(tmp_path)
    before = {path: path.read_bytes() for path in (source, master, library)}
    target = tmp_path / "probed.pscx"

    report = materialize_native_fault_probes(
        source, target, master_path=master, library_path=library
    )

    assert all(path.read_bytes() == payload for path, payload in before.items())
    root = ET.parse(target).getroot()
    identifiers = [item.get("id") for item in root.iter() if item.get("id")]
    assert len(identifiers) == len(set(identifiers))
    probes = {probe["name"]: probe for probe in report["probes"]}
    assert probes["MMC_V_INSERTED_TOP"]["terminals"] == [[846, 342], [846, 432]]
    assert probes["MMC_V_INSERTED_TOP"]["polarity"] == "Ntop_minus_Nbtm"
    assert probes["MMC_BLOCKED_TOP"]["source_point"] == [2196, 1440]
    assert probes["MMC_BLOCKED_TOP"]["active_value"] == 1
    assert probes["MMC_VCAP_TOP"]["source_point"] == [900, 378]
    assert probes["MMC_VCAP_TOP"]["dimension"] == "DimC"
    assert probes["MMC_DC_FAULT_ACTIVE"]["source_signal"] == "DC_flt_Mid"
    assert probes["MMC_DC_FAULT_CURRENT"]["units"] == "kA"
    assert probes["MMC_VDC_T1"]["terminals"] == [[90, 180], [90, 270]]
    assert report["source_sha256_before"] == report["source_sha256_after"]


def test_native_probes_reject_changed_port_contract(tmp_path: Path) -> None:
    source, master, library = _sources(tmp_path)
    root = ET.parse(library).getroot()
    root.find(".//port[@name='Ntop']").set("x", "18")
    ET.ElementTree(root).write(library)
    target = tmp_path / "probed.pscx"

    with pytest.raises(BackendError) as raised:
        materialize_native_fault_probes(
            source, target, master_path=master, library_path=library
        )

    assert raised.value.code == "MMC_PROBE_SOURCE_MISMATCH"
    assert not target.exists()


def test_native_probes_use_official_library_port_profile(tmp_path: Path) -> None:
    source, master, library = _sources(tmp_path)
    root = ET.parse(library).getroot()
    root.find(".//port[@name='Nbtm']").set("y", "54")
    root.find(".//port[@name='Block']").set("x", "0")
    ET.ElementTree(root).write(library)
    project = ET.parse(source)
    for wire in project.findall(".//Wire"):
        if wire.get("id") in {"101", "104"}:
            wire.set("y", str(int(wire.get("y")) + 18))
        if wire.get("id") in {"106", "107"}:
            wire.set("x", str(int(wire.get("x")) - 18))
    project.write(source)

    result = materialize_native_fault_probes(
        source, tmp_path / "probed.pscx", master_path=master, library_path=library
    )

    probes = {probe["name"]: probe for probe in result["probes"]}
    assert probes["MMC_V_INSERTED_TOP"]["terminals"] == [[846, 342], [846, 450]]
    assert probes["MMC_BLOCKED_TOP"]["source_point"] == [2178, 1440]
    assert result["library_port_profile"] == "official_462"


def test_native_probes_reject_a_mismatched_project_library_pair(tmp_path: Path) -> None:
    source, master, library = _sources(tmp_path)
    root = ET.parse(library).getroot()
    root.find(".//port[@name='Nbtm']").set("y", "54")
    root.find(".//port[@name='Block']").set("x", "0")
    ET.ElementTree(root).write(library)
    target = tmp_path / "probed.pscx"

    with pytest.raises(BackendError) as raised:
        materialize_native_fault_probes(
            source, target, master_path=master, library_path=library
        )

    assert raised.value.code == "MMC_PROBE_SOURCE_MISMATCH"
    assert not target.exists()


def test_native_probes_accept_audited_461_library_with_462_project(
    tmp_path: Path,
) -> None:
    source, master, library = _sources(tmp_path)
    root = ET.parse(library).getroot()
    root.set("version", "4.6.1")
    ET.ElementTree(root).write(library)

    result = materialize_native_fault_probes(
        source, tmp_path / "probed.pscx", master_path=master, library_path=library
    )

    assert result["library_xml_version"] == "4.6.1"
    assert result["library_port_profile"] == "historical_derived_462"


def _contains(left: tuple, right: tuple, point: tuple) -> bool:
    return (
        left[0] == right[0] == point[0]
        and min(left[1], right[1]) <= point[1] <= max(left[1], right[1])
    ) or (
        left[1] == right[1] == point[1]
        and min(left[0], right[0]) <= point[0] <= max(left[0], right[0])
    )


def test_native_probe_routes_do_not_short_stations_or_mix_signal_and_power(
    tmp_path: Path,
) -> None:
    source, master, library = _sources(tmp_path)
    target = tmp_path / "probed.pscx"
    materialize_native_fault_probes(
        source, target, master_path=master, library_path=library
    )
    root = ET.parse(target).getroot()

    def new_wires(canvas_name):
        for wire in root.findall(
            f".//Definition[@name='{canvas_name}']/schematic/Wire"
        ):
            if int(wire.get("id", "0")) >= 1_800_000_000:
                x, y = int(wire.get("x")), int(wire.get("y"))
                yield [
                    (x + int(v.get("x")), y + int(v.get("y")))
                    for v in wire.findall("vertex")
                ]

    for vertices in new_wires("Main"):
        if (90, 180) in vertices or (90, 270) in vertices:
            for left, right in pairwise(vertices):
                assert not _contains(left, right, (360, 180))
                assert not _contains(left, right, (360, 270))
    pole = root.find(".//Definition[@name='MMC_Hb_Pole_PWM']")
    natural = [
        (int(node.get("x")), int(node.get("y")) + dy)
        for node in pole.findall(".//User[@defn='master:voltmeter']")
        for dy in (0, 36)
    ]
    for vertices in new_wires("MMC_Hb_Pole_PWM"):
        if (900, 378) in vertices or (900, 666) in vertices:
            for left, right in pairwise(vertices):
                assert not any(_contains(left, right, point) for point in natural)
                assert not _contains(left, right, (990, 378))
                assert not _contains(left, right, (990, 666))


@pytest.mark.parametrize("obstacle", ["port", "wire", "diagonal_wire"])
def test_native_probes_reject_foreign_contacts_before_writing(
    tmp_path: Path, obstacle: str
) -> None:
    source, master, library = _sources(tmp_path)
    root = ET.parse(source).getroot()
    pole = root.find(".//Definition[@name='MMC_Hb_Pole_PWM']/schematic")
    if obstacle == "port":
        ET.SubElement(
            pole,
            "User",
            {
                "classid": "UserCmp",
                "defn": "master:pgb",
                "id": "400",
                "x": "720",
                "y": "342",
                "orient": "0",
            },
        )
    else:
        wire = ET.SubElement(
            pole, "Wire", {"classid": "Wire", "id": "400", "x": "800", "y": "324"}
        )
        ET.SubElement(wire, "vertex", {"x": "0", "y": "0"})
        ET.SubElement(
            wire,
            "vertex",
            {"x": "18" if obstacle == "diagonal_wire" else "0", "y": "36"},
        )
    ET.ElementTree(root).write(source)
    target = tmp_path / "probed.pscx"

    with pytest.raises(BackendError) as raised:
        materialize_native_fault_probes(
            source, target, master_path=master, library_path=library
        )

    assert raised.value.code == "MMC_PROBE_SOURCE_MISMATCH"
    assert not target.exists()


def test_probe_route_guard_rejects_crossing_between_new_routes() -> None:
    root = ET.fromstring(
        '<project name="case"><definitions><Definition name="Main"><schematic/></Definition></definitions></project>'
    )
    canvas = root.find(".//schematic")
    writer = _ProbeWriter(root)
    writer.wire(canvas, [(0, 0), (0, 36)], kind="electrical")
    writer.wire(canvas, [(-18, 18), (18, 18)], kind="data")

    with pytest.raises(BackendError) as raised:
        writer.verify_routes(root, {})

    assert raised.value.code == "MMC_PROBE_SOURCE_MISMATCH"


def test_native_probes_refuse_source_overwrite(tmp_path: Path) -> None:
    source, master, library = _sources(tmp_path)
    before = source.read_bytes()

    with pytest.raises(BackendError) as raised:
        materialize_native_fault_probes(
            source, source, master_path=master, library_path=library
        )

    assert raised.value.code == "MMC_BUILD_CONFLICT"
    assert source.read_bytes() == before
