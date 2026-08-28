"""Public PSCAD line-constants generation for audited MMC templates.

The installed PSCAD X4 distribution exposes ``tline.exe`` as the supported
line-constants program.  This module only derives its documented text input
from a DCTL definition and records the resulting artifacts; it never edits an
installed source project.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from xml.etree import ElementTree as ET


_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")


def _tag(value: str) -> str:
    return value.rsplit("}", 1)[-1].casefold()


def _number(value: str | None, *, parameter: str) -> float:
    match = _NUMBER.search((value or "").strip())
    if match is None:
        raise ValueError(f"DCTL parameter {parameter!r} is missing a numeric value")
    return float(match.group(0))


def _params(element: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in element.iter():
        if _tag(child.tag) == "param" and child.attrib.get("name"):
            result[child.attrib["name"]] = child.attrib.get("value", "")
    return result


def _find_user(root: ET.Element, definition: str) -> dict[str, str]:
    target = definition.casefold()
    for element in root.iter():
        if _tag(element.tag) != "user":
            continue
        value = element.attrib.get("defn", "")
        if value.casefold() == target or value.rsplit(":", 1)[-1].casefold() == target.rsplit(":", 1)[-1]:
            return _params(element)
    raise ValueError(f"DCTL configuration {definition!r} is missing")


@dataclass(frozen=True)
class TlineSegment:
    name: str
    length_km: float
    frequency_hz: float
    conductors: int
    options: Mapping[str, str]
    ground: Mapping[str, str]
    tower: Mapping[str, str]


@dataclass(frozen=True)
class LineConstantsArtifact:
    segment: str
    input_path: str
    constants_path: str
    log_path: str
    output_path: str
    input_sha256: str
    constants_sha256: str
    log_sha256: str
    output_sha256: str
    command: tuple[str, ...]
    returncode: int

    def to_dict(self) -> dict[str, object]:
        return {
            "segment": self.segment,
            "input_path": self.input_path,
            "constants_path": self.constants_path,
            "log_path": self.log_path,
            "output_path": self.output_path,
            "input_sha256": self.input_sha256,
            "constants_sha256": self.constants_sha256,
            "log_sha256": self.log_sha256,
            "output_sha256": self.output_sha256,
            "command": list(self.command),
            "returncode": self.returncode,
        }


def extract_tline_segments(project_path: str | Path) -> tuple[TlineSegment, ...]:
    root = ET.parse(project_path).getroot()
    definition = next(
        (
            item
            for item in root.iter()
            if _tag(item.tag) == "definition"
            and item.attrib.get("name", "").rsplit(":", 1)[-1].casefold() == "dctl"
        ),
        None,
    )
    if definition is None:
        raise ValueError("DCTL definition is missing")
    options = _find_user(definition, "Line_FrePhase_Options")
    ground = _find_user(definition, "Line_Ground")
    tower = _find_user(definition, "Line_Tower_2_Flat")
    segments: list[TlineSegment] = []
    for wire in root.iter():
        if _tag(wire.tag) != "wire" or wire.attrib.get("classid", "").casefold() != "tline":
            continue
        params = _params(wire)
        name = params.get("Name", "").strip()
        if not name:
            raise ValueError("DCTL parameter 'Name' is missing")
        length = _number(params.get("Length"), parameter="Length")
        dim = int(round(_number(params.get("Dim"), parameter="Dim")))
        if dim < 1:
            raise ValueError("DCTL parameter 'Dim' must be positive")
        segments.append(
            TlineSegment(
                name=name,
                length_km=length,
                frequency_hz=_number(params.get("Freq", "0"), parameter="Freq"),
                conductors=dim,
                options=options,
                ground=ground,
                tower=tower,
            )
        )
    if not segments:
        raise ValueError("No DCTL transmission segments were found")
    return tuple(segments)


def _v(values: Mapping[str, str], name: str, default: str | None = None) -> float:
    value = values.get(name, default)
    return _number(value, parameter=name)


def render_tli(segment: TlineSegment) -> str:
    """Render the documented PSCAD 4.6 LCP input sections."""

    o, g, t = segment.options, segment.ground, segment.tower
    conductors = " ".join(str(i) for i in range(1, segment.conductors + 1))
    lines = [
        "Line Summary:",
        "   {",
        f"   Line Name = {segment.name}",
        f"   Line Length = {segment.length_km:g}",
        f"   Steady State Frequency = {segment.frequency_hz:g}",
        f"   Number of Conductors = {segment.conductors}",
        "   }",
        "",
        "Line Constants Tower:",
        "   {",
        f"   Name = {t.get('TName', 'MMC_TOWER')}",
        "   Circuit = 1",
        "      {",
        f"      Transposed = {int(_v(t, 'Transp', '1'))}",
        f"      Conductors = {segment.conductors}",
        f"      Conductor Phase Information = {conductors}",
        f"      Radius = {_v(t, 'RadiusC'):g}",
        f"      DCResistance = {_v(t, 'DCResC'):g}",
        f"      Conductor Relative Permeability = {_v(t, 'PERMC', '1'):g}",
        f"      ShuntConductance = {_v(t, 'ShuntG', '1.0e-11'):g}",
        f"      P1 = {-_v(t, 'XC', '0'):g} {_v(t, 'Y'):g}",
        f"      P2 = {_v(t, 'XC', '0'):g} {_v(t, 'Y'):g}",
        f"      Sag = {_v(t, 'SAGC', '0'):g}",
        f"      Sub-ConductorsPerBundle = {int(_v(t, 'NCondB', '1'))}",
        "         {",
        f"         BundleSpacing = {_v(t, 'BSP', '0'):g}",
        "         }",
        "      }",
        f"   GroundWires = {int(_v(t, 'NG', '1'))}",
        "      {",
        f"      Eliminate Ground Wires = {int(_v(t, 'ElimGW', '1'))}",
        f"      Radius = {_v(t, 'RadiusG'):g}",
        f"      DCResistance = {_v(t, 'DCResG'):g}",
        f"      Ground Wire Relative Permeability = {_v(t, 'PERMG', '1'):g}",
        f"      Unique Ground Wires = {int(_v(t, 'GWSame', '1'))}",
        f"      P1 = {-_v(t, 'XG', '0'):g} {_v(t, 'YG', '0'):g}",
        f"      P2 = {_v(t, 'XG', '0'):g} {_v(t, 'YG', '0'):g}",
        f"      Sag = {_v(t, 'SAGG', '0'):g}",
        "      }",
        "   }",
        "",
        "Frequency Dep. (Phase) Model Options:",
        "   {",
        f"   Interpolate Travel Times = {int(_v(o, 'Interp1', '1'))}",
        f"   Infinite Line Length = {int(_v(o, 'Inflen', '0'))}",
        f"   Curve Fitting Start Frequency = {_v(o, 'FS', '0.5'):g}",
        f"   Curve Fitting End Frequency = {_v(o, 'FE', '1.0e6'):g}",
        f"   Total Number of Frequency Increments = {int(_v(o, 'Numf', '100'))}",
        f"   Maximum # of Poles for Surge Admittance Fit = {int(_v(o, 'YMaxP', '20'))}",
        f"   Maximum Fitting Error (%) for Surge Admittance = {_v(o, 'YMaxE', '0.2'):g}",
        f"   Maximum # of Poles for Attenuation Constant Fit = {int(_v(o, 'AMaxP', '20'))}",
        f"   Maximum Fitting Error (%) for Attenuation Constant = {_v(o, 'AMaxE', '0.2'):g}",
        f"   Weighting Factor 1 = {_v(o, 'W1', '1.0'):g}",
        f"   Weighting Factor 2 = {_v(o, 'W2', '1000.0'):g}",
        f"   Weighting Factor 3 = {_v(o, 'W3', '1.0'):g}",
        f"   Write Detailed Output Files = {int(_v(o, 'Output', '0'))}",
        "   }",
        "",
        "Line Constants Ground Data:",
        "   {",
        f"   Ground Resistivity Type = {int(_v(g, 'GrRho', '0'))}",
        f"   GroundResistivity = {_v(g, 'GRRES', '100.0'):g}",
        f"   GroundPermeability = {_v(g, 'GPERM', '1.0'):g}",
        f"   EarthImpedanceFormula = {int(_v(g, 'EarthForm', '0'))}",
        f"   EarthUImpedanceFormula = {int(_v(g, 'EarthForm2', '0'))}",
        f"   EarthMImpedanceFormula = {int(_v(g, 'EarthForm3', '2'))}",
        "   }",
        "",
    ]
    return "\n".join(lines)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate_public_line_constants(
    project_path: str | Path,
    output_dir: str | Path,
    *,
    executable: str | Path | None = None,
    timeout_s: float = 300.0,
) -> tuple[LineConstantsArtifact, ...]:
    """Generate one LCP artifact per DCTL through the installed public utility."""

    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    tline = Path(executable).expanduser().resolve() if executable else None
    if tline is None:
        candidates = (
            Path(os.environ.get("PSCAD_MCP_TLINE", "")),
            Path(r"C:\Program Files (x86)\PSCAD46\bin\win\tline.exe"),
        )
        tline = next((item for item in candidates if str(item) and item.is_file()), None)
        if tline is None:
            found = shutil.which("tline.exe") or shutil.which("tline")
            tline = Path(found).resolve() if found else None
    if tline is None or not tline.is_file():
        raise FileNotFoundError("PSCAD tline.exe was not found")

    artifacts: list[LineConstantsArtifact] = []
    for segment in extract_tline_segments(project_path):
        input_path = destination / f"{segment.name}.tli"
        constants_path = destination / f"{segment.name}.tlo"
        log_path = destination / f"{segment.name}.log"
        output_path = destination / f"{segment.name}.out"
        input_path.write_text(render_tli(segment), encoding="utf-8", newline="\n")
        command = (str(tline), input_path.name)
        with log_path.open("w", encoding="utf-8", newline="") as log:
            completed = subprocess.run(
                list(command),
                cwd=destination,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=timeout_s,
            )
        if completed.returncode != 0 or not constants_path.is_file():
            raise RuntimeError(
                f"PSCAD line constants failed for {segment.name}: "
                f"returncode={completed.returncode} log={log_path}"
            )
        artifacts.append(
            LineConstantsArtifact(
                segment=segment.name,
                input_path=str(input_path),
                constants_path=str(constants_path),
                log_path=str(log_path),
                output_path=str(output_path),
                input_sha256=_sha256(input_path),
                constants_sha256=_sha256(constants_path),
                log_sha256=_sha256(log_path),
                output_sha256=_sha256(output_path) if output_path.is_file() else "",
                command=command,
                returncode=completed.returncode,
            )
        )
    return tuple(artifacts)


def rebind_template_line_constants(
    source_project: str | Path,
    artifacts: tuple[LineConstantsArtifact, ...],
    target_project: str | Path,
) -> Path:
    """Copy a template and replace only DCTL ``const_path`` attributes.

    The source bytes are never modified.  Targeted block replacement preserves
    PSCAD's XML layout and makes the resulting source hash auditable.
    """

    source = Path(source_project).expanduser().resolve()
    target = Path(target_project).expanduser().resolve()
    if source == target:
        raise ValueError("The rebound template must be a distinct file")
    text = source.read_text(encoding="utf-8")
    for artifact in artifacts:
        marker = re.compile(
            r'(<Wire\b(?=[^>]*\bclassid=["\']TLine["\'])[^>]*>.*?'
            r'<param\b[^>]*\bname=["\']Name["\']\s+value=["\']'
            + re.escape(artifact.segment)
            + r'["\'][^>]*/>.*?<param\b[^>]*\bname=["\']const_path["\']'
            r'\s+value=["\'])[^"\']*(["\'])',
            re.IGNORECASE | re.DOTALL,
        )
        text, count = marker.subn(
            lambda match: match.group(1) + artifact.constants_path + match.group(2),
            text,
            count=1,
        )
        if count != 1:
            raise ValueError(
                f"DCTL segment {artifact.segment!r} has no replaceable const_path"
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="")
    return target


__all__ = [
    "LineConstantsArtifact",
    "TlineSegment",
    "extract_tline_segments",
    "generate_public_line_constants",
    "rebind_template_line_constants",
    "render_tli",
]
