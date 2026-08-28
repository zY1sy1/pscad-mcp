"""HVDC domain diagnostics over confirmed canonical topology."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from ...hvdc.classifier import classify_topology, extract_assets
from ...hvdc.mappings import resolve_mappings
from ...hvdc.models import HvdcProjectEvidence
from ...hvdc.profiles import load_profile
from ..adapters.hvdc import topology_to_hvdc_evidence
from ..models import DiagnosticFinding, ProjectTopology


def diagnose_hvdc(
    topology: ProjectTopology,
    *,
    profile: str = "auto",
) -> tuple[DiagnosticFinding, ...]:
    """Run existing HVDC classification and validation on canonical evidence."""
    evidence = topology_to_hvdc_evidence(topology)
    summary = classify_topology(evidence)
    if profile == "auto" and summary.family == "unknown":
        return (
            _finding(
                "HVDC_TOPOLOGY_AMBIGUOUS",
                "Topology family is unknown; no domain profile was selected.",
                evidence=summary.evidence or summary.unresolved_questions,
            ),
        )

    profile_name = (
        _auto_profile(evidence, summary.family)
        if profile == "auto"
        else profile
    )
    loaded = load_profile(profile_name)
    assets = extract_assets(evidence)
    found = {item.kind for item in assets}
    missing_assets = sorted(set(loaded.get("required_assets", ())) - found)
    resolution = resolve_mappings(evidence, loaded)
    constraints = loaded.get("topology_constraints", {})
    findings: list[DiagnosticFinding] = []

    if constraints.get("family") and summary.family != constraints["family"]:
        findings.append(
            _finding(
                "HVDC_TOPOLOGY_AMBIGUOUS",
                "Project family does not satisfy the selected profile.",
                evidence=summary.evidence,
            )
        )
    if constraints.get("polarity") and summary.polarity != constraints["polarity"]:
        findings.append(
            _finding(
                "HVDC_TOPOLOGY_AMBIGUOUS",
                "Project polarity does not satisfy the selected profile.",
                evidence=summary.evidence,
            )
        )
    if constraints.get("return_mode") == "earth_return":
        if summary.return_path_status == "ambiguous":
            findings.append(
                _finding(
                    "HVDC_TOPOLOGY_AMBIGUOUS",
                    "Earth-return and metallic-return evidence conflict.",
                    evidence=summary.mode_evidence,
                )
            )
        elif (
            summary.return_path_status != "verified"
            or summary.return_mode != "earth_return"
        ):
            findings.append(
                _finding(
                    "HVDC_RETURN_PATH_UNRESOLVED",
                    "The earth-return path is not verified.",
                    evidence=tuple(
                        question
                        for path in summary.return_path
                        for question in path.unresolved_questions
                    ),
                )
            )
    if missing_assets or resolution.unresolved:
        findings.append(
            _finding(
                "HVDC_MAPPING_MISSING",
                "Required HVDC assets or semantic mappings are missing.",
                evidence=(*missing_assets, *resolution.unresolved),
            )
        )
    if resolution.conflicts:
        findings.append(
            _finding(
                "HVDC_MAPPING_CONFLICT",
                "One or more semantic mappings have conflicting evidence.",
                evidence=resolution.conflicts,
            )
        )
    findings.extend(
        _finding(
            warning.split(":", 1)[0],
            warning,
            severity="warning",
            evidence=(warning,),
        )
        for warning in evidence.warnings
    )
    return tuple(
        sorted(
            findings,
            key=lambda item: (item.code, item.objects, item.message),
        )
    )


def _auto_profile(evidence: HvdcProjectEvidence, family: str) -> str:
    if family == "lcc":
        text = " ".join(
            [item.definition for item in evidence.components]
            + [item.name for item in evidence.components]
            + [item.text for item in evidence.labels]
        ).casefold()
        if "earth return" in text or "earthreturn" in text:
            return "lcc_bipolar_earth_return_v1"
        return "lcc_bipolar_generic"
    if family == "mmc":
        return "mmc_bipolar_generic"
    return "vsc_2level_generic"


def _finding(
    code: str,
    message: str,
    *,
    severity: Literal["info", "warning", "error"] = "error",
    evidence: Iterable[object] = (),
) -> DiagnosticFinding:
    references = tuple(sorted({str(item) for item in evidence if str(item)}))
    return DiagnosticFinding(
        code=code,
        severity=severity,
        status="unresolved" if severity != "info" else "derived",
        confidence=1.0,
        objects=(),
        evidence=references,
        message=message,
        suggested_action="Review the named HVDC evidence and select an explicit profile if needed.",
    )
