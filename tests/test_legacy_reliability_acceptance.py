"""Opt-in PSCAD 4.6.2 reliability acceptance on timestamped copies."""

from __future__ import annotations

import asyncio
from decimal import Decimal
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import psutil

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.backend.legacy_support import Rect
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.service import PscadService
from tests.test_legacy_acceptance import (
    ACCEPTANCE_ENABLED,
    LegacyAcceptanceCase,
    _pscad_processes,
)


@unittest.skipUnless(
    ACCEPTANCE_ENABLED,
    "Set PSCAD_MCP_ACCEPTANCE=1 to run licensed PSCAD 4.6.x acceptance.",
)
class TestLegacyReliabilityAcceptance(LegacyAcceptanceCase):
    @staticmethod
    def _layer_names(node) -> set[str]:
        raw = node.get("layer") or node.get("layers") or ""
        return {value for value in re.split(r"[;,\s]+", raw) if value}

    @staticmethod
    def _rect_from_node(node) -> Rect:
        return Rect(
            int(node.get("x", "0")),
            int(node.get("y", "0")),
            max(int(node.get("w", "36")), 1),
            max(int(node.get("h", "36")), 1),
        )

    async def test_01_create_blank_case_and_library_reload(self) -> None:
        directory = self._evidence_directory("reliability-create")
        case_path = directory / "created_case.pscx"
        library_path = directory / "created_library.pslx"

        case = await self.backend.create_project(
            "case", case_path.name, str(directory)
        )
        library = await self.backend.create_project(
            "library", library_path.name, str(directory)
        )
        await self.backend.save_project(case.name)
        await self.backend.save_project(library.name)
        self.assertTrue(case_path.is_file())
        self.assertTrue(library_path.is_file())

        await self._restart_backend()
        await self.backend.load_projects([str(case_path), str(library_path)])
        projects = {
            project.name: project for project in await self.backend.list_projects()
        }
        self.assertEqual(projects[case_path.stem].type.casefold(), "case")
        self.assertEqual(projects[library_path.stem].type.casefold(), "library")
        self.assertEqual(self._xml_root(case_path).get("name"), case_path.stem)
        self.assertEqual(
            self._xml_root(library_path).get("name"), library_path.stem
        )
        print(
            "ACCEPTANCE_RELIABILITY=create-reload;PASS;"
            f"case_sha256={self._sha256(case_path)};"
            f"library_sha256={self._sha256(library_path)}",
            flush=True,
        )

    async def test_02_native_failure_save_as_fallback_reload(self) -> None:
        original_source = self._project_path(
            "PSCAD_MCP_ACCEPTANCE_RELIABILITY_PROJECT"
        )
        original_hash = self._sha256(original_source)
        source = self._timestamped_project_copy("reliability-save-as")
        project_name = await self._load_path(source)
        destination = source.parent / "saved_as_case.pscx"
        project = await self.backend._project(project_name)
        failed_response = ET.Element(
            "commandresponse", {"success": "false"}
        )

        with patch.object(
            type(project), "save_as", return_value=failed_response
        ):
            await self.backend.save_project_as(
                project_name, destination.name, str(destination.parent)
            )

        self.assertEqual(self._sha256(original_source), original_hash)
        target_root = self._xml_root(destination)
        self.assertEqual(target_root.get("name"), destination.stem)
        self.assertTrue(
            all(
                output.get("name") == destination.stem
                for output in target_root.findall("./output")
            )
        )

        await self._restart_backend()
        await self._load_path(destination)
        project = next(
            item
            for item in await self.backend.list_projects()
            if item.name == destination.stem
        )
        self.assertEqual(project.type.casefold(), "case")
        self.assertEqual(self._sha256(original_source), original_hash)
        print(
            "ACCEPTANCE_RELIABILITY=save-as-fallback;PASS;"
            f"protected_source={original_source};"
            f"protected_source_sha256={original_hash};"
            f"operated_copy_sha256={self._sha256(source)};"
            f"target_sha256={self._sha256(destination)}",
            flush=True,
        )

    async def test_03_nonblocking_run_pause_resume_stop(self) -> None:
        path = self._timestamped_project_copy("reliability-run-control")
        project_name = await self._load_path(path)

        await asyncio.wait_for(self.backend.run_project(project_name), 10)
        started = await asyncio.wait_for(
            self.backend.project_run_state(project_name), 10
        )
        with self._captured_stdout() as captured:
            await asyncio.wait_for(
                self.backend.pause_project(project_name), 10
            )
        self.assertEqual(captured.getvalue(), "")
        paused = await asyncio.wait_for(
            self.backend.project_run_state(project_name), 10
        )
        await asyncio.wait_for(self.backend.run_project(project_name), 10)
        resumed = await asyncio.wait_for(
            self.backend.project_run_state(project_name), 10
        )
        await asyncio.wait_for(self.backend.stop_project(project_name), 10)
        stopped = await self._wait_for_terminal_state(project_name, 30)
        self.assertIn(stopped.status, {"completed", "stopped", "idle"})
        print(
            "ACCEPTANCE_RELIABILITY=run-control;PASS;"
            f"started={started.status};paused={paused.status};"
            f"resumed={resumed.status};stopped={stopped.status}",
            flush=True,
        )

    async def test_04_project_settings_round_trip_and_restore(self) -> None:
        path = self._timestamped_project_copy("reliability-settings")
        project_name = await self._load_path(path)
        before = await self.backend.get_settings(project_name)
        self.assertIn("time_duration", before)
        original = before["time_duration"]
        changed = str(Decimal(str(original)) + Decimal("0.1"))
        application_before = dict(
            await self.backend.executor.run_safe(
                self.backend._require_app().settings
            )
        )

        try:
            await self.backend.set_settings(
                project_name, {"time_duration": changed}
            )
            reread = await self.backend.get_settings(project_name)
            self.assertEqual(
                Decimal(str(reread["time_duration"])), Decimal(changed)
            )
        finally:
            await self.backend.set_settings(
                project_name, {"time_duration": original}
            )
            await self.backend.save_project(project_name)

        restored = await self.backend.get_settings(project_name)
        self.assertEqual(
            Decimal(str(restored["time_duration"])), Decimal(str(original))
        )
        application_after = dict(
            await self.backend.executor.run_safe(
                self.backend._require_app().settings
            )
        )
        self.assertEqual(application_after, application_before)
        print(
            "ACCEPTANCE_RELIABILITY=project-settings;PASS;"
            f"original={original};changed={changed};restored={restored['time_duration']}",
            flush=True,
        )

    async def test_05_disabled_layer_capability_limit_is_explicit(self) -> None:
        path = self._timestamped_project_copy("reliability-disabled-layer")
        project_name = await self._load_path(path)
        component = await self.backend.add_component(
            project_name,
            "Main",
            "master",
            "resistor",
            (450, 450),
            0,
            {},
        )
        await self.backend.save_project(project_name)

        with self.assertRaises(BackendError) as raised:
            await self.backend.set_component_enabled(
                project_name, component.id, False
            )
        self.assertEqual(raised.exception.code, "PSCAD_COMMAND_FAILED")
        self.assertEqual(raised.exception.operation, "disable_component")
        await self.backend.save_project(project_name)
        unchanged_node = self._xml_node_by_id(
            self._xml_root(path), component.id
        )
        self.assertIsNotNone(unchanged_node)
        self.assertNotIn(
            "PSCAD_MCP_DISABLED", self._layer_names(unchanged_node)
        )

        await self.backend.set_component_enabled(
            project_name, component.id, True
        )
        await self.backend.save_project(project_name)
        enabled_node = self._xml_node_by_id(self._xml_root(path), component.id)
        self.assertIsNotNone(enabled_node)
        self.assertNotIn("PSCAD_MCP_DISABLED", self._layer_names(enabled_node))
        print(
            "ACCEPTANCE_RELIABILITY=disabled-layer-capability-limit;PASS;"
            f"code={raised.exception.code};component={component.id};"
            f"sha256={self._sha256(path)}",
            flush=True,
        )

    async def test_06_connected_batch_delete_removes_wire_and_components(self) -> None:
        path = self._timestamped_project_copy("reliability-delete")
        project_name = await self._load_path(path)
        first = await self.backend.add_component(
            project_name, "Main", "master", "resistor", (450, 450), 0, {}
        )
        second = await self.backend.add_component(
            project_name, "Main", "master", "resistor", (540, 450), 0, {}
        )
        first_ports = await self.backend.get_component_ports(
            project_name, first.id
        )
        second_ports = await self.backend.get_component_ports(
            project_name, second.id
        )
        wire = await self.backend.create_wire(
            project_name,
            "Main",
            [
                (first_ports[-1].x, first_ports[-1].y),
                (second_ports[0].x, second_ports[0].y),
            ],
        )

        planned_ids = {first.id, second.id, int(wire["id"])}
        await self.backend.delete_components(
            project_name, [first.id, second.id]
        )
        canvas = await self.backend._canvas(project_name, "Main")
        response = await self.backend.executor.run_safe(
            canvas.list_components
        )
        live_ids = {
            int(node.get("id"))
            for node in response.iter()
            if node.get("id") is not None
        }
        self.assertTrue(planned_ids.isdisjoint(live_ids))
        await self.backend.save_project(project_name)
        saved_ids = {
            int(node.get("id"))
            for node in self._xml_root(path).iter()
            if node.get("id", "").isdigit()
        }
        self.assertTrue(planned_ids.isdisjoint(saved_ids))
        print(
            "ACCEPTANCE_RELIABILITY=connected-delete;PASS;"
            f"planned_ids={sorted(planned_ids)};sha256={self._sha256(path)}",
            flush=True,
        )

    async def test_07_empty_rectangle_stays_clear_after_add(self) -> None:
        path = self._timestamped_project_copy("reliability-empty-space")
        project_name = await self._load_path(path)
        occupied_component = await self.backend.add_component(
            project_name, "Main", "master", "resistor", (450, 450), 0, {}
        )
        await self.backend.save_project(project_name)
        occupied_node = self._xml_node_by_id(
            self._xml_root(path), occupied_component.id
        )
        self.assertIsNotNone(occupied_node)
        occupied = self._rect_from_node(occupied_node)

        empty = await self.backend.find_empty_space(
            project_name,
            "Main",
            occupied.width,
            occupied.height,
            (occupied.x, occupied.y),
        )
        self.assertEqual(empty["x"] % 18, 0)
        self.assertEqual(empty["y"] % 18, 0)
        added = await self.backend.add_component(
            project_name,
            "Main",
            "master",
            "resistor",
            (empty["x"], empty["y"]),
            0,
            {},
        )
        await self.backend.save_project(project_name)
        root = self._xml_root(path)
        first_node = self._xml_node_by_id(root, occupied_component.id)
        second_node = self._xml_node_by_id(root, added.id)
        self.assertIsNotNone(first_node)
        self.assertIsNotNone(second_node)
        first_rect = self._rect_from_node(first_node)
        second_rect = self._rect_from_node(second_node)
        self.assertFalse(first_rect.intersects(second_rect))
        print(
            "ACCEPTANCE_RELIABILITY=empty-space;PASS;"
            f"first={first_rect};second={second_rect};sha256={self._sha256(path)}",
            flush=True,
        )

    async def test_08_owned_repair_replaces_process_in_order(self) -> None:
        old_pids = {
            pid for pid in self.owned_processes if psutil.pid_exists(pid)
        }
        self.assertTrue(old_pids)
        factory_process_snapshots = []

        def factory():
            factory_process_snapshots.append(_pscad_processes())
            return self._new_backend()

        service = PscadService(factory, executor=robust_executor)
        service._backend = self.backend
        result = await service.repair_connection()
        self.backend = service.backend

        self.assertTrue(factory_process_snapshots)
        self.assertTrue(
            old_pids.isdisjoint(factory_process_snapshots[0]),
            "A fresh backend was selected before the owned PSCAD PID exited.",
        )
        await self._wait_for_pids_to_exit(old_pids, timeout=10.0)
        active = _pscad_processes()
        new_processes = {
            pid: executable
            for pid, executable in active.items()
            if pid not in old_pids
        }
        self.assertTrue(new_processes)
        self.owned_processes.update(new_processes)
        self.assertIn("launched a new PSCAD automation instance", result)
        print(
            "ACCEPTANCE_RELIABILITY=owned-repair;PASS;"
            f"old_pids={sorted(old_pids)};new_pids={sorted(new_processes)}",
            flush=True,
        )

    async def test_09_simulation_set_lifecycle_and_task_parameters(self) -> None:
        path = self._timestamped_project_copy("reliability-simset")
        set_name = f"MCP_{path.parent.name[-24:]}"[:48]
        project_name = path.stem
        service = PscadService(lambda: self.backend, executor=robust_executor)
        service._backend = self.backend
        created = False
        try:
            await service.load_projects([str(path)])
            details = await service.create_simulation_set(set_name)
            created = True
            self.assertEqual(details["tasks"], ())

            await service.add_task_to_set("", set_name, project_name)
            self.assertEqual(
                await service.list_simulation_set_tasks(set_name),
                [project_name],
            )

            original = await service.get_simulation_task_parameters(
                set_name, project_name
            )
            updated_volley = 2 if original["volley"] != 2 else 3
            updated = await service.set_simulation_task_parameters(
                set_name, project_name, {"volley": updated_volley}
            )
            self.assertEqual(updated["volley"], updated_volley)
            restored = await service.set_simulation_task_parameters(
                set_name, project_name, {"volley": original["volley"]}
            )
            self.assertEqual(restored["volley"], original["volley"])

            await service.remove_tasks_from_set(
                set_name, [project_name], confirm=True
            )
            await service.remove_simulation_set(set_name, confirm=True)
            created = False
            print(
                "ACCEPTANCE_RELIABILITY=simulation-set;PASS;"
                f"set_name={set_name};project={path}",
                flush=True,
            )
        finally:
            if created:
                try:
                    await service.remove_simulation_set(set_name, confirm=True)
                except Exception as cleanup_error:
                    print(
                        "ACCEPTANCE_RELIABILITY=simulation-set-cleanup;FAIL;"
                        f"error_type={type(cleanup_error).__name__}",
                        flush=True,
                    )


if __name__ == "__main__":
    unittest.main()
