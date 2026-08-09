import asyncio
import json
import io
import os
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from pscad_mcp.core.backend.base import (
    BackendError,
    RunState,
    SimulationSetInfo,
    SimulationTaskInfo,
)
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.backend.legacy_support import project_kind
from pscad_mcp.core.backend.modern import ModernBackend
from tests.backend_fakes import (
    FakeLegacyAutomation,
    FakeModernPscad,
    ImmediateExecutor,
)


def write_project_file(
    path: Path, name: str, kind: str, *, include_output: bool = True
) -> None:
    root = ET.Element(
        "project",
        {"name": name, "Target": "EMTDC" if kind == "case" else "Library"},
    )
    if include_output:
        ET.SubElement(root, "output", {"name": name})
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class FakeProject:
    def __init__(self, name="case", kind="Case", definition_path=None):
        self.name = name
        self.type = kind
        self.description = "Example"
        self.filename = f"{name}.pscx"
        self.definition_path = Path(definition_path) if definition_path else None
        self.calls = []
        self.settings_data = {"time_duration": "0.5", "time_step": "50 [us]"}
        self.accept_settings = True
        self.native_save_as_response = ET.Element("response", {"success": "true"})
        self.native_save_as_writes = True
        self.native_save_as_payload = None
        self.run_command = FakeCommand(self, "run")
        self.run_status_response = ("running", 50.0)
        self.run_status_responses = []
        self.run_status_args = ()
        self.run_status_kwargs = {}
        self.run_status_callback_enabled = True
        self.run_status_callback_threaded = False
        self.run_status_requires_pump = False
        self._pending_run_status_callback = None

    def save(self): self.calls.append(("save",))
    def save_as(self, *args, **kwargs):
        self.calls.append(("save_as", args, kwargs))
        if args and self.native_save_as_writes:
            destination = Path(args[0])
            if self.native_save_as_payload is not None:
                destination.write_bytes(self.native_save_as_payload)
            elif self.definition_path is not None:
                root = ET.parse(self.definition_path).getroot()
                old_name = root.get("name")
                root.set("name", destination.stem)
                for output in root.findall("./output"):
                    if output.get("name") == old_name:
                        output.set("name", destination.stem)
                ET.ElementTree(root).write(
                    destination, encoding="utf-8", xml_declaration=True
                )
        return self.native_save_as_response
    def build(self): self.calls.append(("build",))
    def run(self): self.calls.append(("run",))
    def pause(self):
        self.calls.append(("pause",))
        self.run_status_response = ("paused", 50.0)
    def stop(self):
        self.calls.append(("stop",))
        self.run_status_response = ("stopped", 100.0)
    def run_status(self):
        return self.run_status_response
    def command(self, name):
        self.calls.append(("command", name))
        if name != "run":
            raise KeyError(name)
        return self.run_command
    def get_run_status(self, callback):
        self.calls.append(("get_run_status",))
        if not self.run_status_callback_enabled:
            return None
        if self.run_status_requires_pump:
            self._pending_run_status_callback = callback
            return None

        self._send_run_status(callback)
        return None

    def _send_run_status(self, callback):

        def send():
            if self.run_status_responses:
                self.run_status_response = self.run_status_responses.pop(0)
            callback(
                self.run_status_response,
                *self.run_status_args,
                **self.run_status_kwargs,
            )

        if self.run_status_callback_threaded:
            thread = threading.Thread(target=send)
            thread.start()
            thread.join()
        else:
            send()

    def pump_run_status(self):
        callback = self._pending_run_status_callback
        self._pending_run_status_callback = None
        if callback is not None:
            self._send_run_status(callback)
    def definitions(self): return ["master:source", "master:ground"]
    def list_definitions(self): return ["source", "ground"]
    def output(self): return "modern output"
    def messages(self): return [("legacy output", "build", "normal", self.name, "", 0, 0)]
    def parameters(self): return dict(self.settings_data)
    def set_parameters(self, values):
        self.calls.append(("set_parameters", dict(values)))
        if not self.accept_settings:
            return False
        self.settings_data.update(values)
        return True


class FakeCommand:
    def __init__(self, owner, name, response=None):
        self.owner = owner
        self.name = name
        self.response = (
            response
            if response is not None
            else ET.Element("response", {"success": "true"})
        )
        self.execute_args = []

    def execute(self, wait_for_response=True):
        self.execute_args.append(wait_for_response)
        calls = getattr(self.owner, "calls", None)
        if calls is not None:
            calls.append(("execute", self.name, wait_for_response))
        succeeded = not (
            isinstance(self.response, ET.Element)
            and self.response.get("success", "true").casefold() == "false"
        )
        effect = getattr(self.owner, "command_effects", {}).get(self.name)
        if succeeded and callable(effect):
            effect()
        return self.response if wait_for_response else None


class ItemsProxy:
    def __init__(self, values):
        self.values = values

    def items(self):
        return self.values.items()


class InvalidItemsProxy:
    def __init__(self):
        self.items_called = False

    def items(self):
        self.items_called = True
        return ["not a key-value pair"]


class RaisingItemsProxy:
    def items(self):
        raise RuntimeError("vendor mapping failed")


class BrokenMapping(Mapping):
    def __getitem__(self, _key):
        raise KeyError

    def __iter__(self):
        raise RuntimeError("mapping iteration failed")

    def __len__(self):
        return 1


class HostileProxy:
    def __str__(self):
        raise AssertionError("diagnostics must not stringify vendor proxies")

    def __repr__(self):
        raise AssertionError("diagnostics must not repr vendor proxies")


def xml_response(success=True):
    return ET.Element("commandresponse", {"success": "true" if success else "false"})


class FakeTasks(dict):
    def __eq__(self, other):
        if isinstance(other, list):
            return list(self) == other
        return super().__eq__(other)


class FakeSimulationTask:
    def __init__(self, name, *, modern=False):
        self.name = name
        self.modern = modern
        self.values = {"namespace": name, "controlgroup": "", "volley": 1, "affinity": 1}
        if modern:
            self.values.pop("controlgroup")
        self.fail_on = set()
        self.fail_restore_on = set()
        self.original = dict(self.values)

    def namespace(self): return self.values["namespace"]

    def _set(self, key, value):
        if key in self.fail_on or (value == self.original[key] and key in self.fail_restore_on):
            raise RuntimeError(f"failed {key}")
        self.values[key] = value

    def controlgroup(self, value=None):
        if self.modern:
            raise AttributeError("controlgroup unavailable")
        if value is not None: self._set("controlgroup", value)
        return self.values["controlgroup"]

    def volley(self, value=None):
        if value is not None: self._set("volley", value)
        return self.values["volley"]

    def affinity(self, value=None):
        if value is not None: self._set("affinity", value)
        return self.values["affinity"]

    def parameters(self, **updates):
        if not self.modern:
            raise AttributeError("parameters unavailable")
        if updates:
            for key, value in updates.items():
                self._set(key, value)
            return None
        return dict(self.values)


