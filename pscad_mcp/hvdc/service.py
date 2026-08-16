"""Application service for deterministic HVDC workflows."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from ..core.backend.base import BackendError
from ..core.path_policy import PathPolicy, WorkspaceNotConfiguredError
from .classifier import classify_topology, extract_assets
from .mappings import MappingResolution, resolve_mappings
from .profiles import list_profiles, load_profile, register_profile
from .scanner import scan_project


class HvdcDomainService:
    """Coordinate read-only inspection and safe domain operations."""

    def __init__(self, backend_service: Any | None = None, *, path_policy: Any | None = None) -> None:
        self.backend_service = backend_service
        self.path_policy = path_policy or PathPolicy()
        self._cache: dict[str, tuple[int, dict[str, Any]]] = {}
        self._scenarios: dict[str, dict[str, Any]] = {}

    def _resolve_project(self, project_name: str) -> Path:
        if not isinstance(project_name, str) or not project_name.strip():
            raise BackendError("INVALID_ARGUMENT", "project_name must be a non-empty string.", "hvdc", "inspect_hvdc_project")
        candidate = Path(project_name).expanduser()
        if candidate.suffix.lower() != ".pscx":
            candidate = candidate.with_suffix(".pscx")
        try:
            try:
                return self.path_policy.resolve(str(candidate), suffixes={".pscx"}, must_exist=True)
            except TypeError:
                return self.path_policy.resolve(str(candidate))
        except WorkspaceNotConfiguredError as error:
            raise BackendError("WORKSPACE_NOT_CONFIGURED", str(error), "hvdc", "inspect_hvdc_project", {"candidate": project_name}) from error
        except FileNotFoundError as error:
            raise BackendError("NOT_FOUND", f"HVDC project '{project_name}' was not found.", "hvdc", "inspect_hvdc_project", {"candidate": project_name}) from error
        except ValueError as error:
            raise BackendError("INVALID_ARGUMENT", str(error), "hvdc", "inspect_hvdc_project", {"candidate": project_name}) from error

    def _inspection(self, project_name: str, canvas_name: str = "Main") -> dict[str, Any]:
        path = self._resolve_project(project_name)
        key = str(path)
        mtime = path.stat().st_mtime_ns
        cached = self._cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        evidence = scan_project(path, canvas_name)
        topology = classify_topology(evidence)
        assets = extract_assets(evidence)
        profile_name = "hvdc_breaker_difforder" if any(asset.kind == "breaker" for asset in assets) else "auto"
        mappings: MappingResolution
        unresolved: list[str]
        if profile_name == "auto":
            mappings = MappingResolution((), (), ())
            unresolved = []
        else:
            mappings = resolve_mappings(evidence, load_profile(profile_name))
            unresolved = list(mappings.unresolved)
        result = {
            "project": {"name": evidence.project_name, "path": evidence.project_path, "pscad_version": evidence.pscad_version, "canvas": canvas_name},
            "evidence": asdict(evidence),
            "topology": asdict(topology),
            "assets": [asdict(asset) for asset in assets],
            "mappings": [asdict(mapping) for mapping in mappings.mappings],
            "unresolved": unresolved,
            "warnings": list(evidence.warnings) + list(mappings.warnings),
            "confidence": topology.confidence,
        }
        self._cache[key] = (mtime, result)
        return result

    def inspect_project(self, project_name: str, canvas_name: str = "Main") -> dict[str, Any]:
        return self._inspection(project_name, canvas_name)

    def get_assets(self, project_name: str, kind: str | None = None, canvas_name: str = "Main") -> list[dict[str, Any]]:
        assets = self._inspection(project_name, canvas_name)["assets"]
        return [asset for asset in assets if kind is None or asset["kind"] == kind]

    def get_mappings(self, project_name: str, canonical: str | None = None, canvas_name: str = "Main") -> dict[str, Any]:
        result = self._inspection(project_name, canvas_name)
        mappings = [item for item in result["mappings"] if canonical is None or item["canonical"] == canonical]
        return {"mappings": mappings, "unresolved": result["unresolved"], "warnings": result["warnings"]}

    def validate_project(self, project_name: str, profile: str = "auto", canvas_name: str = "Main") -> dict[str, Any]:
        result = self._inspection(project_name, canvas_name)
        profile_name = profile
        if profile == "auto":
            profile_name = "hvdc_breaker_difforder" if any(item["kind"] == "breaker" for item in result["assets"]) else "lcc_bipolar_generic"
        loaded = load_profile(profile_name)
        found = {item["kind"] for item in result["assets"]}
        missing_assets = sorted(set(loaded.get("required_assets", [])) - found)
        errors: list[dict[str, Any]] = []
        if result["topology"]["family"] == "unknown":
            errors.append({"code": "HVDC_TOPOLOGY_AMBIGUOUS", "message": "Topology family is unknown.", "evidence": result["topology"]["evidence"]})
        if missing_assets:
            errors.append({"code": "HVDC_MAPPING_MISSING", "message": "Required HVDC assets are missing.", "missing_assets": missing_assets})
        return {"valid": not errors and not result["unresolved"], "profile": profile_name, "missing_assets": missing_assets, "unresolved": result["unresolved"], "errors": errors, "warnings": result["warnings"], "topology": result["topology"]}

    def list_profiles(self) -> list[dict[str, Any]]:
        return [{"name": name, "profile": load_profile(name)} for name in list_profiles()]

    def register_profile(self, profile_name: str, mapping_file: str) -> dict[str, Any]:
        try:
            try:
                resolved = self.path_policy.resolve(mapping_file, suffixes={".json"}, must_exist=True)
            except TypeError:
                resolved = self.path_policy.resolve(mapping_file)
        except WorkspaceNotConfiguredError as error:
            raise BackendError("WORKSPACE_NOT_CONFIGURED", str(error), "hvdc", "register_hvdc_profile", {"candidate": mapping_file}) from error
        except FileNotFoundError as error:
            raise BackendError("NOT_FOUND", f"HVDC mapping file '{mapping_file}' was not found.", "hvdc", "register_hvdc_profile", {"candidate": mapping_file}) from error
        except ValueError as error:
            raise BackendError("INVALID_ARGUMENT", str(error), "hvdc", "register_hvdc_profile", {"candidate": mapping_file}) from error
        return register_profile(profile_name, str(resolved))

    async def validate_scenario(self, scenario: Mapping[str, Any]) -> dict[str, Any]:
        from .scenarios import validate_scenario
        return validate_scenario(scenario)

    async def run_scenario(self, project_name: str, scenario: Mapping[str, Any], confirm: bool = False) -> dict[str, Any]:
        from .scenarios import run_scenario
        return await run_scenario(self, project_name, scenario, confirm=confirm)

    async def scenario_status(self, scenario_id: str) -> dict[str, Any]:
        return dict(self._scenarios.get(scenario_id, {"error": {"code": "NOT_FOUND", "message": f"Scenario '{scenario_id}' was not found."}}))

    async def analyze_results(self, scenario_id: str, metrics: list[str] | None = None) -> dict[str, Any]:
        from .metrics import calculate_metrics

        record = self._scenarios.get(scenario_id)
        if record is None:
            return {"error": {"code": "NOT_FOUND", "message": f"Scenario '{scenario_id}' was not found."}}
        samples = record.get("samples")
        if samples is None and record.get("output_files") and self.backend_service is not None:
            try:
                samples = await self.backend_service.read_output_file(record["output_files"][0], summary_only=False)
            except Exception as error:
                record.setdefault("warnings", []).append(str(error))
        samples = samples or {"time": [], "channels": {}}
        result = calculate_metrics(samples, metrics)
        record["metrics"] = result["metrics"]
        record["verdict"] = result["verdict"]
        record.setdefault("warnings", []).extend(result["warnings"])
        return {"scenario_id": scenario_id, **result}

    async def compare_scenarios(self, scenario_ids: list[str], metrics: list[str] | None = None) -> dict[str, Any]:
        if not isinstance(scenario_ids, list) or not scenario_ids:
            return {"error": {"code": "INVALID_ARGUMENT", "message": "scenario_ids must not be empty."}}
        records: list[dict[str, Any]] = []
        for scenario_id in scenario_ids:
            if scenario_id not in self._scenarios:
                return {"error": {"code": "NOT_FOUND", "message": f"Scenario '{scenario_id}' was not found."}}
            if not self._scenarios[scenario_id].get("metrics"):
                await self.analyze_results(scenario_id, metrics)
            records.append(self._scenarios[scenario_id])
        names = metrics or sorted({item["name"] for record in records for item in record.get("metrics", [])})
        comparisons: list[dict[str, Any]] = []
        for name in names:
            values = [next((item.get("value") for item in record.get("metrics", []) if item.get("name") == name), None) for record in records]
            baseline = values[0]
            for index, value in enumerate(values[1:], start=1):
                comparisons.append({"metric": name, "baseline": scenario_ids[0], "scenario_id": scenario_ids[index], "baseline_value": baseline, "value": value, "delta": None if baseline is None or value is None else value - baseline})
        return {"scenario_ids": scenario_ids, "comparisons": comparisons, "verdicts": {record["scenario_id"]: record.get("verdict") for record in records}}
