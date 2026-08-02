"""Opt-in acceptance tests against a licensed PSCAD 4.6.x installation.

These tests are skipped unless PSCAD_MCP_ACCEPTANCE=1. The runner prepares
independent project copies and refuses to run while another PSCAD process is
already open, so teardown can safely verify only the processes launched here.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager, redirect_stdout
from datetime import datetime
import hashlib
import io
import os
from pathlib import Path
import shutil
import unittest
from typing import Any, Callable

import psutil

from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.executor import robust_executor


ACCEPTANCE_ENABLED = os.getenv("PSCAD_MCP_ACCEPTANCE") == "1"


def _pscad_processes() -> dict[int, str | None]:
    result: dict[int, str | None] = {}
    for process in psutil.process_iter(["pid", "name", "exe"]):
        name = str(process.info.get("name") or "")
        if name.casefold().startswith("pscad"):
            result[int(process.info["pid"])] = process.info.get("exe")
    return result


class LegacyAcceptanceCase(unittest.IsolatedAsyncioTestCase):
    def _new_backend(self) -> LegacyBackend:
        return LegacyBackend(
            robust_executor,
            version=os.getenv("PSCAD_MCP_ACCEPTANCE_VERSION", "4.6.2"),
            x64=os.getenv("PSCAD_MCP_ACCEPTANCE_X64", "true").casefold()
            in {"1", "true", "yes", "on"},
        )

    async def asyncSetUp(self) -> None:
        self.before_processes = _pscad_processes()
        self.assertEqual(
            self.before_processes,
            {},
            "Acceptance refuses to attach while an unrelated PSCAD process is open.",
        )
        self.owned_processes: dict[int, str | None] = {}
        self.backend = self._new_backend()
        await self._attach_and_record(self.backend)
        self.launched_processes = dict(self.owned_processes)

    async def _attach_and_record(self, backend: LegacyBackend) -> None:
        before = _pscad_processes()
        info = await backend.attach()
        self.assertTrue(info.alive)
        self.assertTrue(info.licensed)
        self.assertTrue(info.owns_process)
        launched = {
            pid: executable
            for pid, executable in _pscad_processes().items()
            if pid not in before
        }
        self.assertTrue(
            launched,
            "The backend reported ownership but no new PSCAD PID was detected.",
        )
        self.owned_processes.update(launched)
        for pid, executable in launched.items():
            print(f"ACCEPTANCE_PID={pid};EXE={executable}", flush=True)

    async def asyncTearDown(self) -> None:
        teardown_error: BaseException | None = None
        if getattr(self, "backend", None) is not None:
            try:
                if self.backend.owns_process:
                    await self.backend.quit()
            except BaseException as error:
                teardown_error = error
            finally:
                try:
                    await self.backend.disconnect()
                except BaseException as error:
                    if teardown_error is None:
                        teardown_error = error

        await self._wait_for_pids_to_exit(
            set(getattr(self, "owned_processes", {})), timeout=10.0
        )
        remaining = {
            pid: executable
            for pid, executable in getattr(self, "owned_processes", {}).items()
            if psutil.pid_exists(pid)
        }
        self.assertEqual(
            remaining,
            {},
            f"Acceptance-owned PSCAD process did not exit: {remaining}",
        )
        if teardown_error is not None:
            raise teardown_error

    async def _wait_until(
        self,
        predicate: Callable[[], Any],
        *,
        timeout: float,
        message: str,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() >= deadline:
                self.fail(message)
            await asyncio.sleep(0.25)

    async def _wait_for_pids_to_exit(
        self, pids: set[int], *, timeout: float
    ) -> None:
        await self._wait_until(
            lambda: not any(psutil.pid_exists(pid) for pid in pids),
            timeout=timeout,
            message=f"PSCAD PIDs did not exit within {timeout}s: {sorted(pids)}",
        )

    def _project_path(self, variable: str) -> Path:
        raw_path = os.getenv(variable)
        if not raw_path:
            self.skipTest(f"{variable} is not configured.")
        path = Path(raw_path).resolve()
        self.assertTrue(path.is_file(), f"Missing acceptance project: {path}")
        self.assertEqual(path.suffix.casefold(), ".pscx")
        return path

    def _evidence_directory(self, label: str) -> Path:
        raw_workspace = os.getenv("PSCAD_MCP_ACCEPTANCE_WORKSPACE")
        if not raw_workspace:
            self.skipTest("PSCAD_MCP_ACCEPTANCE_WORKSPACE is not configured.")
        workspace = Path(raw_workspace).resolve()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        directory = workspace / f"codex-{stamp}-{label}"
        directory.mkdir(parents=True, exist_ok=False)
        print(f"ACCEPTANCE_EVIDENCE={directory}", flush=True)
        return directory

    def _timestamped_project_copy(
        self,
        label: str,
        variable: str = "PSCAD_MCP_ACCEPTANCE_RELIABILITY_PROJECT",
    ) -> Path:
        source = self._project_path(variable)
        directory = self._evidence_directory(label)
        destination = directory / source.name
        shutil.copy2(source, destination)
        print(
            f"ACCEPTANCE_SOURCE_COPY={destination};SHA256={self._sha256(destination)}",
            flush=True,
        )
        return destination

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()

    @staticmethod
    def _xml_root(path: Path):
        import xml.etree.ElementTree as ET

        return ET.parse(path).getroot()

    @staticmethod
    def _xml_node_by_id(root: Any, object_id: int):
        expected = str(object_id)
        return next(
            (node for node in root.iter() if node.get("id") == expected),
            None,
        )

    @contextmanager
    def _captured_stdout(self):
        captured = io.StringIO()
        with redirect_stdout(captured):
            yield captured

    async def _load_path(self, path: Path) -> str:
        await self.backend.load_projects([str(path)])
        project_name = path.stem
        names = {item.name for item in await self.backend.list_projects()}
        self.assertIn(project_name, names)
        return project_name

    async def _load_project(self, variable: str) -> str:
        return await self._load_path(self._project_path(variable))

    async def _restart_backend(self) -> None:
        previous = self.backend
        previous_pids = {
            pid for pid in self.owned_processes if psutil.pid_exists(pid)
        }
        if previous.owns_process:
            await previous.quit()
        await previous.disconnect()
        await self._wait_for_pids_to_exit(previous_pids, timeout=10.0)
        robust_executor.reset()
        self.backend = self._new_backend()
        await self._attach_and_record(self.backend)

    async def _wait_for_terminal_state(
        self, project_name: str, timeout: float
    ):
        deadline = asyncio.get_running_loop().time() + timeout
        terminal = {"completed", "stopped", "failed", "idle"}
        observed = []
        while True:
            state = await self.backend.project_run_state(project_name)
            observed.append(state.status)
            if state.status.casefold() in terminal:
                return state
            if asyncio.get_running_loop().time() >= deadline:
                self.fail(
                    f"Simulation did not finish within {timeout}s; "
                    f"states={observed[-20:]}"
                )
            await asyncio.sleep(0.25)


@unittest.skipUnless(
    ACCEPTANCE_ENABLED,
    "Set PSCAD_MCP_ACCEPTANCE=1 to run licensed PSCAD 4.6.x acceptance.",
)
class TestLegacyAcceptance(LegacyAcceptanceCase):

    async def test_01_read_only(self) -> None:
        project_name = await self._load_project(
            "PSCAD_MCP_ACCEPTANCE_READONLY_PROJECT"
        )
        definitions = await self.backend.project_definitions(project_name)
        components = await self.backend.find_components(
            project_name, "Main", None, None
        )
        settings = await self.backend.get_settings(project_name)
        self.assertIsInstance(definitions, list)
        self.assertTrue(components)
        self.assertIsInstance(settings, dict)
        print(
            "ACCEPTANCE_GROUP=read-only;PASS;"
            f"definitions={len(definitions)};components={len(components)}",
            flush=True,
        )

    async def test_02_mutation_and_canvas(self) -> None:
        project_name = await self._load_project(
            "PSCAD_MCP_ACCEPTANCE_MUTATION_PROJECT"
        )
        component = await self.backend.add_component(
            project_name,
            "Main",
            "master",
            "resistor",
            (450, 450),
            0,
            {},
        )
        before_ports = await self.backend.get_component_ports(
            project_name, component.id
        )
        await self.backend.rotate_component(project_name, component.id, "right")
        after_ports = await self.backend.get_component_ports(
            project_name, component.id
        )
        self.assertNotEqual(
            [(port.x, port.y) for port in before_ports],
            [(port.x, port.y) for port in after_ports],
        )
        clone = await self.backend.clone_component(
            project_name, component.id, (540, 450)
        )
        clone_ports = await self.backend.get_component_ports(
            project_name, clone.id
        )
        self.assertTrue(after_ports)
        self.assertTrue(clone_ports)
        await self.backend.create_wire(
            project_name,
            "Main",
            [
                (after_ports[-1].x, after_ports[-1].y),
                (clone_ports[0].x, clone_ports[0].y),
            ],
        )
        await self.backend.create_bus(
            project_name, "Main", [(630, 450), (690, 450)], {}
        )
        await self.backend.create_connection(
            project_name,
            "Main",
            (630, 540),
            (690, 540),
            "ACCEPTANCE_DATA",
            False,
        )
        annotation = await self.backend.create_annotation(
            project_name,
            "Main",
            (450, 630),
            "PSCAD MCP",
            "Acceptance",
        )
        graph = await self.backend.create_graph_frame(
            project_name, "Main", (540, 630)
        )
        control = await self.backend.create_control_frame(
            project_name, "Main", (630, 630)
        )
        canvas_items = await self.backend.list_canvas_components(
            project_name, "Main"
        )
        canvas_ids = {item["id"] for item in canvas_items}
        self.assertIn(annotation.id, canvas_ids)
        self.assertIn(graph["id"], canvas_ids)
        self.assertIn(control["frame_id"], canvas_ids)
        await self.backend.save_project(project_name)
        print(
            "ACCEPTANCE_GROUP=mutation-canvas;PASS;"
            f"component={component.id};clone={clone.id};items={len(canvas_items)}",
            flush=True,
        )

    async def test_03_build(self) -> None:
        project_name = await self._load_project(
            "PSCAD_MCP_ACCEPTANCE_BUILD_PROJECT"
        )
        await asyncio.wait_for(self.backend.build_project(project_name), 360)
        output = await self.backend.project_output(project_name)
        self.assertIsInstance(output, str)
        print(
            f"ACCEPTANCE_GROUP=build;PASS;output_chars={len(output)}",
            flush=True,
        )

    async def test_04_simulation_and_output(self) -> None:
        project_name = await self._load_project(
            "PSCAD_MCP_ACCEPTANCE_SIMULATION_PROJECT"
        )
        await asyncio.wait_for(self.backend.run_project(project_name), 10)
        state = await self._wait_for_terminal_state(project_name, 360)
        self.assertNotEqual(state.status, "failed")
        output = await self.backend.project_output(project_name)
        self.assertIsInstance(output, str)
        self.assertIn("Solve Time", output)
        print(
            f"ACCEPTANCE_GROUP=simulation-output;PASS;output_chars={len(output)}",
            flush=True,
        )

    async def test_05_run_pause_status_stop(self) -> None:
        project_name = await self._load_project(
            "PSCAD_MCP_ACCEPTANCE_SIMULATION_PROJECT"
        )
        await asyncio.wait_for(self.backend.run_project(project_name), 10)
        started = await asyncio.wait_for(
            self.backend.project_run_state(project_name), 10
        )
        captured = io.StringIO()
        with redirect_stdout(captured):
            await asyncio.wait_for(
                self.backend.pause_project(project_name), 10
            )
        self.assertEqual(captured.getvalue(), "")
        paused = await asyncio.wait_for(
            self.backend.project_run_state(project_name), 10
        )
        await asyncio.wait_for(self.backend.stop_project(project_name), 10)
        stopped = await self._wait_for_terminal_state(project_name, 30)
        self.assertIn(stopped.status, {"completed", "stopped", "idle"})
        print(
            "ACCEPTANCE_GROUP=run-control;PASS;"
            f"started={started.status};paused={paused.status};stopped={stopped.status}",
            flush=True,
        )

    async def test_05_psout_reader(self) -> None:
        raw_path = os.getenv("PSCAD_MCP_ACCEPTANCE_RESULT_FILE")
        if not raw_path:
            self.skipTest("PSCAD_MCP_ACCEPTANCE_RESULT_FILE is not configured.")
        path = Path(raw_path).resolve()
        self.assertTrue(path.is_file(), f"Missing PSOUT sample: {path}")
        result = await self.backend.read_output_file(str(path), 25)
        self.assertGreaterEqual(result["runs"], 1)
        self.assertTrue(result["channels"])
        self.assertLessEqual(len(result["channels"][0]["values"]), 25)
        print(
            "ACCEPTANCE_GROUP=psout;PASS;"
            f"runs={result['runs']};channels={len(result['channels'])}",
            flush=True,
        )


if __name__ == "__main__":
    unittest.main()