class FakeSimulationSet:
    def __init__(self, name="set1", *, modern=False):
        self.set_name = name
        self.modern = modern
        self.ran = False
        self.tasks = FakeTasks()
        self.add_response = xml_response()
        self.remove_response = xml_response()

    def run(self): self.ran = True
    def name(self): return self.set_name
    def depends_on(self): return "None"
    def list_tasks(self): return list(self.tasks)
    def task(self, name): return self.tasks[name]
    def add_tasks(self, *names):
        for name in names:
            self.tasks[name] = FakeSimulationTask(name, modern=self.modern)
        return self.add_response
    def remove_tasks(self, *names):
        for name in names:
            self.tasks.pop(name, None)
        return self.remove_response


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
    def simulation_set(self, name): return self.app.simsets[name]
    def create_simulation_set(self, name):
        self.app.simsets[name] = FakeSimulationSet(name)
        return self.app.create_set_response
    def remove_simulation_set(self, name):
        self.app.simsets.pop(name, None)
        return self.app.remove_set_response


class FakeLegacyApp:
    def __init__(self):
        self.project_map = {"case": FakeProject()}
        self.simsets = {"set1": FakeSimulationSet()}
        self.create_set_response = xml_response()
        self.remove_set_response = xml_response()
        self.loaded = []
        self.settings_data = {"fortran_version": "GFortran"}
        self.settings_calls = []
        self.workspace_proxy = FakeWorkspace(self)
        self.built_all = False
        self.fail_load_names = set()
        self.hidden_load_names = set()
        self.loaded_type_overrides = {}
        self.command_calls = []
        self.command_responses = {
            "ID_RIBBON_HOME_RUN_PAUSE": ET.Element(
                "response", {"success": "true"}
            ),
            "ID_RIBBON_HOME_RUN_STOP": ET.Element(
                "response", {"success": "true"}
            ),
        }
        self.command_effects = {
            "ID_RIBBON_HOME_RUN_PAUSE": lambda: self._set_all_run_states(
                "paused"
            ),
            "ID_RIBBON_HOME_RUN_STOP": lambda: self._set_all_run_states(
                "stopped"
            ),
        }

    def _set_all_run_states(self, status):
        progress = 100.0 if status == "stopped" else 50.0
        for project in self.project_map.values():
            if project.type.casefold() == "case":
                project.run_status_response = (status, progress)

    def is_alive(self): return True
    def licensed(self): return True
    def load(self, *filenames):
        for filename in filenames:
            self.loaded.append(filename)
            path = Path(filename)
            root = ET.parse(path).getroot()
            if root.tag != "project" or not root.get("name"):
                raise ValueError("Fake PSCAD accepts only a named <project> XML root.")
            name = root.get("name")
            kind = project_kind(root, path.suffix)
            if name in self.fail_load_names:
                raise RuntimeError(f"PSCAD refused to load {name}")
            if name in self.hidden_load_names:
                continue
            loaded_type = self.loaded_type_overrides.get(
                name, "Case" if kind == "case" else "Library"
            )
            self.project_map[name] = FakeProject(name, loaded_type, path)
    def list_projects(self):
        for project in self.project_map.values():
            project.pump_run_status()
        return [{"name": p.name, "type": p.type, "description": p.description} for p in self.project_map.values()]
    def project(self, name): return self.project_map[name]
    def workspace(self): return self.workspace_proxy
    def build_all(self): self.built_all = True
    def settings(self, settings=None, **kwargs):
        updates = dict(settings or {}, **kwargs)
        self.settings_calls.append(dict(updates))
        if updates: self.settings_data.update(updates)
        return dict(self.settings_data)
    def simulation_set(self, name): return self.simsets[name]
    def _command_id_cmd(self, command_id):
        self.command_calls.append(command_id)
        return FakeCommand(
            self,
            command_id,
            self.command_responses[command_id],
        )
    def quit(self): pass


class FakeModernApp(FakeLegacyApp):
    version = "5.0.2"
    workspace_path = r"D:\PSCAD-Workspace"

    def __init__(self):
        super().__init__()
        self.simsets = {"set1": FakeSimulationSet(modern=True)}

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
    def create_simulation_set(self, name):
        self.simsets[name] = FakeSimulationSet(name, modern=True)
        return self.create_set_response
    def remove_simulation_set(self, name):
        self.simsets.pop(name, None)
        return self.remove_set_response


