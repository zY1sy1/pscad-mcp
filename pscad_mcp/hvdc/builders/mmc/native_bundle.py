"""Native PSCAD library and two-station AVM integration fixture."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree as ET

from ....core.definition_metadata import read_definition_metadata_document
from .avm_companion import (
    AverageArmParameters,
    _audit_master,
    _definition,
    _make_library,
    _project,
    _script,
    _sha,
    _write_new,
    _Writer,
)
from .cable_companion import (
    DEFAULT_DONOR,
    DEFAULT_MASTER,
    append_native_cable_link,
)

NATIVE_SCOPE = "cigre_mmc_avm_v1"
CONTROL_NAME = "MMCStationModulator"
CONTROL_OUTPUTS = (
    "M_A_UPPER",
    "M_A_LOWER",
    "M_B_UPPER",
    "M_B_LOWER",
    "M_C_UPPER",
    "M_C_LOWER",
    "BLOCK",
    "SEQUENCE",
)
CONTROL_DEFAULTS = {
    "Frequency_Hz": 60.0,
    "Modulation_Index": 0.82,
    "Phase_Offset_Deg": 0.0,
    "Deblock_Time_s": 0.10,
    "Reversal_Time_s": 0.30,
}
FIXTURE_CHANNELS = {
    "P_VDC": "kV",
    "V_VDC": "kV",
    "P_A_UPPER_I": "kA",
    "P_A_UPPER_W": "MJ",
    "V_A_UPPER_I": "kA",
    "V_A_UPPER_W": "MJ",
    "P_SEQUENCE": "1",
    "V_SEQUENCE": "1",
}


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _station_control(root: ET.Element) -> ET.Element:
    ports = {
        name: (72, -126 + index * 36, "Transfer", "Output")
        for index, name in enumerate(CONTROL_OUTPUTS)
    }
    control = _definition(root, CONTROL_NAME, ports, CONTROL_DEFAULTS)
    control.find("./paramlist/param[@name='Description']").set(
        "value", "Native scheduled six-arm modulation and blocking"
    )
    _script(
        control,
        "Checks",
        "ERROR Frequency must be positive : Frequency_Hz > 0\n"
        "ERROR Modulation must stay below unity : Modulation_Index >= 0 && Modulation_Index < 1\n"
        "ERROR Reversal must follow deblock : Reversal_Time_s > Deblock_Time_s\n",
    )
    _script(
        control,
        "Fortran",
        """#LOCAL REAL ANGLE
#LOCAL REAL OFFSET
#LOCAL REAL MA
#LOCAL REAL MB
#LOCAL REAL MC
      OFFSET = $Phase_Offset_Deg * 0.0174532925199433
      IF (TIME .GE. $Reversal_Time_s) OFFSET = -OFFSET
      ANGLE = 6.28318530717959 * $Frequency_Hz * TIME + OFFSET
      MA = $Modulation_Index * SIN(ANGLE)
      MB = $Modulation_Index * SIN(ANGLE - 2.09439510239320)
      MC = $Modulation_Index * SIN(ANGLE + 2.09439510239320)
      $M_A_UPPER = 0.5 * (1.0 - MA)
      $M_A_LOWER = 0.5 * (1.0 + MA)
      $M_B_UPPER = 0.5 * (1.0 - MB)
      $M_B_LOWER = 0.5 * (1.0 + MB)
      $M_C_UPPER = 0.5 * (1.0 - MC)
      $M_C_LOWER = 0.5 * (1.0 + MC)
      $BLOCK = 0.0
      $SEQUENCE = 2.0
      IF (TIME .LT. $Deblock_Time_s) THEN
        $BLOCK = 1.0
        $SEQUENCE = 1.0
      ELSEIF (TIME .GE. $Reversal_Time_s) THEN
        $SEQUENCE = 3.0
      ENDIF
