import json
import unittest
from collections.abc import Mapping
from decimal import Decimal

from pscad_mcp.core.backend.base import BackendError
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
        self.settings_data = {"time_duration": "0.5", "time_step": "50 [us]"}
        self.accept_settings = True

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
    def parameters(self): return dict(self.settings_data)
    def set_parameters(self, values):
        self.calls.append(("set_parameters", dict(values)))
        if not self.accept_settings:
            return False
        self.settings_data.update(values)
        return True


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
        self.settings_calls = []
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
        self.settings_calls.append(dict(updates))
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


if __name__ == "__main__":
    unittest.main()
