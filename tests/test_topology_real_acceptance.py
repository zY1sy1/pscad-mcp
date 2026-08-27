"""Opt-in read-only topology acceptance against licensed PSCAD 4.6.2."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from typing import Any
import xml.etree.ElementTree as ET

from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.topology.acceptance import write_acceptance_report
from pscad_mcp.topology.hashing import canonical_sha256, topology_sha256
from pscad_mcp.topology.models import ProjectTopology, TopologySnapshot
from pscad_mcp.topology.service import TopologyService
from tests.test_legacy_acceptance import LegacyAcceptanceCase


ROOT = Path(__file__).parents[1]
ACCEPTANCE_ENABLED = os.getenv("PSCAD_MCP_TOPOLOGY_ACCEPTANCE") == "1"
OPT_IN_MESSAGE = (
    "Set PSCAD_MCP_TOPOLOGY_ACCEPTANCE=1 to run licensed PSCAD 4.6.2 "
    "topology acceptance."
)


class AcceptanceReadOnlyBackend:
    def __init__(self, backend: LegacyBackend) -> None:
        self._backend = backend
        self.calls: list[str] = []

    async def inspect_canvas_topology(
        self, project_name: str, canvas_name: str
    ) -> TopologySnapshot:
        self.calls.append("inspect_canvas_topology")
        return await self._backend.inspect_canvas_topology(
            project_name, canvas_name
        )

    def __getattr__(self, _name: str) -> Any:
        raise AssertionError(
            "topology acceptance requested a non-read backend member"
        )


def confirmed_net_truth(topology: ProjectTopology) -> list[str]:
    return sorted(
        (
            f"{net.namespace}|ports={','.join(sorted(net.port_keys))}"
            f"|conductors={','.join(sorted(net.conductor_keys))}"
            f"|labels={','.join(sorted(net.label_keys))}"
        )
        for net in topology.nets
    )


def inventory_sha256(snapshot: TopologySnapshot) -> str:
    projection = {
        "canvases": [
            {
                "key": item.key,
                "name": item.name,
                "parent_key": item.parent_key,
                "page_ports": sorted(item.page_ports),
            }
            for item in sorted(snapshot.canvases, key=lambda value: value.key)
        ],
        "components": [
            {
                "key": item.key,
                "canvas_key": item.canvas_key,
                "object_id": item.object_id,
                "definition": item.definition,
                "location": item.location,
                "orientation": item.orientation,
                "active": item.active,
                "ports": [
                    {
                        "key": port.key,
                        "name": port.name,
                        "absolute": port.absolute,
                        "relative": port.relative,
                        "kind": port.kind,
                        "dimension": port.dimension,
                        "active": port.active,
                        "required": port.required,
                    }
                    for port in sorted(item.ports, key=lambda value: value.key)
                ],
            }
            for item in sorted(snapshot.components, key=lambda value: value.key)
        ],
        "conductors": [
            {
                "key": item.key,
                "canvas_key": item.canvas_key,
                "object_id": item.object_id,
                "kind": item.kind,
                "namespace": item.namespace,
                "vertices": item.vertices,
            }
            for item in sorted(snapshot.conductors, key=lambda value: value.key)
        ],
        "labels": [
            {
                "key": item.key,
                "canvas_key": item.canvas_key,
                "object_id": item.object_id,
                "name": item.name,
                "namespace": item.namespace,
                "scope": item.scope,
                "location": item.location,
            }
            for item in sorted(snapshot.labels, key=lambda value: value.key)
        ],
        "boundary_links": [
            {
                "key": item.key,
                "outer_port_key": item.outer_port_key,
                "outer_canvas_key": item.outer_canvas_key,
                "outer_point": item.outer_point,
                "inner_port_key": item.inner_port_key,
                "inner_canvas_key": item.inner_canvas_key,
                "inner_point": item.inner_point,
                "namespace": item.namespace,
                "dimension": item.dimension,
            }
            for item in sorted(
                snapshot.boundary_links, key=lambda value: value.key
            )
        ],
        "unresolved": sorted(snapshot.unresolved),
    }
    return canonical_sha256(projection)


def topology_object_count(topology: ProjectTopology) -> int:
    return sum(
        len(collection)
        for collection in (
            topology.components,
            topology.conductors,
            topology.labels,
        )
    )


def _project_identity(path: Path) -> str:
    name = (ET.parse(path).getroot().get("name") or "").strip()
    if not name:
        raise ValueError(f"project identity is missing: {path}")
    return name


@unittest.skipUnless(ACCEPTANCE_ENABLED, OPT_IN_MESSAGE)
class TestTopologyAcceptanceProjectIdentity(unittest.TestCase):
    def test_reads_pscad_normalized_identity_instead_of_filename_stem(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "seeded-defects.pscx"
            project.write_text(
                '<project name="seeded_defects" version="4.6.2"/>',
                encoding="utf-8",
            )

            self.assertEqual(_project_identity(project), "seeded_defects")


@unittest.skipUnless(ACCEPTANCE_ENABLED, OPT_IN_MESSAGE)
class TestTopologyRealAcceptance(LegacyAcceptanceCase):
    def _new_backend(self) -> LegacyBackend:
        return LegacyBackend(
            robust_executor,
            version=os.getenv(
                "PSCAD_MCP_TOPOLOGY_ACCEPTANCE_VERSION", "4.6.2"
            ),
            x64=os.getenv(
                "PSCAD_MCP_TOPOLOGY_ACCEPTANCE_X64", "true"
            ).casefold()
            in {"1", "true", "yes", "on"},
        )

    async def _load_path(self, path: Path) -> str:
        await self.backend.load_projects([str(path)])
        project_name = _project_identity(path)
        names = {item.name for item in await self.backend.list_projects()}
        self.assertIn(project_name, names)
        return project_name

    async def asyncSetUp(self) -> None:
        self.manifest_path = self._absolute_file_environment(
            "PSCAD_MCP_TOPOLOGY_ACCEPTANCE_MANIFEST", suffix=".json"
        )
        self.workspace = self._absolute_directory_environment(
            "PSCAD_MCP_TOPOLOGY_ACCEPTANCE_WORKSPACE"
        )
        self.report_path = self._absolute_report_environment(
            "PSCAD_MCP_TOPOLOGY_ACCEPTANCE_REPORT"
        )
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertIsInstance(manifest, dict)
        self.rule_version = manifest.get("rule_version", "generic-v1")
        self.assertIn(
            self.rule_version,
            {"generic-v1", "generic+hvdc-v1"},
        )
        self.cases = manifest.get("cases")
        self.assertIsInstance(self.cases, list)
        self.assertTrue(self.cases, "Topology truth manifest has no cases.")
        await super().asyncSetUp()

    def _absolute_file_environment(self, name: str, *, suffix: str) -> Path:
        raw = os.getenv(name)
        self.assertTrue(raw, f"{name} is not configured.")
        path = Path(str(raw))
        self.assertTrue(path.is_absolute(), f"{name} must be absolute.")
        path = path.resolve()
        self.assertTrue(path.is_file(), f"Missing acceptance file: {path}")
        self.assertEqual(path.suffix.casefold(), suffix)
        return path

    def _absolute_directory_environment(self, name: str) -> Path:
        raw = os.getenv(name)
        self.assertTrue(raw, f"{name} is not configured.")
        path = Path(str(raw))
        self.assertTrue(path.is_absolute(), f"{name} must be absolute.")
        path = path.resolve()
        self.assertTrue(path.is_dir(), f"Missing acceptance directory: {path}")
        self.assertTrue(
            path.name.startswith("topology-acceptance-"),
            "Topology acceptance requires a timestamped workspace.",
        )
        return path

    def _absolute_report_environment(self, name: str) -> Path:
        raw = os.getenv(name)
        self.assertTrue(raw, f"{name} is not configured.")
        path = Path(str(raw))
        self.assertTrue(path.is_absolute(), f"{name} must be absolute.")
        path = path.resolve()
        self.assertEqual(path.parent, self.workspace)
        self.assertEqual(path.suffix.casefold(), ".json")
        return path

    def _truth_source(self, case: dict[str, Any], index: int) -> Path:
        raw = case.get("source_project")
        self.assertIsInstance(raw, str, f"Case {index} has no source_project.")
        source = Path(raw)
        self.assertTrue(source.is_absolute(), "source_project must be absolute.")
        source = source.resolve()
        self.assertTrue(source.is_file(), f"Missing source project: {source}")
        self.assertEqual(source.suffix.casefold(), ".pscx")
        return source

    def _copied_project(self, source: Path, index: int) -> Path:
        copied = self.workspace / f"case-{index:03d}" / source.name
        self.assertTrue(copied.is_file(), f"Missing runner copy: {copied}")
        return copied

    async def _inventory_sha256(
        self,
        backend: AcceptanceReadOnlyBackend,
        project_name: str,
        canvas_name: str,
    ) -> str:
        snapshot = await backend.inspect_canvas_topology(
            project_name, canvas_name
        )
        return inventory_sha256(snapshot)

    def _sorted_truth(
        self,
        case: dict[str, Any],
        field: str,
        index: int,
        *,
        optional: bool = False,
    ) -> list[str]:
        value = case.get(field, [] if optional else None)
        self.assertIsInstance(value, list, f"Case {index} {field} is invalid.")
        self.assertTrue(
            all(isinstance(item, str) for item in value),
            f"Case {index} {field} must contain strings.",
        )
        self.assertEqual(value, sorted(value), f"Case {index} {field} is unsorted.")
        return value

    async def test_read_only_topology_truth_and_performance(self) -> None:
        report_cases = []
        coverage_codes: set[str] = set()
        for index, raw_case in enumerate(self.cases):
            self.assertIsInstance(raw_case, dict)
            case = raw_case
            name = case.get("name")
            canvas_name = case.get("canvas", "Main")
            healthy = case.get("healthy")
            minimum_object_count = case.get("minimum_object_count")
            ruleset = case.get("ruleset", "generic")
            self.assertIsInstance(name, str)
            self.assertTrue(name)
            self.assertIsInstance(canvas_name, str)
            self.assertTrue(canvas_name)
            self.assertIsInstance(healthy, bool)
            self.assertIsInstance(minimum_object_count, int)
            self.assertGreaterEqual(minimum_object_count, 0)
            self.assertIn(ruleset, {"generic", "generic+hvdc-auto"})

            source_project = self._truth_source(case, index)
            copied_project = self._copied_project(source_project, index)
            expected_confirmed_edges = self._sorted_truth(
                case, "expected_confirmed_edges", index
            )
            expected_error_codes = self._sorted_truth(
                case, "expected_error_codes", index
            )
            expected_domain_codes = self._sorted_truth(
                case,
                "expected_domain_codes",
                index,
                optional=True,
            )
            expected_unresolved_codes = self._sorted_truth(
                case, "expected_unresolved_codes", index
            )
            required_capabilities = case.get("required_source_capabilities")
            self.assertIsInstance(required_capabilities, dict)
            self.assertTrue(required_capabilities)
            self.assertTrue(
                all(type(value) is bool for value in required_capabilities.values())
            )

            source_hash = self._sha256(source_project).lower()
            before_hash = self._sha256(copied_project).lower()
            project_name = await self._load_path(copied_project)
            readonly_backend = AcceptanceReadOnlyBackend(self.backend)
            service = TopologyService(readonly_backend)
            before_inventory = await self._inventory_sha256(
                readonly_backend, project_name, canvas_name
            )

            diagnosis_started = time.perf_counter()
            first_report = await service.diagnose(
                project_name,
                canvas_name,
                ruleset=ruleset,
                mode="conservative",
            )
            elapsed_ms = (time.perf_counter() - diagnosis_started) * 1000.0
            print(
                "TOPOLOGY_ACCEPTANCE_CASE="
                f"{name};ELAPSED_MS={elapsed_ms:.3f};"
                f"PHASE_TIMINGS_MS={dict(first_report.timings_ms)}",
                flush=True,
            )
            first = await service.inspect(
                project_name, canvas_name, mode="conservative"
            )
            second = await service.inspect(
                project_name, canvas_name, mode="conservative"
            )
            after_inventory = await self._inventory_sha256(
                readonly_backend, project_name, canvas_name
            )
            after_hash = self._sha256(copied_project).lower()

            topology_hash = topology_sha256(first)
            second_topology_hash = topology_sha256(second)
            observed_confirmed_edges = confirmed_net_truth(first)
            observed_unresolved_codes = sorted(first.unresolved)
            observed_domain_codes = sorted(
                item.code
                for item in first_report.findings
                if item.severity == "error" and item.code.startswith("HVDC_")
            )
            observed_error_codes = sorted(
                item.code
                for item in first_report.findings
                if item.severity == "error"
                and not item.code.startswith("HVDC_")
            )
            object_count = topology_object_count(first)
            source_capabilities = dict(first.source_capabilities)

            self.assertEqual(source_hash, before_hash)
            self.assertEqual(before_hash, after_hash)
            self.assertEqual(before_inventory, after_inventory)
            self.assertEqual(first_report.topology_hash, topology_hash)
            self.assertEqual(topology_hash, second_topology_hash)
            self.assertEqual(
                expected_confirmed_edges, observed_confirmed_edges
            )
            self.assertEqual(
                expected_unresolved_codes, observed_unresolved_codes
            )
            self.assertFalse(first.candidate_edges)
            self.assertTrue(
                required_capabilities.items() <= source_capabilities.items()
            )
            self.assertEqual(expected_error_codes, observed_error_codes)
            self.assertEqual(expected_domain_codes, observed_domain_codes)
            self.assertGreaterEqual(object_count, minimum_object_count)
            self.assertEqual(
                set(readonly_backend.calls), {"inspect_canvas_topology"}
            )

            coverage_codes.update(expected_error_codes)
            report_cases.append(
                {
                    "name": name,
                    "ruleset": ruleset,
                    "healthy": healthy,
                    "source_sha256": source_hash,
                    "before_sha256": before_hash,
                    "after_sha256": after_hash,
                    "topology_hashes": [topology_hash, second_topology_hash],
                    "inventory_hashes": [
                        before_inventory,
                        after_inventory,
                    ],
                    "dirty_state": {
                        "available": False,
                        "before": None,
                        "after": None,
                    },
                    "elapsed_ms": elapsed_ms,
                    "phase_timings_ms": dict(first_report.timings_ms),
                    "object_count": object_count,
                    "source_capabilities": source_capabilities,
                    "finding_counts": dict(first_report.summary),
                    "expected_confirmed_edges": expected_confirmed_edges,
                    "observed_confirmed_edges": observed_confirmed_edges,
                    "expected_error_codes": expected_error_codes,
                    "observed_error_codes": observed_error_codes,
                    "expected_domain_codes": expected_domain_codes,
                    "observed_domain_codes": observed_domain_codes,
                    "expected_unresolved_codes": expected_unresolved_codes,
                    "observed_unresolved_codes": observed_unresolved_codes,
                    "candidate_edges_confirmed": False,
                }
            )

        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        report = {
            "schema_version": 1,
            "status": "PASS",
            "commit": commit,
            "rule_version": self.rule_version,
            "pscad": {
                "version": self.backend.version,
                "backend": "legacy",
                "licensed": True,
            },
            "cases": report_cases,
            "coverage_codes": sorted(coverage_codes),
        }
        written = write_acceptance_report(self.report_path, report)
        print(f"TOPOLOGY_ACCEPTANCE_REPORT={written}", flush=True)