""",
    )
    return control


def _copy_constants(added: dict, destination: Path) -> dict[str, str]:
    destination.mkdir(parents=True, exist_ok=False)
    hashes = {}
    evidence = Path(added["constants"]["evidence_path"])
    for filename, expected in added["constants"]["produced_files"].items():
        source = evidence.parent / filename
        target = destination / filename
        shutil.copy2(source, target)
        if _hash(target) != expected:
            raise ValueError("Copied native cable artifact differs from its receipt")
        hashes[str(target.resolve())] = expected
    receipt = destination / "evidence.json"
    shutil.copy2(evidence, receipt)
    hashes[str(receipt.resolve())] = _hash(receipt)
    return hashes


def materialize_native_avm_library(
    destination: str | Path,
    *,
    constants_evidence: str | Path,
    master_path: str | Path = DEFAULT_MASTER,
    source_project: str | Path = DEFAULT_DONOR,
) -> dict:
    """Create the physical arm, modulator and cable in one native library."""
    target = Path(destination).resolve()
    if target.exists() or target.is_symlink():
        raise FileExistsError("Native AVM library destination must be new")
    master = Path(master_path).resolve()
    source = Path(source_project).resolve()
    metadata, master_hash, defaults = _audit_master(master)
    root, arm_writer = _make_library(metadata, defaults, scope=NATIVE_SCOPE)
    _station_control(root)
    evidence = Path(constants_evidence).resolve()
    constants_name = Path(
        json.loads(evidence.read_text(encoding="utf-8"))["constants_path"]
    ).name
    constants_path = target.parent / "constants" / constants_name
    added = append_native_cable_link(
        root,
        constants_evidence=evidence,
        source_project=source,
        master_path=master,
        local_constants=constants_path,
    )
    delivered_constants = _copy_constants(added, constants_path.parent)
    library_hash = _write_new(target, root)
    if _hash(master) != master_hash:
        raise ValueError("Master changed while materializing the native AVM library")
    return {
        "schema_version": 1,
        "scope": "native_mmc_avm_library",
        "library_path": str(target),
        "library_sha256": library_hash,
        "master_path": str(master),
        "master_sha256": master_hash,
        "source_project": str(source),
        "source_hashes": added["input_hashes"],
        "constants_path": str(constants_path),
        "constants_sha256": added["constants"]["constants_sha256"],
        "constants_receipt": str(evidence),
        "constants_artifacts": delivered_constants,
        "cable_name": added["constants"]["segment"],
        "cable_length_km": added["constants"]["length_km"],
        "cable_configuration_id": added["configuration"].get("id"),
        "cable_topology": {
            "module_wires": added["module_wires"],
            "source_definition_receipts": added["source_definition_receipts"],
            "geometry_semantics_sha256": added["geometry_semantics_sha256"],
        },
        "arm_topology": {
            "electrical_nets": {
                name: dict(nets) for name, nets in arm_writer.nets.items()
            },
            "routes": arm_writer.routes,
        },
        "control": {
            "definition": f"{NATIVE_SCOPE}:{CONTROL_NAME}",
            "kind": "scheduled_open_loop",
            "outputs": list(CONTROL_OUTPUTS),
        },
        "model_accepted": False,
    }


def _source_parameters(name: str, voltage_kv: float, frequency_hz: float) -> dict:
    return {
        "Name": name,
        "View": "1",
        "Type": "3",
        "Ctrl": "0",
        "MVA": "1000.0 [MVA]",
        "Vm": f"{voltage_kv} [kV]",
        "F": f"{frequency_hz} [Hz]",
        "Tc": "0.05 [s]",
        "ZSeq": "0",
        "Imp": "1",
        "Term": "0",
        "Z1": "20.0 [ohm]",
        "Phi1": "84.2894068625 [deg]",
        "Es": f"{voltage_kv} [kV]",
        "F0": f"{frequency_hz} [Hz]",
        "Ph": "0.0 [deg]",
    }


def _transformer_parameters(name: str, voltage_kv: float, frequency_hz: float) -> dict:
    return {
        "Name": name,
        "Tmva": "1200.0 [MVA]",
        "f": f"{frequency_hz} [Hz]",
        "YD1": "0",
        "YD2": "1",
        "Lead": "1",
        "Xl": "0.15 [pu]",
        "Ideal": "0",
        "NLL": "0.005 [pu]",
        "CuL": "0.005 [pu]",
        "View": "1",
        "V1": f"{voltage_kv} [kV]",
        "V2": f"{voltage_kv} [kV]",
        "Sat": "0",
    }


def _hierarchy_call(
    parent: ET.Element, component: ET.Element, *, z: int, instance: int
) -> ET.Element:
    return ET.SubElement(
        parent,
        "call",
        {
            "link": component.get("id"),
            "name": component.get("defn"),
            "z": str(z),
            "view": "false",
            "instance": str(instance),
        },
    )


def materialize_native_avm_fixture(
    destination: str | Path,
    *,
    constants_evidence: str | Path,
    master_path: str | Path = DEFAULT_MASTER,
    source_project: str | Path = DEFAULT_DONOR,
    frequency_hz: float = 60.0,
    ac_voltage_kv: float = 230.0,
    arm_parameters: AverageArmParameters | None = None,
) -> dict:
    """Create a complete two-station, twelve-arm native integration fixture."""
    folder = Path(destination).resolve()
    if folder.exists() or folder.is_symlink():
        raise FileExistsError("Native AVM fixture directory must be new")
    for value, name in (
        (frequency_hz, "frequency_hz"),
        (ac_voltage_kv, "ac_voltage_kv"),
    ):
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    folder.mkdir(parents=True)
    library = folder / f"{NATIVE_SCOPE}.pslx"
    library_receipt = materialize_native_avm_library(
        library,
        constants_evidence=constants_evidence,
        master_path=master_path,
        source_project=source_project,
    )
    master_metadata, master_hash, master_defaults = _audit_master(
        Path(master_path).resolve()
    )
    library_metadata = read_definition_metadata_document(library.read_bytes())
    project_name = "mmc_native_avm_fixture"
    root = _project(project_name, library=False)
    settings = root.find("./paramlist[@name='Settings']")
    for name, value in {
        "time_duration": "0.5",
        "time_step": "20",
        "sample_step": "100",
        "PlotType": "1",
        "StartType": "0",
        "output_filename": project_name + ".out",
    }.items():
        settings.find(f"param[@name='{name}']").set("value", value)
    writer = _Writer(
        root,
        master_metadata,
        master_defaults,
        {NATIVE_SCOPE: library_metadata},
    )
    main = root.find("./definitions/Definition[@name='Main']")
    hierarchy = root.find("./hierarchy/call/call")
    custom: list[tuple[ET.Element, str]] = []
    arm_values = asdict(arm_parameters or AverageArmParameters(L_arm_H=0.1))

    for station, prefix, phase_offset in (
        ("P", "P", 5.0),
        ("VDC", "V", 0.0),
    ):
        source = writer.add(
            main,
            prefix + "_source",
            "master:source3",
            _source_parameters(prefix + "_SOURCE", ac_voltage_kv, frequency_hz),
            {"N3": prefix + "_GRID", "N": "GND"},
        )
        transformer = writer.add(
            main,
            prefix + "_transformer",
            "master:xfmr-3p2w",
            _transformer_parameters(prefix + "_XFMR", ac_voltage_kv, frequency_hz),
            {
                "N1": prefix + "_GRID",
                "N2": prefix + "_VALVE_VECTOR",
                "G1": "GND",
            },
        )
        writer.add(
            main,
            prefix + "_breakout",
            "master:breakout",
            {"Com": "0", "Dis": "0"},
            {
                "N": prefix + "_VALVE_VECTOR",
                "N1": prefix + "_PHASE_A",
                "N2": prefix + "_PHASE_B",
                "N3": prefix + "_PHASE_C",
            },
        )
        control = writer.add(
            main,
            prefix + "_modulator",
            f"{NATIVE_SCOPE}:{CONTROL_NAME}",
            {
                **CONTROL_DEFAULTS,
                "Frequency_Hz": frequency_hz,
                "Phase_Offset_Deg": phase_offset,
            },
            {name: prefix + "_" + name for name in CONTROL_OUTPUTS},
        )
        custom.append((control, CONTROL_NAME))
        for phase in "ABC":
            for position in ("UPPER", "LOWER"):
                role = f"{prefix}_{phase}_{position}"
                inputs = (
                    (prefix + "_DC_POS", prefix + "_PHASE_" + phase)
                    if position == "UPPER"
                    else (prefix + "_PHASE_" + phase, prefix + "_DC_NEG")
                )
                arm = writer.add(
                    main,
                    role,
                    f"{NATIVE_SCOPE}:MMCAverageArm",
                    arm_values,
                    {
                        "IN": inputs[0],
                        "OUT": inputs[1],
                        "M": prefix + f"_M_{phase}_{position}",
                        "BLOCK": prefix + "_BLOCK",
                        "V_INSERTED": role + "_V",
                        "I_ARM": role + "_I",
                        "ENERGY": role + "_W",
                        "V_CAP_EQ": role + "_VCAP",
                    },
                )
                custom.append((arm, "MMCAverageArm"))
        if source is None or transformer is None:
            raise ValueError(f"Native station {station} instances were not authored")

    cable = writer.add(
        main,
        "DC_CABLE",
        f"{NATIVE_SCOPE}:MMCCableLink",
        {},
        {
            "SEND_POS": "P_DC_POS",
            "SEND_NEG": "P_DC_NEG",
            "RECV_POS": "V_DC_POS",
            "RECV_NEG": "V_DC_NEG",
        },
    )
    custom.append((cable, "MMCCableLink"))
    writer.add(main, "neutral_ground", "master:ground", {}, {"A": "GND"})
    for prefix in ("P", "V"):
        writer.add(
            main,
            prefix + "_vdc_meter",
            "master:voltmeter",
            {"Name": prefix + "_VDC"},
            {"N1": prefix + "_DC_POS", "N2": prefix + "_DC_NEG"},
        )
    selected_signals = {
        "P_VDC": "P_VDC",
        "V_VDC": "V_VDC",
        "P_A_UPPER_I": "P_A_UPPER_I",
        "P_A_UPPER_W": "P_A_UPPER_W",
        "V_A_UPPER_I": "V_A_UPPER_I",
        "V_A_UPPER_W": "V_A_UPPER_W",
        "P_SEQUENCE": "P_SEQUENCE",
        "V_SEQUENCE": "V_SEQUENCE",
    }
    for name, signal in selected_signals.items():
        writer.add(
            main,
            "probe_" + name,
            "master:pgb",
            {
                "Name": name,
                "Units": FIXTURE_CHANNELS[name],
                "Group": "MMC_NATIVE",
                "UseSignalName": "0",
                "enab": "1",
                "Display": "1",
                "Scale": "1.0",
                "mrun": "0",
                "Pol": "0",
                "Max": "1000.0",
                "Min": "-1000.0",
            },
            {"Signl": signal},
        )
    writer.verify()
    arm_instances = {
        "P_A_UPPER": 0,
        "P_A_LOWER": 1,
        "P_B_UPPER": 2,
        "P_B_LOWER": 3,
        "P_C_UPPER": 11,
        "P_C_LOWER": 5,
        "V_A_UPPER": 4,
        "V_A_LOWER": 10,
        "V_B_UPPER": 6,
        "V_B_LOWER": 7,
        "V_C_UPPER": 8,
        "V_C_LOWER": 9,
    }
    for index, (component, definition) in enumerate(custom, start=1):
        if definition == CONTROL_NAME:
            continue
        call = _hierarchy_call(
            hierarchy,
            component,
            z=index * 10,
            instance=(arm_instances[component.get("name")] if definition == "MMCAverageArm" else 0),
        )
        if definition == "MMCCableLink":
            ET.SubElement(
                call,
                "call",
                {
                    "link": library_receipt["cable_configuration_id"],
                    "name": f"{NATIVE_SCOPE}:Cable2",
                    "z": "-1",
                    "view": "false",
                    "instance": "0",
                },
            )
    project = folder / (project_name + ".pscx")
    project_hash = _write_new(project, root)
    receipt = {
        "schema_version": 1,
        "scope": "native_two_station_twelve_arm_avm_fixture",
        "project_name": project_name,
        "project_path": str(project),
        "project_sha256": project_hash,
        "library": library_receipt,
        "master_sha256": master_hash,
        "parameters": {
            "frequency_hz": frequency_hz,
            "ac_voltage_kv": ac_voltage_kv,
            "arm": arm_values,
        },
        "electrical_nets": {name: dict(nets) for name, nets in writer.nets.items()},
        "routes": writer.routes,
        "channels": FIXTURE_CHANNELS,
        "control_kind": "scheduled_open_loop",
        "model_accepted": False,
        "licensed_acceptance": "NOT_RUN",
    }
    receipt["topology"] = audit_native_avm_fixture(project, receipt)
    receipt["source_hashes_after"] = {
        path: _hash(Path(path)) for path in library_receipt["source_hashes"]
    }
    if receipt["source_hashes_after"] != library_receipt["source_hashes"]:
        raise ValueError("Native AVM source inputs changed during materialization")
    receipt_path = folder / "native-avm-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return receipt


def audit_native_avm_fixture(
    project_path: str | Path,
    receipt: dict,
    *,
    finalized_library_sha256: str | None = None,
) -> dict:
    root = ET.parse(project_path).getroot()
    if root.get("name") != receipt["project_name"] or root.get("version") != "4.6.2":
        raise ValueError("Native AVM project identity changed")
    main = root.find("./definitions/Definition[@name='Main']")
    counts = Counter(user.get("defn") for user in main.findall("./schematic/User"))
    required = {
        f"{NATIVE_SCOPE}:MMCAverageArm": 12,
        f"{NATIVE_SCOPE}:{CONTROL_NAME}": 2,
        f"{NATIVE_SCOPE}:MMCCableLink": 1,
        "master:source3": 2,
        "master:xfmr-3p2w": 2,
        "master:breakout": 2,
        "master:ground": 1,
        "master:voltmeter": 2,
        "master:pgb": len(FIXTURE_CHANNELS),
    }
    if any(counts[name] != count for name, count in required.items()):
        raise ValueError("Native AVM fixture is missing a required physical component")
    nets = receipt["electrical_nets"]["Main"]
    if {
        "P_source:N",
        "P_transformer:G1",
        "V_source:N",
        "V_transformer:G1",
        "neutral_ground:A",
    } - set(nets["GND"]):
        raise ValueError("Native AVM source and transformer neutrals are not grounded")
    for prefix in ("P", "V"):
        for phase in "ABC":
            if {
                f"{prefix}_{phase}_UPPER:OUT",
                f"{prefix}_{phase}_LOWER:IN",
                f"{prefix}_breakout:N{'ABC'.index(phase) + 1}",
            } - set(nets[prefix + "_PHASE_" + phase]):
                raise ValueError("Native AVM phase midpoint is incomplete")
        if not all(
            f"{prefix}_{phase}_UPPER:IN" in nets[prefix + "_DC_POS"]
            and f"{prefix}_{phase}_LOWER:OUT" in nets[prefix + "_DC_NEG"]
            for phase in "ABC"
        ):
            raise ValueError("Native AVM DC arm polarity is incomplete")
    if set(nets["P_DC_POS"]) & set(nets["P_DC_NEG"]) or set(nets["V_DC_POS"]) & set(
        nets["V_DC_NEG"]
    ):
        raise ValueError("Native AVM DC poles are crossed")
    library = Path(receipt["library"]["library_path"])
    expected_library_sha256 = (
        receipt["library"]["library_sha256"]
        if finalized_library_sha256 is None
        else finalized_library_sha256
    )
    if _hash(library) != expected_library_sha256:
        raise ValueError("Native AVM companion library changed")
    definitions = {
        definition.get("name")
        for definition in ET.parse(library).findall("./definitions/Definition")
    }
    if (
        not {
            "MMCAverageArm",
            "MMCAverageCoupling",
            CONTROL_NAME,
            "MMCCableLink",
            "Cable2",
        }
        <= definitions
    ):
        raise ValueError("Native AVM companion definitions are incomplete")
    return {
        "two_stations": True,
        "arm_count": 12,
        "phase_breakout_count": 2,
        "coupled_cable_count": 1,
        "control_kind": receipt["control_kind"],
        "physical_power_control_closed": False,
    }


__all__ = [
    "CONTROL_DEFAULTS",
    "CONTROL_NAME",
    "CONTROL_OUTPUTS",
    "FIXTURE_CHANNELS",
    "NATIVE_SCOPE",
    "audit_native_avm_fixture",
    "materialize_native_avm_fixture",
    "materialize_native_avm_library",
]