class TestLegacyProjectFiles(unittest.IsolatedAsyncioTestCase):
    async def make_backend(self):
        app = FakeLegacyApp()
        backend = LegacyBackend(
            ImmediateExecutor(),
            version="4.6.2",
            x64=True,
            automation_module=FakeLegacyAutomation(app),
        )
        await backend.attach()
        return backend, app

    async def load_source(self, backend, app, folder: str, kind: str = "case"):
        suffix = ".pscx" if kind == "case" else ".pslx"
        source = Path(folder) / f"source{suffix}"
        write_project_file(source, "source", kind)
        await backend.load_projects([str(source)])
        return source, app.project_map["source"]

    def assert_project_identity(
        self, destination: Path, expected_name: str, *, require_output: bool
    ) -> None:
        root = ET.parse(destination).getroot()
        self.assertEqual(root.tag, "project")
        self.assertEqual(root.get("name"), expected_name)
        outputs = root.findall("./output")
        if require_output:
            self.assertTrue(outputs)
        self.assertTrue(
            all(output.get("name") == expected_name for output in outputs)
        )

    async def test_legacy_creates_case_from_verified_template(self):
        with tempfile.TemporaryDirectory() as folder:
            backend, app = await self.make_backend()
            destination = Path(folder) / "created_case.pscx"

            self.assertFalse(destination.exists())
            self.assertNotIn("created_case", backend.definition_paths)
            info = await backend.create_project(
                "case", destination.name, str(destination.parent)
            )

            self.assertTrue(destination.is_file())
            self.assert_project_identity(
                destination, "created_case", require_output=False
            )
            self.assertNotIn(
                "empty_case:", destination.read_text(encoding="utf-8")
            )
            self.assertIn(
                "created_case:Main", destination.read_text(encoding="utf-8")
            )
            self.assertEqual((info.name, info.type), ("created_case", "Case"))
            self.assertIn("created_case", app.project_map)
            self.assertEqual(
                backend.definition_paths["created_case"], destination.resolve()
            )

    async def test_legacy_creates_library_from_verified_template(self):
        with tempfile.TemporaryDirectory() as folder:
            backend, app = await self.make_backend()
            destination = Path(folder) / "created_library.pslx"

            self.assertFalse(destination.exists())
            self.assertNotIn("created_library", backend.definition_paths)
            info = await backend.create_project(
                "library", destination.name, str(destination.parent)
            )

            self.assertTrue(destination.is_file())
            self.assert_project_identity(
                destination, "created_library", require_output=False
            )
            self.assertNotIn(
                "empty_library:", destination.read_text(encoding="utf-8")
            )
            self.assertIn(
                "created_library:Main",
                destination.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (info.name, info.type), ("created_library", "Library")
            )
            self.assertIn("created_library", app.project_map)
            self.assertEqual(
                backend.definition_paths["created_library"],
                destination.resolve(),
            )

    async def test_legacy_create_cleans_owned_file_and_restores_existing_on_load_failure(self):
        for preexisting in (False, True):
            with self.subTest(preexisting=preexisting):
                with tempfile.TemporaryDirectory() as folder:
                    backend, app = await self.make_backend()
                    destination = Path(folder) / "rejected.pscx"
                    original = None
                    if preexisting:
                        write_project_file(destination, "original", "case")
                        original = destination.read_bytes()
                    app.fail_load_names.add("rejected")

                    with self.assertRaises(RuntimeError):
                        await backend.create_project(
                            "case", destination.name, str(destination.parent)
                        )

                    self.assertNotIn("rejected", backend.definition_paths)
                    if preexisting:
                        self.assertEqual(destination.read_bytes(), original)
                    else:
                        self.assertFalse(destination.exists())

    async def test_legacy_create_parses_rewritten_temp_before_atomic_replace(self):
        with tempfile.TemporaryDirectory() as folder:
            backend, _app = await self.make_backend()
            destination = Path(folder) / "protected.pscx"
            write_project_file(destination, "original", "case")
            original = destination.read_bytes()

            def write_malformed(_source, temporary, _new_name, **_kwargs):
                Path(temporary).write_text("<project", encoding="utf-8")

            with patch(
                "pscad_mcp.core.backend.legacy_support.rewrite_template_identity",
                side_effect=write_malformed,
            ):
                with self.assertRaises(ET.ParseError):
                    await backend.create_project(
                        "case", destination.name, str(destination.parent)
                    )

            self.assertEqual(destination.read_bytes(), original)
            self.assertNotIn("protected", backend.definition_paths)

    async def test_legacy_create_keeps_backup_when_restore_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            backend, app = await self.make_backend()
            destination = Path(folder) / "unverified.pscx"
            write_project_file(destination, "original", "case")
            original = destination.read_bytes()
            app.hidden_load_names.add("unverified")
            original_replace = os.replace

            def fail_restore(source_path, destination_path):
                source = Path(source_path)
                if (
                    source.suffix == ".bak"
                    and Path(destination_path).resolve() == destination.resolve()
                ):
                    raise PermissionError("restore blocked")
                return original_replace(source_path, destination_path)

            with patch("os.replace", side_effect=fail_restore):
                with self.assertRaises(PermissionError):
                    await backend.create_project(
                        "case", destination.name, str(destination.parent)
                    )

            backups = list(destination.parent.glob(f".{destination.name}.*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertNotIn("unverified", backend.definition_paths)

    async def test_legacy_create_rejects_kind_suffix_mismatch_without_touching_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            backend, _app = await self.make_backend()
            destination = Path(folder) / "protected.pslx"
            write_project_file(destination, "original", "library")
            original = destination.read_bytes()

            with self.assertRaises(ValueError):
                await backend.create_project(
                    "case", destination.name, str(destination.parent)
                )

            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(backend.definition_paths, {})

    async def test_legacy_save_as_accepts_only_verified_native_success(self):
        with tempfile.TemporaryDirectory() as folder:
            backend, app = await self.make_backend()
            _source, project = await self.load_source(backend, app, folder)
            destination = Path(folder) / "native_copy.pscx"
            project.native_save_as_response = ET.Element(
                "response", {"success": "true"}
            )

            await backend.save_project_as(
                "source", destination.name, str(destination.parent)
            )

            self.assertTrue(destination.is_file())
            self.assert_project_identity(
                destination, "native_copy", require_output=True
            )
            self.assertIn("native_copy", app.project_map)
            self.assertEqual(
                backend.definition_paths["native_copy"], destination.resolve()
            )
            self.assertNotIn(("save",), project.calls)

    async def test_legacy_save_as_existing_destination_uses_atomic_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            backend, app = await self.make_backend()
            _source, project = await self.load_source(backend, app, folder)
            destination = Path(folder) / "existing_copy.pscx"
            write_project_file(destination, "previous", "case")
            project.native_save_as_response = ET.Element(
                "response", {"success": "true"}
            )

            await backend.save_project_as(
                "source", destination.name, str(destination.parent)
            )

            self.assertFalse(
                any(call[0] == "save_as" for call in project.calls)
            )
            self.assertIn(("save",), project.calls)
            self.assert_project_identity(
                destination, "existing_copy", require_output=True
            )

    async def test_legacy_save_as_false_response_uses_verified_atomic_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            backend, app = await self.make_backend()
            source, project = await self.load_source(backend, app, folder)
            source.write_text(
                '<project name="source" Target="EMTDC">'
                '<output name="source" />'
                '<User defn="source:Main" />'
                '<call name="source:Station" />'
                '<param value="source must remain" />'
                '</project>',
                encoding="utf-8",
            )
            source_original = source.read_bytes()
            destination = Path(folder) / "fallback_copy.pscx"
            write_project_file(destination, "previous", "case")
            project.native_save_as_response = ET.Element(
                "response", {"success": "false"}
            )
            project.native_save_as_writes = False
            original_replace = os.replace
            replacement_observations = []

            def observe_replace(source_path, destination_path):
                if Path(destination_path).resolve() == destination.resolve():
                    replacement_observations.append(destination.exists())
                return original_replace(source_path, destination_path)

            with patch("os.replace", side_effect=observe_replace):
                await backend.save_project_as(
                    "source", destination.name, str(destination.parent)
                )

            self.assertTrue(destination.is_file())
            self.assert_project_identity(
                destination, "fallback_copy", require_output=True
            )
            self.assertTrue(replacement_observations)
            self.assertTrue(all(replacement_observations))
            self.assertEqual(source.read_bytes(), source_original)
            destination_text = destination.read_text(encoding="utf-8")
            self.assertNotIn("source:Main", destination_text)
            self.assertNotIn("source:Station", destination_text)
            self.assertIn("fallback_copy:Main", destination_text)
            self.assertIn("fallback_copy:Station", destination_text)
            self.assertIn("source must remain", destination_text)
            self.assertIn(("save",), project.calls)
            self.assertIn("fallback_copy", app.project_map)
            self.assertEqual(
                backend.definition_paths["fallback_copy"], destination.resolve()
            )

    async def test_legacy_save_as_fallback_cleans_owned_file_and_restores_existing_on_verification_failure(self):
        for preexisting in (False, True):
            with self.subTest(preexisting=preexisting):
                with tempfile.TemporaryDirectory() as folder:
                    backend, app = await self.make_backend()
                    _source, project = await self.load_source(
                        backend, app, folder
                    )
                    destination = Path(folder) / "unverified.pscx"
                    original = None
                    if preexisting:
                        write_project_file(destination, "original", "case")
                        original = destination.read_bytes()
                    project.native_save_as_response = ET.Element(
                        "response", {"success": "false"}
                    )
                    project.native_save_as_payload = b"<project"
                    app.hidden_load_names.add("unverified")

                    with self.assertRaises(BackendError) as raised:
                        await backend.save_project_as(
                            "source", destination.name, str(destination.parent)
                        )

                    self.assertEqual(
                        raised.exception.code, "POSTCONDITION_FAILED"
                    )
                    self.assertEqual(
                        raised.exception.details,
                        {
                            "path": str(destination.resolve()),
                            "expected_name": "unverified",
                            "expected_type": "Case",
                        },
                    )
                    self.assertNotIn("unverified", backend.definition_paths)
                    if preexisting:
                        self.assertEqual(destination.read_bytes(), original)
                    else:
                        self.assertFalse(destination.exists())

    async def test_legacy_save_as_uses_fallback_for_unusable_or_incomplete_native_result(self):
        responses = (
            None,
            object(),
            ET.Element("response", {"success": "true"}),
        )
        for response in responses:
            with self.subTest(response_type=type(response).__name__):
                with tempfile.TemporaryDirectory() as folder:
                    backend, app = await self.make_backend()
                    _source, project = await self.load_source(
                        backend, app, folder
                    )
                    destination = Path(folder) / "fallback.pscx"
                    project.native_save_as_response = response
                    project.native_save_as_writes = False

                    await backend.save_project_as(
                        "source", destination.name, str(destination.parent)
                    )

                    self.assertTrue(destination.is_file())
                    self.assert_project_identity(
                        destination, "fallback", require_output=True
                    )
                    self.assertIn(("save",), project.calls)
                    self.assertEqual(
                        backend.definition_paths["fallback"],
                        destination.resolve(),
                    )

    async def test_legacy_save_as_does_not_fallback_after_native_parse_error(self):
        with tempfile.TemporaryDirectory() as folder:
            backend, app = await self.make_backend()
            _source, project = await self.load_source(backend, app, folder)
            destination = Path(folder) / "malformed.pscx"
            project.native_save_as_response = ET.Element(
                "response", {"success": "true"}
            )
            project.native_save_as_payload = b"<project"

            with self.assertRaises(ET.ParseError):
                await backend.save_project_as(
                    "source", destination.name, str(destination.parent)
                )

            self.assertNotIn(("save",), project.calls)
            self.assertNotIn("malformed", backend.definition_paths)

    async def test_legacy_save_as_rejects_stale_native_output_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            backend, app = await self.make_backend()
            _source, project = await self.load_source(backend, app, folder)
            destination = Path(folder) / "native_copy.pscx"
            project.native_save_as_response = ET.Element(
                "response", {"success": "true"}
            )
            project.native_save_as_payload = (
                b'<project name="native_copy" Target="EMTDC">'
                b'<output name="source" /></project>'
            )

            with self.assertRaises(ValueError):
                await backend.save_project_as(
                    "source", destination.name, str(destination.parent)
                )

            self.assertFalse(destination.exists())
            self.assertNotIn(("save",), project.calls)
            self.assertNotIn("native_copy", backend.definition_paths)

    async def test_legacy_save_as_rejects_kind_suffix_mismatch_before_native_call(self):
        with tempfile.TemporaryDirectory() as folder:
            backend, app = await self.make_backend()
            _source, project = await self.load_source(backend, app, folder)
            destination = Path(folder) / "wrong.pslx"

            with self.assertRaises(ValueError):
                await backend.save_project_as(
                    "source", destination.name, str(destination.parent)
                )

            self.assertFalse(destination.exists())
            self.assertFalse(
                any(call[0] == "save_as" for call in project.calls)
            )
            self.assertNotIn("wrong", backend.definition_paths)


class TestLegacyRunControl(unittest.IsolatedAsyncioTestCase):
    async def make_backend(self):
        app = FakeLegacyApp()
        backend = LegacyBackend(
            ImmediateExecutor(),
            version="4.6.2",
            x64=True,
            automation_module=FakeLegacyAutomation(app),
        )
        await backend.attach()
        return backend, app, app.project_map["case"]

    async def test_run_uses_nonblocking_command_and_allows_immediate_status(self):
        backend, _app, project = await self.make_backend()
        project.run_status_response = {"status": "running", "progress": 12}

        await asyncio.wait_for(backend.run_project("case"), 0.1)
        state = await asyncio.wait_for(backend.project_run_state("case"), 0.1)

        self.assertEqual(project.run_command.execute_args, [False])
        self.assertNotIn(("run",), project.calls)
        self.assertEqual(state, RunState("running", 12.0))
        self.assertIn("case", backend._running_projects)

    async def test_status_maps_xml_tuple_and_dict_callback_payloads(self):
        backend, _app, project = await self.make_backend()
        xml_response = ET.fromstring(
            '<messages><response success="true" sequence-id="7">'
            '<run-status status="Run" percent="37" />'
            "</response></messages>"
        )
        cases = (
            (xml_response, (), {}, RunState("running", 37.0)),
            (("Build", None), (), {}, RunState("building", None)),
            ({"state": "Paused", "percentage": "64.5"}, (), {}, RunState("paused", 64.5)),
            (object(), ("Stopped", 100), {}, RunState("stopped", 100.0)),
            (object(), (), {"status": "Idle", "progress": None}, RunState("idle", None)),
        )

        for response, args, kwargs, expected in cases:
            with self.subTest(expected=expected):
                project.run_status_response = response
                project.run_status_args = args
                project.run_status_kwargs = kwargs
                project.run_status_callback_threaded = expected.status == "paused"
                self.assertEqual(
                    await backend.project_run_state("case"),
                    expected,
                )

    async def test_status_maps_real_legacy_build_run_transition(self):
        backend, _app, project = await self.make_backend()
        await backend.run_project("case")

        def response(build: bool, run: bool):
            return ET.fromstring(
                '<commandresponse success="true">'
                f'<build value="{str(build).lower()}" />'
                f'<run value="{str(run).lower()}" />'
                "</commandresponse>"
            )

        project.run_status_response = response(False, False)
        self.assertEqual(
            await backend.project_run_state("case"),
            RunState("starting", None),
        )
        project.run_status_response = response(True, False)
        self.assertEqual(
            await backend.project_run_state("case"),
            RunState("building", None),
        )
        project.run_status_response = response(False, True)
        self.assertEqual(
            await backend.project_run_state("case"),
            RunState("running", None),
        )
        project.run_status_response = response(False, False)
        self.assertEqual(
            await backend.project_run_state("case"),
            RunState("idle", None),
        )
        self.assertNotIn("case", backend._running_projects)

    async def test_status_does_not_remain_starting_after_grace_period(self):
        backend, _app, project = await self.make_backend()
        await backend.run_project("case")
        project.run_status_response = ET.fromstring(
            '<commandresponse success="true">'
            '<build value="false" /><run value="false" />'
            "</commandresponse>"
        )

        with patch.object(LegacyBackend, "RUN_START_GRACE", 0, create=True):
            state = await backend.project_run_state("case")

        self.assertEqual(state, RunState("idle", None))
        self.assertNotIn("case", backend._running_projects)

    async def test_status_timeout_is_bounded(self):
        backend, _app, project = await self.make_backend()
        project.run_status_callback_enabled = False

        with patch.object(LegacyBackend, "RUN_STATUS_TIMEOUT", 0.01, create=True):
            with self.assertRaises(BackendError) as raised:
                await backend.project_run_state("case")

        self.assertEqual(raised.exception.code, "PSCAD_COMMAND_TIMEOUT")
        self.assertEqual(raised.exception.operation, "get_run_status")

    async def test_status_pumps_legacy_socket_after_posting_callback(self):
        backend, _app, project = await self.make_backend()
        project.run_status_requires_pump = True
        project.run_status_response = {"status": "running", "progress": 23}

        with patch.object(LegacyBackend, "RUN_STATUS_TIMEOUT", 0.1):
            state = await backend.project_run_state("case")

        self.assertEqual(state, RunState("running", 23.0))

    async def test_status_rejects_failed_or_unreadable_callback_payload(self):
        backend, _app, project = await self.make_backend()
        failures = (
            ET.fromstring(
                '<messages><response success="false" sequence-id="9" /></messages>'
            ),
            {"error": "status unavailable"},
        )
        for response in failures:
            with self.subTest(response_type=type(response).__name__):
                project.run_status_response = response
                with self.assertRaises(BackendError) as raised:
                    await backend.project_run_state("case")
                self.assertEqual(raised.exception.code, "PSCAD_COMMAND_FAILED")

        project.run_status_response = object()
        with self.assertRaises(BackendError) as raised:
            await backend.project_run_state("case")
        self.assertEqual(raised.exception.code, "UNEXPECTED_RESPONSE")

    async def test_status_bounds_cyclic_and_unhashable_error_payloads(self):
        backend, _app, project = await self.make_backend()
        project.run_status_response = {"error": ["status unavailable"]}
        with self.assertRaises(BackendError) as raised:
            await backend.project_run_state("case")
        self.assertEqual(raised.exception.code, "PSCAD_COMMAND_FAILED")

        cyclic = {}
        cyclic["nested"] = cyclic
        project.run_status_response = cyclic
        with self.assertRaises(BackendError) as raised:
            await backend.project_run_state("case")
        self.assertEqual(raised.exception.code, "UNEXPECTED_RESPONSE")

    async def test_terminal_status_clears_running_project_tracking(self):
        backend, _app, project = await self.make_backend()
        await backend.run_project("case")
        self.assertIn("case", backend._running_projects)
        project.run_status_response = {"status": "Completed", "progress": 100}

        state = await backend.project_run_state("case")

        self.assertEqual(state, RunState("completed", 100.0))
        self.assertNotIn("case", backend._running_projects)
        await backend.disconnect()
        self.assertEqual(backend._running_projects, set())

    async def test_pause_and_stop_use_validated_application_commands(self):
        backend, app, _project = await self.make_backend()
        output = io.StringIO()

        with redirect_stdout(output):
            await backend.pause_project("case")
        await backend.stop_project("case")

        self.assertEqual(output.getvalue(), "")
        self.assertEqual(
            app.command_calls,
            ["ID_RIBBON_HOME_RUN_PAUSE", "ID_RIBBON_HOME_RUN_STOP"],
        )

    async def test_pause_rejects_two_active_projects_without_sending_command(self):
        backend, app, project = await self.make_backend()
        other = FakeProject("other")
        app.project_map["other"] = other
        project.run_status_response = ("running", 20)
        other.run_status_response = ("building", None)

        with self.assertRaises(BackendError) as raised:
            await backend.pause_project("case")

        self.assertEqual(
            raised.exception.code, "RUN_CONTROL_SCOPE_CONFLICT"
        )
        self.assertEqual(
            raised.exception.details["active_projects"],
            {"case": "running", "other": "building"},
        )
        self.assertEqual(app.command_calls, [])

    async def test_stop_rejects_inactive_target_without_sending_command(self):
        backend, app, project = await self.make_backend()
        project.run_status_response = ("idle", None)

        with self.assertRaises(BackendError) as raised:
            await backend.stop_project("case")

        self.assertEqual(raised.exception.code, "RUN_NOT_ACTIVE")
        self.assertEqual(raised.exception.details["state"], "idle")
        self.assertEqual(app.command_calls, [])

    async def test_pause_and_stop_verify_postconditions(self):
        backend, _app, project = await self.make_backend()
        project.run_status_response = ("running", 25)

        await backend.pause_project("case")

        paused = await backend.project_run_state("case")
        self.assertEqual(paused.status, "paused")

        await backend.stop_project("case")

        stopped = await backend.project_run_state("case")
        self.assertIn(stopped.status, {"stopped", "idle", "completed"})

    async def test_pause_tracks_state_when_legacy_status_stays_running(self):
        backend, app, project = await self.make_backend()
        project.run_status_response = ("running", 25)
        app.command_effects["ID_RIBBON_HOME_RUN_PAUSE"] = lambda: None

        with patch.object(LegacyBackend, "RUN_CONTROL_TIMEOUT", 0):
            await backend.pause_project("case")

        state = await backend.project_run_state("case")
        self.assertEqual(state.status, "paused")
        self.assertEqual(
            backend.session_details["paused_state_source"],
            "command-tracked",
        )
        self.assertEqual(
            backend.session_details["tracked_paused_projects"],
            ["case"],
        )

    async def test_run_and_terminal_status_clear_tracked_pause(self):
        backend, _app, project = await self.make_backend()
        project.run_status_response = ("running", 25)
        backend._paused_projects.add("case")

        await backend.run_project("case")

        self.assertEqual(
            (await backend.project_run_state("case")).status,
            "running",
        )
        self.assertEqual(backend._paused_projects, set())

        backend._paused_projects.add("case")
        project.run_status_response = ("idle", None)
        self.assertEqual(
            (await backend.project_run_state("case")).status,
            "idle",
        )
        self.assertEqual(backend._paused_projects, set())

    async def test_pause_waits_for_running_before_sending_global_command(self):
        backend, app, project = await self.make_backend()
        project.run_status_responses = [
            ("starting", None),
            ("running", 25),
        ]
        status_at_command = []

        def pause_effect():
            status_at_command.append(project.run_status_response[0])
            app._set_all_run_states("paused")

        app.command_effects["ID_RIBBON_HOME_RUN_PAUSE"] = pause_effect

        await backend.pause_project("case")

        self.assertEqual(status_at_command, ["running"])
        self.assertEqual(
            (await backend.project_run_state("case")).status,
            "paused",
        )

    async def test_pause_does_not_send_when_run_finishes_before_running(self):
        backend, app, project = await self.make_backend()
        project.run_status_responses = [
            ("starting", None),
            ("idle", None),
        ]

        with self.assertRaises(BackendError) as raised:
            await backend.pause_project("case")

        self.assertEqual(raised.exception.code, "RUN_NOT_ACTIVE")
        self.assertEqual(app.command_calls, [])

    async def test_pause_and_stop_reject_failed_command_responses(self):
        for operation, command_id in (
            ("pause_project", "ID_RIBBON_HOME_RUN_PAUSE"),
            ("stop_project", "ID_RIBBON_HOME_RUN_STOP"),
        ):
            with self.subTest(operation=operation):
                backend, app, _project = await self.make_backend()
                app.command_responses[command_id] = ET.Element(
                    "response", {"success": "false"}
                )
                with self.assertRaises(BackendError) as raised:
                    await getattr(backend, operation)("case")
                self.assertEqual(raised.exception.code, "PSCAD_COMMAND_FAILED")


class TestModernRunControl(unittest.IsolatedAsyncioTestCase):
    async def make_backend(self):
        app = FakeModernApp()
        backend = ModernBackend(
            ImmediateExecutor(),
            version="5.0.2",
            x64=True,
            pscad_module=FakeModernPscad(app),
            psout_module=False,
        )
        await backend.attach()
        return backend, app, app.project_map["case"]

    async def test_stop_prefers_single_project_api(self):
        backend, app, project = await self.make_backend()
        single_stop_calls = []

        def stop_single_project(target):
            single_stop_calls.append(target.name)
            target.run_status_response = ("stopped", 100.0)
            return True

        app.stop_single_project = stop_single_project

        await backend.stop_project("case")

        self.assertEqual(single_stop_calls, ["case"])
        self.assertNotIn(("stop",), project.calls)

    async def test_pause_rejects_multiple_active_projects(self):
        backend, app, _project = await self.make_backend()
        app.project_map["other"] = FakeProject("other")

        with self.assertRaises(BackendError) as raised:
            await backend.pause_project("case")

        self.assertEqual(
            raised.exception.code, "RUN_CONTROL_SCOPE_CONFLICT"
        )
        self.assertNotIn(("pause",), app.project_map["case"].calls)

    async def test_stop_rejects_inactive_target(self):
        backend, _app, project = await self.make_backend()
        project.run_status_response = ("idle", None)

        with self.assertRaises(BackendError) as raised:
            await backend.stop_project("case")

        self.assertEqual(raised.exception.code, "RUN_NOT_ACTIVE")
        self.assertNotIn(("stop",), project.calls)


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

    async def legacy_with_task(self, set_name="Batch1", task_name="case"):
        backend, app = (await self.make_backends())[0]
        app.simsets[set_name] = FakeSimulationSet(set_name)
        app.simsets[set_name].tasks[task_name] = FakeSimulationTask(task_name)
        return backend, app

    async def test_project_lifecycle_and_normalization_match(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "case.pscx"
            write_project_file(source, "case", "case")
            for backend, app in await self.make_backends():
                with self.subTest(backend=backend.name):
                    await backend.load_projects([str(source)])
                    projects = await backend.list_projects()
                    await backend.run_project("case")
                    await backend.pause_project("case")
                    await backend.stop_project("case")
                    state = await backend.project_run_state("case")
                    await backend.save_project("case")
                    await backend.save_project_as("case", "copy.pscx", folder)
                    await backend.build_project("case")
                    await backend.build_all_projects()

                    self.assertEqual(projects[0].name, "case")
                    self.assertEqual(projects[0].type, "Case")
                    self.assertEqual(state.status, "stopped")
                    self.assertEqual(state.progress, 100.0)
                    expected_loads = [str(source)]
                    if backend.name == "legacy":
                        expected_loads.append(str(Path(folder) / "copy.pscx"))
                    self.assertEqual(
                        [str(Path(path).resolve()) for path in app.loaded],
                        [str(Path(path).resolve()) for path in expected_loads],
                    )
                    self.assertTrue(app.built_all)

    async def test_create_definitions_settings_and_output_match(self):
        with tempfile.TemporaryDirectory() as folder:
            for backend, _app in await self.make_backends():
                with self.subTest(backend=backend.name):
                    case = await backend.create_project("case", "new.pscx", folder)
                    library = await backend.create_project(
                        "library", "lib.pslx", folder
                    )
                    await backend.set_settings(
                        "case", {"fortran_version": "Intel"}
                    )

                    self.assertEqual(case.name, "new")
                    self.assertEqual(library.type, "Library")
                    self.assertEqual(
                        (await backend.get_settings("case"))["fortran_version"],
                        "Intel",
                    )
                    self.assertEqual(
                        len(await backend.project_definitions("case")), 2
                    )
                    self.assertIn("output", await backend.project_output("case"))

    async def test_legacy_get_settings_uses_selected_project_not_application(self):
        legacy, app = (await self.make_backends())[0]
        project = app.project_map["case"]
        project.settings_data = {"time_duration": "1.0"}
        app.settings_data = {"application_only": "wrong scope"}

        self.assertEqual(await legacy.get_settings("case"), {"time_duration": "1.0"})
        self.assertEqual(app.settings_calls, [])

    async def test_legacy_get_settings_honors_project_name(self):
        legacy, app = (await self.make_backends())[0]
        app.project_map["other"] = FakeProject("other")
        app.project_map["other"].settings_data = {"time_duration": "2.0"}

        self.assertEqual(await legacy.get_settings("other"), {"time_duration": "2.0"})
        self.assertEqual(app.settings_calls, [])

    async def test_legacy_get_settings_rejects_non_mapping_response(self):
        legacy, app = (await self.make_backends())[0]
        app.project_map["case"].parameters = lambda: object()

        with self.assertRaises(BackendError) as raised:
            await legacy.get_settings("case")

        self.assertEqual(raised.exception.code, "UNEXPECTED_RESPONSE")
        self.assertEqual(raised.exception.operation, "get_project_settings")

    async def test_legacy_get_settings_accepts_mapping_like_items_proxy(self):
        legacy, app = (await self.make_backends())[0]
        app.project_map["case"].parameters = lambda: ItemsProxy(
            {"time_duration": "1.0"}
        )

        settings = await legacy.get_settings("case")

        self.assertEqual(settings, {"time_duration": "1.0"})
        self.assertIsInstance(settings, dict)

    async def test_legacy_get_settings_wraps_invalid_items_proxy_response(self):
        legacy, app = (await self.make_backends())[0]
        proxy = InvalidItemsProxy()
        app.project_map["case"].parameters = lambda: proxy

        with self.assertRaises(BackendError) as raised:
            await legacy.get_settings("case")

        self.assertEqual(raised.exception.code, "UNEXPECTED_RESPONSE")
        self.assertEqual(raised.exception.operation, "get_project_settings")
        self.assertTrue(proxy.items_called)

    async def test_legacy_get_settings_wraps_raising_items_proxy_response(self):
        legacy, app = (await self.make_backends())[0]
        app.project_map["case"].parameters = lambda: RaisingItemsProxy()

        with self.assertRaises(BackendError) as raised:
            await legacy.get_settings("case")

        self.assertEqual(raised.exception.code, "UNEXPECTED_RESPONSE")
        self.assertEqual(raised.exception.operation, "get_project_settings")

    async def test_legacy_set_settings_uses_project_proxy_not_application(self):
        legacy, app = (await self.make_backends())[0]
        project = app.project_map["case"]

        await legacy.set_settings("case", {"time_duration": "1.0"})

        self.assertEqual(project.calls, [("set_parameters", {"time_duration": "1.0"})])
        self.assertEqual(project.settings_data["time_duration"], "1.0")
        self.assertEqual(app.settings_calls, [])

    async def test_legacy_set_settings_accepts_mapping_like_readback(self):
        legacy, app = (await self.make_backends())[0]
        project = app.project_map["case"]
        project.set_parameters = lambda _values: True
        project.parameters = lambda: ItemsProxy({"time_duration": "1.0"})

        await legacy.set_settings("case", {"time_duration": "1.0"})

        self.assertEqual(app.settings_calls, [])

    async def test_legacy_set_settings_rejects_unaccepted_project_parameters(self):
        legacy, app = (await self.make_backends())[0]
        app.project_map["case"].accept_settings = False

        with self.assertRaises(BackendError) as raised:
            await legacy.set_settings("case", {"z": 1, "a": 2})

        self.assertEqual(raised.exception.code, "INVALID_PARAMETER")
        self.assertEqual(raised.exception.operation, "set_project_settings")
        self.assertEqual(
            raised.exception.details,
            {"project": "case", "keys": ["a", "z"]},
        )

    async def test_legacy_set_settings_rejects_non_mapping_input(self):
        legacy, _app = (await self.make_backends())[0]

        for invalid_settings in ([('time_duration', '1.0')], "invalid", 1):
            with self.subTest(settings_type=type(invalid_settings).__name__):
                with self.assertRaises(BackendError) as raised:
                    await legacy.set_settings("case", invalid_settings)

                self.assertEqual(raised.exception.code, "INVALID_PARAMETER")
                self.assertEqual(raised.exception.operation, "set_project_settings")
                self.assertEqual(
                    raised.exception.details,
                    {
                        "project": "case",
                        "reason": "settings must be a mapping",
                        "settings_type": type(invalid_settings).__name__,
                    },
                )
                json.dumps(raised.exception.details, allow_nan=False)

    async def test_legacy_set_settings_wraps_broken_mapping_copy(self):
        legacy, _app = (await self.make_backends())[0]

        with self.assertRaises(BackendError) as raised:
            await legacy.set_settings("case", BrokenMapping())

        self.assertEqual(raised.exception.code, "INVALID_PARAMETER")
        self.assertEqual(raised.exception.operation, "set_project_settings")
        self.assertEqual(
            raised.exception.details,
            {
                "project": "case",
                "reason": "settings mapping could not be copied",
                "settings_type": "BrokenMapping",
            },
        )
        self.assertIsNone(raised.exception.__cause__)
        json.dumps(raised.exception.details, allow_nan=False)

    async def test_legacy_set_settings_rejects_postcondition_mismatch(self):
        legacy, app = (await self.make_backends())[0]
        project = app.project_map["case"]

        def accept_without_updating(_values):
            return True

        project.set_parameters = accept_without_updating
        with self.assertRaises(BackendError) as raised:
            await legacy.set_settings("case", {"time_duration": "1.0"})

        self.assertEqual(raised.exception.code, "POSTCONDITION_FAILED")
        self.assertEqual(raised.exception.operation, "set_project_settings")
        self.assertEqual(
            raised.exception.details,
            {
                "project": "case",
                "mismatches": {
                    "time_duration": {"expected": "1.0", "actual": "0.5"},
                },
            },
        )

    async def test_legacy_set_settings_accepts_equivalent_numeric_values(self):
        legacy, app = (await self.make_backends())[0]
        project = app.project_map["case"]

        def normalize_numeric(_values):
            project.settings_data["time_duration"] = "0.5"
            return True

        project.set_parameters = normalize_numeric
        await legacy.set_settings("case", {"time_duration": 0.5})

        self.assertEqual(project.settings_data["time_duration"], "0.5")
        self.assertEqual(app.settings_calls, [])

    async def test_legacy_settings_numeric_comparison_handles_decimals_and_boundaries(self):
        self.assertTrue(
            LegacyBackend._settings_values_match(Decimal("0.1"), "0.1")
        )
        self.assertTrue(
            LegacyBackend._settings_values_match("1e-1", Decimal("0.1"))
        )
        self.assertFalse(
            LegacyBackend._settings_values_match(Decimal("NaN"), "NaN")
        )
        self.assertFalse(
            LegacyBackend._settings_values_match(Decimal("Infinity"), "Infinity")
        )
        self.assertFalse(LegacyBackend._settings_values_match(True, 1))
        self.assertFalse(LegacyBackend._settings_values_match(0, False))
        self.assertTrue(
            LegacyBackend._settings_values_match(["50 [us]"], ["50 [us]"])
        )
        self.assertTrue(
            LegacyBackend._settings_values_match({"mode": "fixed"}, {"mode": "fixed"})
        )

    async def test_legacy_set_settings_does_not_equate_boolean_and_number(self):
        legacy, app = (await self.make_backends())[0]
        project = app.project_map["case"]

        def normalize_to_number(_values):
            project.settings_data["enabled"] = 1
            return True

        project.set_parameters = normalize_to_number
        with self.assertRaises(BackendError) as raised:
            await legacy.set_settings("case", {"enabled": True})

        self.assertEqual(raised.exception.code, "POSTCONDITION_FAILED")
        self.assertEqual(
            raised.exception.details["mismatches"]["enabled"],
            {"expected": True, "actual": 1},
        )

    async def test_legacy_set_settings_uses_json_safe_mismatch_details(self):
        legacy, app = (await self.make_backends())[0]
        project = app.project_map["case"]

        def write_nan(_values):
            project.settings_data["time_duration"] = float("nan")
            return True

        project.set_parameters = write_nan
        with self.assertRaises(BackendError) as raised:
            await legacy.set_settings("case", {"time_duration": "1.0"})

        json.dumps(raised.exception.details, allow_nan=False)

    async def test_legacy_set_settings_bounds_hostile_proxy_diagnostics(self):
        legacy, app = (await self.make_backends())[0]
        project = app.project_map["case"]
        hostile_key = HostileProxy()
        project.settings_data = {
            hostile_key: {
                "x" * 1_000: [[HostileProxy() for _ in range(100)] for _ in range(100)],
                "x" * 1_000 + "different": [HostileProxy() for _ in range(100)],
            }
        }
        project.set_parameters = lambda _values: True

        with self.assertRaises(BackendError) as raised:
            await legacy.set_settings(
                "case", {hostile_key: "updated", 10 ** 1_000: "missing"}
            )

        self.assertEqual(raised.exception.code, "POSTCONDITION_FAILED")
        encoded = json.dumps(raised.exception.details, allow_nan=False)
        self.assertLessEqual(
            len(encoded), LegacyBackend.SETTING_DETAIL_MAX_SERIALIZED_CHARS
        )
        self.assertIn("HostileProxy", encoded)

        def detail_keys(value):
            if isinstance(value, dict):
                yield from value
                for item in value.values():
                    yield from detail_keys(item)
            elif isinstance(value, list):
                for item in value:
                    yield from detail_keys(item)

        self.assertTrue(
            all(
                len(key) <= LegacyBackend.SETTING_DETAIL_TEXT_LIMIT
                for key in detail_keys(json.loads(encoded))
            )
        )

    async def test_legacy_set_settings_bounds_mismatch_count(self):
        legacy, app = (await self.make_backends())[0]
        project = app.project_map["case"]
        project.settings_data = {}
        project.set_parameters = lambda _values: True
        requested = {
            f"parameter_{index}": index
            for index in range(LegacyBackend.SETTING_DETAIL_MAX_MISMATCHES + 2)
        }

        with self.assertRaises(BackendError) as raised:
            await legacy.set_settings("case", requested)

        self.assertEqual(
            len(raised.exception.details["mismatches"]),
            LegacyBackend.SETTING_DETAIL_MAX_MISMATCHES,
        )
        self.assertEqual(
            raised.exception.details["mismatch_count"], len(requested)
        )

    async def test_legacy_set_settings_bounds_vendor_rejection_keys(self):
        legacy, app = (await self.make_backends())[0]
        app.project_map["case"].accept_settings = False
        requested = {f"parameter_{index:05d}": index for index in range(10_000)}

        with self.assertRaises(BackendError) as raised:
            await legacy.set_settings("case", requested)

        self.assertEqual(raised.exception.code, "INVALID_PARAMETER")
        self.assertEqual(
            len(raised.exception.details["keys"]),
            LegacyBackend.SETTING_DETAIL_MAX_ENTRIES,
        )
        self.assertEqual(raised.exception.details["total_key_count"], len(requested))
        self.assertTrue(raised.exception.details["keys_truncated"])
        self.assertLessEqual(
            len(json.dumps(raised.exception.details, allow_nan=False)),
            LegacyBackend.SETTING_DETAIL_MAX_SERIALIZED_CHARS,
        )

    async def test_legacy_set_settings_bounds_oversized_integer_keys_and_values(self):
        legacy, app = (await self.make_backends())[0]
        project = app.project_map["case"]
        oversized_integer = 1 << 20_000
        project.settings_data = {oversized_integer: 0}
        project.set_parameters = lambda _values: True

        with self.assertRaises(BackendError) as raised:
            await legacy.set_settings(
                "case", {oversized_integer: oversized_integer}
            )

        self.assertEqual(raised.exception.code, "POSTCONDITION_FAILED")
        mismatch = next(iter(raised.exception.details["mismatches"].values()))
        self.assertEqual(
            mismatch["expected"],
            {
                "type": "int",
                "bit_length": oversized_integer.bit_length(),
                "sign": "positive",
            },
        )
        self.assertIn("bit_length", next(iter(raised.exception.details["mismatches"])))
        json.dumps(raised.exception.details, allow_nan=False)

    async def test_simulation_set_operations_match(self):
        for backend, app in await self.make_backends():
            with self.subTest(backend=backend.name):
                self.assertEqual(await backend.list_simulation_sets("case"), ["set1"])
                await backend.run_simulation_set("case", "set1")
                await backend.add_task_to_set("case", "set1", "case")

                self.assertTrue(app.simsets["set1"].ran)
                self.assertEqual(app.simsets["set1"].tasks, ["case"])

    async def test_legacy_simulation_set_crud_and_task_reads(self):
        backend, app = (await self.make_backends())[0]

        created = await backend.create_simulation_set("Batch1")
        self.assertEqual(created, SimulationSetInfo("Batch1", None, ()))

        await backend.add_task_to_set("ignored", "Batch1", "case")
        self.assertEqual(await backend.list_simulation_set_tasks("Batch1"), ["case"])
        self.assertEqual(
            await backend.get_simulation_task_parameters("Batch1", "case"),
            SimulationTaskInfo("case", "case", "", 1, 1),
        )
        details = await backend.get_simulation_set_details("Batch1")
        self.assertEqual(details.tasks, ("case",))

        await backend.remove_tasks_from_set("Batch1", ["case"])
        await backend.remove_simulation_set("Batch1")
        self.assertNotIn("Batch1", app.simsets)

    async def test_modern_simulation_set_crud_and_task_reads(self):
        backend, app = (await self.make_backends())[1]
        created = await backend.create_simulation_set("Batch1")
        self.assertEqual(created, SimulationSetInfo("Batch1", None, ()))
        await backend.add_task_to_set("ignored", "Batch1", "case")
        self.assertEqual(await backend.list_simulation_set_tasks("Batch1"), ["case"])
        task = await backend.get_simulation_task_parameters("Batch1", "case")
        self.assertIsNone(task.controlgroup)
        self.assertEqual((task.volley, task.affinity), (1, 1))
        updated = await backend.set_simulation_task_parameters(
            "Batch1", "case", {"volley": 2, "affinity": 3}
        )
        self.assertEqual((updated.volley, updated.affinity), (2, 3))
        with self.assertRaises(BackendError) as raised:
            await backend.set_simulation_task_parameters(
                "Batch1", "case", {"controlgroup": "A"}
            )
        self.assertEqual(raised.exception.code, "CAPABILITY_UNAVAILABLE")
        await backend.remove_tasks_from_set("Batch1", ["case"])
        await backend.remove_simulation_set("Batch1")
        self.assertNotIn("Batch1", app.simsets)

    async def test_legacy_task_parameter_update_reads_back(self):
        backend, _app = await self.legacy_with_task()
        result = await backend.set_simulation_task_parameters(
            "Batch1", "case", {"volley": 2, "affinity": 3}
        )
        self.assertEqual((result.volley, result.affinity), (2, 3))

    async def test_legacy_task_parameter_failure_restores_original_values(self):
        backend, app = await self.legacy_with_task()
        task = app.simsets["Batch1"].tasks["case"]
        task.fail_on.add("affinity")
        with self.assertRaises(RuntimeError):
            await backend.set_simulation_task_parameters(
                "Batch1", "case", {"volley": 2, "affinity": 3}
            )
        self.assertEqual(task.values["volley"], 1)

    async def test_legacy_task_parameter_failed_restore_is_partial_completion(self):
        backend, app = await self.legacy_with_task()
        task = app.simsets["Batch1"].tasks["case"]
        task.fail_on.add("affinity")
        task.fail_restore_on.add("volley")
        with self.assertRaises(BackendError) as raised:
            await backend.set_simulation_task_parameters(
                "Batch1", "case", {"volley": 2, "affinity": 3}
            )
        self.assertEqual(raised.exception.code, "PARTIAL_COMPLETION")
        self.assertEqual(raised.exception.details["observed"]["volley"], 2)


if __name__ == "__main__":
    unittest.main()
