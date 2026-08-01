import unittest

from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.backend.modern import ModernBackend
from tests.backend_fakes import (
    FakeLegacyAutomation,
    FakeModernPscad,
    ImmediateExecutor,
)


class FakeProject:
    def __init__(self, name="case", kind="Case"):
        self.name = name
        self.type = kind
        self.description = "Example"
        self.filename = f"{name}.pscx"
        self.calls = []

    def save(self): self.calls.append(("save",))
    def save_as(self, *args, **kwargs): self.calls.append(("save_as", args, kwargs))
    def build(self): self.calls.append(("build",))
    def run(self): self.calls.append(("run",))
    def pause(self): self.calls.append(("pause",))
    def stop(self): self.calls.append(("stop",))
    def run_status(self): return ("running", 50.0)
    def definitions(self): return ["master:source", "master:ground"]
    def list_definitions(self): return ["source", "ground"]
    def output(self): return "modern output"
    def messages(self): return [("legacy output", "build", "normal", self.name, "", 0, 0)]


class FakeSimulationSet:
    def __init__(self):
        self.ran = False
        self.tasks = []

    def run(self): self.ran = True
    def add_tasks(self, *names): self.tasks.extend(names)


class FakeWorkspace:
    def __init__(self, app):
        self.app = app
        self.created = []

    def create_project(self, kind, name, path):
        project = FakeProject(name, "Case" if kind == 1 else "Library")
        self.app.project_map[name] = project
        self.created.append((kind, name, path))
        return project

    def list_simulation_sets(self): return list(self.app.simsets)


class FakeLegacyApp:
    def __init__(self):
        self.project_map = {"case": FakeProject()}
        self.simsets = {"set1": FakeSimulationSet()}
        self.loaded = []
        self.settings_data = {"fortran_version": "GFortran"}
        self.workspace_proxy = FakeWorkspace(self)
        self.built_all = False

    def is_alive(self): return True
    def licensed(self): return True
    def load(self, *filenames): self.loaded.extend(filenames)
    def list_projects(self):
        return [{"name": p.name, "type": p.type, "description": p.description} for p in self.project_map.values()]
    def project(self, name): return self.project_map[name]
    def workspace(self): return self.workspace_proxy
    def build_all(self): self.built_all = True
    def settings(self, settings=None, **kwargs):
        updates = dict(settings or {}, **kwargs)
        if updates: self.settings_data.update(updates)
        return dict(self.settings_data)
    def simulation_set(self, name): return self.simsets[name]
    def quit(self): pass


class FakeModernApp(FakeLegacyApp):
    version = "5.0.2"
    workspace_path = r"D:\PSCAD-Workspace"

    def is_busy(self): return False
    def projects(self): return self.list_projects()
    def create_case(self, filename, folder=None):
        return self._create(filename, "Case")
    def create_library(self, filename, folder=None):
        return self._create(filename, "Library")
    def _create(self, filename, kind):
        name = filename.rsplit(".", 1)[0]
        project = FakeProject(name, kind)
        self.project_map[name] = project
        return project
    def simulation_sets(self): return list(self.simsets)


class TestBackendProjectContracts(unittest.IsolatedAsyncioTestCase):
    async def make_backends(self):
        legacy_app = FakeLegacyApp()
        modern_app = FakeModernApp()
        legacy = LegacyBackend(
            ImmediateExecutor(), version="4.6.2", x64=True,
            automation_module=FakeLegacyAutomation(legacy_app),
        )
        modern = ModernBackend(
            ImmediateExecutor(), version="5.0.2", x64=True,
            pscad_module=FakeModernPscad(modern_app), psout_module=False,
        )
        await legacy.attach()
        await modern.attach()
        return [(legacy, legacy_app), (modern, modern_app)]

    async def test_project_lifecycle_and_normalization_match(self):
        for backend, app in await self.make_backends():
            with self.subTest(backend=backend.name):
                await backend.load_projects([r"D:\work\case.pscx"])
                projects = await backend.list_projects()
                await backend.run_project("case")
                await backend.pause_project("case")
                await backend.stop_project("case")
                state = await backend.project_run_state("case")
                await backend.save_project("case")
                await backend.save_project_as("case", "copy.pscx", r"D:\work")
                await backend.build_project("case")
                await backend.build_all_projects()

                self.assertEqual(projects[0].name, "case")
                self.assertEqual(projects[0].type, "Case")
                self.assertEqual(state.status, "running")
                self.assertEqual(state.progress, 50.0)
                self.assertEqual(app.loaded, [r"D:\work\case.pscx"])
                self.assertTrue(app.built_all)

    async def test_create_definitions_settings_and_output_match(self):
        for backend, _app in await self.make_backends():
            with self.subTest(backend=backend.name):
                case = await backend.create_project("case", "new.pscx", r"D:\work")
                library = await backend.create_project("library", "lib.pslx", r"D:\work")
                await backend.set_settings("case", {"fortran_version": "Intel"})

                self.assertEqual(case.name, "new")
                self.assertEqual(library.type, "Library")
                self.assertEqual((await backend.get_settings("case"))["fortran_version"], "Intel")
                self.assertEqual(len(await backend.project_definitions("case")), 2)
                self.assertIn("output", await backend.project_output("case"))

    async def test_simulation_set_operations_match(self):
        for backend, app in await self.make_backends():
            with self.subTest(backend=backend.name):
                self.assertEqual(await backend.list_simulation_sets("case"), ["set1"])
                await backend.run_simulation_set("case", "set1")
                await backend.add_task_to_set("case", "set1", "case")

                self.assertTrue(app.simsets["set1"].ran)
                self.assertEqual(app.simsets["set1"].tasks, ["case"])


if __name__ == "__main__":
    unittest.main()
