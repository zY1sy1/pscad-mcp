"""Opt-in acceptance tests against a licensed PSCAD 4.6.x installation.

These tests are skipped unless PSCAD_MCP_ACCEPTANCE=1. The runner prepares
independent project copies and refuses to run while another PSCAD process is
already open, so teardown can safely verify only the processes launched here.
"""

from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path
import unittest
from contextlib import redirect_stdout

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


@unittest.skipUnless(
    ACCEPTANCE_ENABLED,
    "Set PSCAD_MCP_ACCEPTANCE=1 to run licensed PSCAD 4.6.x acceptance.",
)
class TestLegacyAcceptance(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.before_processes = _pscad_processes()
        self.assertEqual(
            self.before_processes,
            {},
            "Acceptance refuses to attach while an unrelated PSCAD process is open.",
        )
        self.backend = LegacyBackend(
            robust_executor,
            version=os.getenv("PSCAD_MCP_ACCEPTANCE_VERSION", "4.6.2"),
            x64=os.getenv("PSCAD_MCP_ACCEPTANCE_X64", "true").casefold()
            in {"1", "true", "yes", "on"},
        )
        info = await self.backend.attach()
        self.assertTrue(info.alive)
        self.assertTrue(info.licensed)
        self.assertTrue(info.owns_process)
        self.launched_processes = {
            pid: executable
            for pid, executable in _pscad_processes().items()
            if pid not in self.before_processes
        }
        self.assertTrue(
            self.launched_processes,
            "The backend reported ownership but no new PSCAD PID was detected.",
        )
        for pid, executable in self.launched_processes.items():
            print(f"ACCEPTANCE_PID={pid};EXE={executable}", flush=True)

    async def asyncTearDown(self) -> None:
        if getattr(self, "backend", None) is not None:
            try:
                if self.backend.owns_process:
                    await self.backend.quit()
            finally:
                await self.backend.disconnect()
        launched = getattr(self, "launched_processes", {})
        for _ in range(40):
            if not any(psutil.pid_exists(pid) for pid in launched):
                break
            await asyncio.sleep(0.25)
        remaining = {
            pid: executable
            for pid, executable in launched.items()
            if psutil.pid_exists(pid)
        }
        self.assertEqual(
            remaining,
            {},
            f"Acceptance-owned PSCAD process did not exit: {remaining}",
        )

    def _project_path(self, variable: str) -> Path:
        raw_path = os.getenv(variable)
        if not raw_path:
            self.skipTest(f"{variable} is not configured.")
        path = Path(raw_path).resolve()
        self.assertTrue(path.is_file(), f"Missing acceptance project: {path}")
        self.assertEqual(path.suffix.casefold(), ".pscx")
        return path

    async def _load_project(self, variable: str) -> str:
        path = self._project_path(variable)
        await self.backend.load_projects([str(path)])
        project_name = path.stem
        names = {item.name for item in await self.backend.list_projects()}
        self.assertIn(project_name, names)
        return project_name

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
                    f"Simulation did not finish within {timeout}s; states={observed[-20:]}"
                )
            await asyncio.sleep(0.25)

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
