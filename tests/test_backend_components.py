import copy
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.backend.legacy_support import Rect
from pscad_mcp.core.backend.modern import ModernBackend
from pscad_mcp.core.backend.base import BackendError
from tests.backend_fakes import (
    FakeLegacyAutomation,
    FakeModernPscad,
    ImmediateExecutor,
)


class StatefulComponent:
    def __init__(self, component_id=7, *, legacy=False, canvas=None):
        self.id = component_id
        self._id = (str(component_id),)
        self.name = "V1"
        self.defn_name = "master:source3"
        self.location = (10, 5)
        self.values = {"Name": "V1", "Gain": 5, "enabled": True}
        self.orientation = 0
        self.mirrored = False
        self.flipped = False
        self.deleted = False
        self.canvas = canvas
        self.legacy = legacy
        self.port_names = ["A", "B"]
        self.port_map = {
            "A": SimpleNamespace(name="A", x=9, y=5, dim=1, type="electrical"),
            "B": SimpleNamespace(name="B", x=11, y=5, dim=1, type="electrical"),
        }
        self.layers = ["USER_LAYER"]
        self.layer_calls = []
        self.layer_responses = {
            "add": ET.Element("response", {"success": "true"}),
            "remove": ET.Element("response", {"success": "true"}),
        }
        self.apply_layer_changes = True
        self.parameter_writes = []
        self.delete_error = None
        self.apply_delete = True

    def get_definition(self):
        return SimpleNamespace(scoped_name=self.defn_name)

    def get_location(self): return self.location
    def set_location(self, x, y): self.location = (x, y)
    def get_parameters(self): return dict(self.values)
    def set_parameters(self, **kwargs):
        self.parameter_writes.append(dict(kwargs))
        self.values.update(kwargs)
    def parameters(self, parameters=None):
        if parameters is not None:
            self.parameter_writes.append(dict(parameters))
            self.values.update(parameters)
        return dict(self.values)
    def range(self, name): return (0, 10)

    def rotate_right(self): self.orientation = (self.orientation + 90) % 360
    def rotate_left(self): self.orientation = (self.orientation - 90) % 360
    def rotate_180(self): self.orientation = (self.orientation + 180) % 360
    def mirror(self): self.mirrored = not self.mirrored
    def flip(self): self.flipped = not self.flipped
    def _generic(self, command):
        {
            "IDM_ROTATERIGHT": self.rotate_right,
            "IDM_ROTATELEFT": self.rotate_left,
            "IDM_ROTATE180": self.rotate_180,
            "IDM_MIRROR": self.mirror,
            "IDM_FLIP": self.flip,
        }[command]()

    def clone(self, x, y):
        clone = copy.copy(self)
        clone.id = max(c.id for c in self.canvas.components) + 1
        clone._id = (str(clone.id),)
        clone.name = "V1_copy"
        clone.location = (x, y)
        clone.deleted = False
        self.canvas.components.append(clone)
        return clone

    def copy(self): self.canvas.clipboard = self
    def delete(self):
        if self.canvas is not None:
            self.canvas.events.append(("component", self.id))
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted = True
        if self.canvas is not None and self.apply_delete:
            self.canvas.components = [c for c in self.canvas.components if c is not self]
    def ports(self): return dict(self.port_map)
    def port(self, name): return self.port_map.get(name)
    def get_port_location(self, name):
        port = self.port_map.get(name)
        return (port.x, port.y) if port else None
    def enable(self): self.values["enabled"] = True
    def disable(self): self.values["enabled"] = False
    def add_to_layer(self, name):
        self.layer_calls.append(("add", name))
        response = self.layer_responses["add"]
        if (
            self.apply_layer_changes
            and response.get("success", "").casefold() == "true"
            and name not in self.layers
        ):
            self.layers.append(name)
        return response
    def remove_from_layer(self, name):
        self.layer_calls.append(("remove", name))
        response = self.layer_responses["remove"]
        if (
            self.apply_layer_changes
            and response.get("success", "").casefold() == "true"
        ):
            self.layers = [layer for layer in self.layers if layer != name]
        return response


class StatefulCanvas:
    def __init__(self, legacy=False):
        self.components = []
        self.events = []
        self.clipboard = None
        self.legacy = legacy
        self.components.append(StatefulComponent(legacy=legacy, canvas=self))

    def find_all(self, *names, **params):
        result = list(self.components)
        if names:
            definition = names[0]
            if ":" in definition:
                result = [c for c in result if c.defn_name == definition]
            elif len(names) == 1:
                result = [c for c in result if c.name == definition]
        if len(names) > 1:
            result = [c for c in result if c.name == names[1]]
        return result

    def paste(self):
        clone = copy.copy(self.clipboard)
        clone.id = max(c.id for c in self.components) + 1
        clone._id = (str(clone.id),)
        clone.name = "V1_copy"
        clone.canvas = self
        clone.deleted = False
        self.components.append(clone)

    def add_component(self, library, name, x=0, y=0):
        clone = StatefulComponent(
            max(component.id for component in self.components) + 1,
            legacy=self.legacy,
            canvas=self,
        )
        clone.defn_name = f"{library}:{name}"
        clone.location = (x, y)
        self.components.append(clone)
        return clone

    def list_components(self):
        root = ET.Element("response", {"success": "true"})
        components = ET.SubElement(root, "components")
        for component in self.components:
            if isinstance(component, StatefulComponent):
                ET.SubElement(
                    components,
                    "User",
                    {
                        "id": str(component.id),
                        "layer": ";".join(component.layers),
                    },
                )
            elif type(component).__name__ == "WireOrthogonal":
                ET.SubElement(
                    components,
                    "WireOrthogonal",
                    {"id": str(component.id)},
                )
        return root


class LegacyWire:
    """Canvas object returned by legacy find_all(), but not a user component."""

    def __init__(self, object_id=99):
        self.id = object_id
        self._id = (str(object_id),)

    def get_location(self):
        return (0, 0)


class WireOrthogonal:
    def __init__(self, object_id, vertices, canvas, *, location=None):
        self.id = object_id
        self._id = (str(object_id),)
        self.vertices = list(vertices)
        if location is not None:
            self.location = location
        self.canvas = canvas
        self.deleted = False
        self.delete_error = None
        self.apply_delete = True

    def delete(self):
        self.canvas.events.append(("wire", self.id))
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted = True
        if self.apply_delete:
            self.canvas.components = [
                item for item in self.canvas.components if item is not self
            ]


class LegacyComponentProject:
    def __init__(self):
        self.main = StatefulCanvas(legacy=True)
        self.layers = {}
        self.layer_calls = []
        self.layer_responses = {
            "create": ET.Element("response", {"success": "true"}),
            "set": ET.Element("response", {"success": "true"}),
        }
        self.apply_layer_changes = True
    def user_canvas(self, name): return self.main
    def create_layer(self, name):
        self.layer_calls.append(("create", name))
        response = self.layer_responses["create"]
        if (
            self.apply_layer_changes
            and response.get("success", "").casefold() == "true"
        ):
            self.layers.setdefault(name, "enabled")
        return response
    def set_layer(self, name, state):
        self.layer_calls.append(("set", name, state))
        response = self.layer_responses["set"]
        if (
            self.apply_layer_changes
            and response.get("success", "").casefold() == "true"
            and name in self.layers
        ):
            self.layers[name] = state
        return response


class ModernComponentProject:
    def __init__(self): self.main = StatefulCanvas()
    def component(self, component_id):
        return next(c for c in self.main.components if c.id == component_id)
    def find_all(self, definition=None, name=None):
        return [
            c for c in self.main.components
            if (definition is None or c.defn_name == definition)
            and (name is None or c.name == name)
        ]


class ComponentApp:
    def __init__(self, project, modern=False):
        self.project_proxy = project
        self.version = "5.0.2" if modern else "4.6.2"
    def project(self, name): return self.project_proxy
    def is_alive(self): return True
    def is_busy(self): return False
    def licensed(self): return True
    def quit(self): pass


class TestBackendComponentContracts(unittest.IsolatedAsyncioTestCase):
    async def make_legacy_backend(self, project=None, definition_paths=None):
        project = project or LegacyComponentProject()
        backend = LegacyBackend(
            ImmediateExecutor(),
            version="4.6.2",
            x64=True,
            automation_module=FakeLegacyAutomation(ComponentApp(project)),
            definition_paths=definition_paths,
        )
        await backend.attach()
        return backend, project, project.main.components[0]

    async def make_backends(self):
        legacy_project = LegacyComponentProject()
        modern_project = ModernComponentProject()
        legacy = LegacyBackend(
            ImmediateExecutor(), version="4.6.2", x64=True,
            automation_module=FakeLegacyAutomation(ComponentApp(legacy_project)),
        )
        modern = ModernBackend(
            ImmediateExecutor(), version="5.0.2", x64=True,
            pscad_module=FakeModernPscad(ComponentApp(modern_project, modern=True)),
            psout_module=False,
        )
        await legacy.attach()
        await modern.attach()
        return [(legacy, legacy_project.main), (modern, modern_project.main)]

    async def test_find_and_parameter_contracts_match(self):
        for backend, _canvas in await self.make_backends():
            with self.subTest(backend=backend.name):
                found = await backend.find_components("case", "Main", "master:source3", None)
                self.assertEqual(found[0].id, 7)
                self.assertEqual(found[0].definition, "master:source3")
                self.assertEqual(found[0].location, {"x": 10, "y": 5})
                self.assertEqual((await backend.get_component_parameters("case", 7))["Gain"], 5)
                await backend.set_component_parameters("case", 7, {"Gain": 8})
                self.assertEqual((await backend.get_component_parameters("case", 7))["Gain"], 8)
                self.assertEqual(await backend.component_parameter_range("case", 7, "Gain"), (0, 10))

    async def test_legacy_find_components_skips_non_component_canvas_objects(self):
        project = LegacyComponentProject()
        project.main.components.append(LegacyWire())
        backend = LegacyBackend(
            ImmediateExecutor(), version="4.6.2", x64=True,
            automation_module=FakeLegacyAutomation(ComponentApp(project)),
        )
        await backend.attach()

        found = await backend.find_components("case", "Main", None, None)

        self.assertEqual([component.id for component in found], [7])

    async def test_legacy_disable_creates_and_verifies_dedicated_layer(self):
        backend, project, component = await self.make_legacy_backend()

        await backend.set_component_enabled("case", 7, False)

        self.assertEqual(
            project.layer_calls,
            [
                ("create", "PSCAD_MCP_DISABLED"),
                ("set", "PSCAD_MCP_DISABLED", "disabled"),
            ],
        )
        self.assertEqual(
            component.layer_calls,
            [("add", "PSCAD_MCP_DISABLED")],
        )
        self.assertEqual(
            component.layers,
            ["USER_LAYER", "PSCAD_MCP_DISABLED"],
        )
        self.assertEqual(component.parameter_writes, [])
        self.assertTrue(component.values["enabled"])

    async def test_legacy_disable_is_idempotent_and_enable_preserves_other_layers(self):
        backend, project, component = await self.make_legacy_backend()

        await backend.set_component_enabled("case", 7, False)
        await backend.set_component_enabled("case", 7, False)
        await backend.set_component_enabled("case", 7, True)

        self.assertEqual(
            [call for call in project.layer_calls if call[0] == "create"],
            [("create", "PSCAD_MCP_DISABLED")],
        )
        self.assertEqual(
            component.layer_calls,
            [
                ("add", "PSCAD_MCP_DISABLED"),
                ("remove", "PSCAD_MCP_DISABLED"),
            ],
        )
        self.assertEqual(component.layers, ["USER_LAYER"])
        self.assertEqual(component.parameter_writes, [])

        await backend.disconnect()
        self.assertEqual(backend._known_managed_layers, set())

    async def test_legacy_layer_mutations_reject_failed_responses(self):
        cases = ("create", "set", "add", "remove")
        for failing_command in cases:
            with self.subTest(failing_command=failing_command):
                backend, project, component = await self.make_legacy_backend()
                if failing_command == "remove":
                    component.layers.append("PSCAD_MCP_DISABLED")
                    project.layers["PSCAD_MCP_DISABLED"] = "disabled"
                    component.layer_responses["remove"] = ET.Element(
                        "response", {"success": "false"}
                    )
                    enabled = True
                else:
                    enabled = False
                    if failing_command in {"create", "set"}:
                        project.layer_responses[failing_command] = ET.Element(
                            "response", {"success": "false"}
                        )
                    else:
                        component.layer_responses["add"] = ET.Element(
                            "response", {"success": "false"}
                        )

                with self.assertRaises(BackendError) as raised:
                    await backend.set_component_enabled(
                        "case", 7, enabled
                    )

                self.assertEqual(raised.exception.code, "PSCAD_COMMAND_FAILED")
                if failing_command == "create":
                    self.assertNotIn(
                        ("case", "PSCAD_MCP_DISABLED"),
                        backend._known_managed_layers,
                    )

    async def test_legacy_layer_success_requires_membership_postcondition(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                backend, project, component = await self.make_legacy_backend()
                if enabled:
                    component.layers.append("PSCAD_MCP_DISABLED")
                    project.layers["PSCAD_MCP_DISABLED"] = "disabled"
                component.apply_layer_changes = False

                with self.assertRaises(BackendError) as raised:
                    await backend.set_component_enabled("case", 7, enabled)

                self.assertEqual(raised.exception.code, "POSTCONDITION_FAILED")
                self.assertEqual(
                    raised.exception.operation, "set_component_enabled"
                )

    async def test_legacy_recognizes_managed_layer_from_project_xml(self):
        project = LegacyComponentProject()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "case.pscx"
            path.write_text(
                '<project><User id="99" '
                'layer="OTHER, PSCAD_MCP_DISABLED EXTRA" /></project>',
                encoding="utf-8",
            )
            backend, project, component = await self.make_legacy_backend(
                project, {"case": path}
            )

            await backend.set_component_enabled("case", 7, False)

        self.assertNotIn(
            ("create", "PSCAD_MCP_DISABLED"), project.layer_calls
        )
        self.assertIn("PSCAD_MCP_DISABLED", component.layers)

    async def test_location_rotation_and_mirror_contracts_match(self):
        for backend, canvas in await self.make_backends():
            with self.subTest(backend=backend.name):
                await backend.set_component_location("case", 7, (20, 15))
                self.assertEqual(await backend.get_component_location("case", 7), (20, 15))
                await backend.rotate_component("case", 7, "right")
                await backend.mirror_component("case", 7, "horizontal")
                self.assertEqual(canvas.components[0].orientation, 90)
                self.assertTrue(canvas.components[0].mirrored)

    async def test_clone_ports_enable_and_delete_contracts_match(self):
        for backend, canvas in await self.make_backends():
            with self.subTest(backend=backend.name):
                clone = await backend.clone_component("case", 7, (30, 10))
                self.assertNotEqual(clone.id, 7)
                self.assertEqual(clone.location, {"x": 30, "y": 10})
                ports = await backend.get_component_ports("case", 7)
                self.assertEqual([port.name for port in ports], ["A", "B"])
                await backend.set_component_enabled("case", 7, False)
                if backend.name == "legacy":
                    self.assertIn("PSCAD_MCP_DISABLED", canvas.components[0].layers)
                    self.assertTrue(
                        (await backend.get_component_parameters("case", 7))["enabled"]
                    )
                else:
                    self.assertFalse(
                        (await backend.get_component_parameters("case", 7))["enabled"]
                    )
                await backend.delete_component("case", clone.id)
                self.assertNotIn(clone.id, [c.id for c in canvas.components])

    async def test_legacy_batch_delete_prevalidates_all_targets(self):
        backend, project, component = await self.make_legacy_backend()
        wire = WireOrthogonal(100, [(9, 5), (30, 5)], project.main)
        project.main.components.append(wire)

        with self.assertRaises(BackendError):
            await backend.delete_components("case", [7, 999])

        self.assertEqual(project.main.events, [])
        self.assertFalse(component.deleted)
        self.assertFalse(wire.deleted)

    async def test_modern_batch_delete_prevalidates_all_targets(self):
        modern_project = ModernComponentProject()
        first = modern_project.main.components[0]
        modern = ModernBackend(
            ImmediateExecutor(),
            version="5.0.2",
            x64=True,
            pscad_module=FakeModernPscad(
                ComponentApp(modern_project, modern=True)
            ),
            psout_module=False,
        )
        await modern.attach()

        with self.assertRaisesRegex(RuntimeError, "StopIteration"):
            await modern.delete_components("case", [7, 999])

        self.assertEqual(modern_project.main.events, [])
        self.assertFalse(first.deleted)

    async def test_legacy_batch_delete_without_connections_succeeds(self):
        backend, project, first = await self.make_legacy_backend()
        second = StatefulComponent(8, legacy=True, canvas=project.main)
        second.port_map = {
            "A": SimpleNamespace(name="A", x=30, y=5, dim=1, type="electrical"),
            "B": SimpleNamespace(name="B", x=32, y=5, dim=1, type="electrical"),
        }
        unrelated = WireOrthogonal(100, [(50, 5), (70, 5)], project.main)
        project.main.components.extend([second, unrelated])

        await backend.delete_components("case", [7, 8])

        self.assertEqual(
            project.main.events,
            [("component", 7), ("component", 8)],
        )
        self.assertTrue(first.deleted)
        self.assertTrue(second.deleted)
        self.assertFalse(unrelated.deleted)

    async def test_legacy_batch_delete_matches_only_wire_endpoints_and_orders_wire_first(self):
        backend, project, component = await self.make_legacy_backend()
        connected = WireOrthogonal(100, [(9, 5), (30, 5)], project.main)
        intermediate = WireOrthogonal(
            101, [(0, 0), (9, 5), (40, 0)], project.main
        )
        unrelated = WireOrthogonal(102, [(0, 0), (40, 0)], project.main)
        project.main.components.extend([connected, intermediate, unrelated])

        await backend.delete_components("case", [7])

        self.assertEqual(
            project.main.events,
            [("wire", 100), ("component", 7)],
        )
        self.assertTrue(component.deleted)
        self.assertTrue(connected.deleted)
        self.assertFalse(intermediate.deleted)
        self.assertFalse(unrelated.deleted)

    async def test_legacy_batch_delete_translates_relative_wire_vertices(self):
        backend, project, component = await self.make_legacy_backend()
        connected = WireOrthogonal(
            100,
            [(0, 0), (21, 0)],
            project.main,
            location=(9, 5),
        )
        project.main.components.append(connected)

        await backend.delete_components("case", [7])

        self.assertEqual(
            project.main.events,
            [("wire", 100), ("component", 7)],
        )
        self.assertTrue(component.deleted)
        self.assertTrue(connected.deleted)

    async def test_legacy_batch_delete_uses_canvas_selection_when_available(self):
        backend, project, component = await self.make_legacy_backend()
        component.apply_delete = False
        unrelated = StatefulComponent(8, legacy=True, canvas=project.main)
        unrelated.location = (90, 90)
        project.main.components.append(unrelated)
        selected = []

        def select_components(x1, y1, x2, y2):
            left, right = sorted((x1, x2))
            bottom, top = sorted((y1, y2))
            selected[:] = [
                item
                for item in project.main.components
                if isinstance(item, StatefulComponent)
                and left <= item.location[0] <= right
                and bottom <= item.location[1] <= top
            ]
            return ET.Element("response", {"success": "true"})

        def delete_selection(command):
            self.assertEqual(command, "IDM_DELETE")
            for item in list(selected):
                item.apply_delete = True
                item.delete()
            return ET.Element("response", {"success": "true"})

        project.main.select_components = select_components
        project.main._generic = delete_selection

        await backend.delete_components("case", [7])

        self.assertTrue(component.deleted)
        self.assertFalse(unrelated.deleted)
        self.assertIn(unrelated, project.main.components)

    def test_legacy_selection_bounds_use_pscad_y_coordinate_order(self):
        self.assertEqual(
            LegacyBackend._selection_bounds(
                [(10, 5), (20, 15)], padding=2
            ),
            (8, 17, 22, 3),
        )

    async def test_legacy_canvas_selection_deletes_connected_batch_once(self):
        backend, project, first = await self.make_legacy_backend()
        first.apply_delete = False
        second = StatefulComponent(8, legacy=True, canvas=project.main)
        second.location = (30, 5)
        second.port_map = {
            "A": SimpleNamespace(name="A", x=30, y=5, dim=1, type="electrical"),
            "B": SimpleNamespace(name="B", x=32, y=5, dim=1, type="electrical"),
        }
        second.apply_delete = False
        unrelated = StatefulComponent(9, legacy=True, canvas=project.main)
        unrelated.location = (90, 90)
        wire = WireOrthogonal(100, [(11, 5), (30, 5)], project.main)
        project.main.components.extend([second, unrelated, wire])
        selected = []
        delete_calls = []

        def select_components(x1, y1, x2, y2):
            left, right = sorted((x1, x2))
            bottom, top = sorted((y1, y2))
            selected[:] = [
                item
                for item in project.main.components
                if isinstance(item, StatefulComponent)
                and left <= item.location[0] <= right
                and bottom <= item.location[1] <= top
            ]
            return ET.Element("response", {"success": "true"})

        def delete_selection(command):
            delete_calls.append(command)
            for item in list(selected):
                item.apply_delete = True
                item.delete()
            if first in selected and second in selected:
                wire.delete()
            return ET.Element("response", {"success": "true"})

        project.main.select_components = select_components
        project.main._generic = delete_selection

        await backend.delete_components("case", [7, 8])

        self.assertEqual(delete_calls, ["IDM_DELETE"])
        self.assertTrue(first.deleted)
        self.assertTrue(second.deleted)
        self.assertTrue(wire.deleted)
        self.assertFalse(unrelated.deleted)

    async def test_legacy_canvas_selection_rejects_conflicting_object_before_delete(self):
        backend, project, target = await self.make_legacy_backend()
        conflict = StatefulComponent(8, legacy=True, canvas=project.main)
        conflict.location = (20, 5)
        project.main.components.append(conflict)
        delete_calls = []
        project.main.select_components = lambda *_args: ET.Element(
            "response", {"success": "true"}
        )
        project.main._generic = lambda command: delete_calls.append(command)

        with self.assertRaises(BackendError) as raised:
            await backend.delete_components("case", [7])

        self.assertEqual(raised.exception.code, "CAPABILITY_UNAVAILABLE")
        self.assertEqual(
            raised.exception.details["conflicting_object_ids"], [8]
        )
        self.assertEqual(delete_calls, [])
        self.assertFalse(target.deleted)
        self.assertFalse(conflict.deleted)

    async def test_legacy_batch_delete_deletes_shared_wire_once(self):
        backend, project, first = await self.make_legacy_backend()
        second = StatefulComponent(8, legacy=True, canvas=project.main)
        second.port_map = {
            "A": SimpleNamespace(name="A", x=30, y=5, dim=1, type="electrical"),
            "B": SimpleNamespace(name="B", x=32, y=5, dim=1, type="electrical"),
        }
        project.main.components.append(second)
        shared = WireOrthogonal(100, [(11, 5), (30, 5)], project.main)
        project.main.components.append(shared)

        await backend.delete_components("case", [7, 8, 7])

        self.assertEqual(
            project.main.events,
            [("wire", 100), ("component", 7), ("component", 8)],
        )
        self.assertTrue(first.deleted)
        self.assertTrue(second.deleted)

    async def test_legacy_batch_delete_reports_partial_completion(self):
        backend, project, component = await self.make_legacy_backend()
        wire = WireOrthogonal(100, [(9, 5), (30, 5)], project.main)
        project.main.components.append(wire)
        component.delete_error = RuntimeError("component delete failed")

        with self.assertRaises(BackendError) as raised:
            await backend.delete_components("case", [7])

        self.assertEqual(raised.exception.code, "PARTIAL_COMPLETION")
        self.assertEqual(
            raised.exception.details,
            {
                "deleted_component_ids": [],
                "deleted_wire_ids": [100],
                "remaining_component_ids": [7],
                "remaining_wire_ids": [],
            },
        )

    async def test_legacy_batch_delete_verifies_planned_wire_ids(self):
        backend, project, _component = await self.make_legacy_backend()
        wire = WireOrthogonal(100, [(9, 5), (30, 5)], project.main)
        wire.apply_delete = False
        project.main.components.append(wire)

        with self.assertRaises(BackendError) as raised:
            await backend.delete_components("case", [7])

        self.assertEqual(raised.exception.code, "PARTIAL_COMPLETION")
        self.assertEqual(raised.exception.details["deleted_wire_ids"], [])
        self.assertEqual(raised.exception.details["deleted_component_ids"], [7])
        self.assertEqual(raised.exception.details["remaining_wire_ids"], [100])
        self.assertEqual(raised.exception.details["remaining_component_ids"], [])

    async def test_legacy_clone_does_not_depend_on_clipboard_selection(self):
        project = LegacyComponentProject()
        project.main.paste = lambda: project.main.components.append(
            LegacyWire(99)
        )
        backend = LegacyBackend(
            ImmediateExecutor(), version="4.6.2", x64=True,
            automation_module=FakeLegacyAutomation(ComponentApp(project)),
        )
        await backend.attach()

        clone = await backend.clone_component("case", 7, (30, 10))

        self.assertEqual(clone.definition, "master:source3")
        self.assertEqual(clone.location, {"x": 30, "y": 10})
        self.assertEqual(
            await backend.get_component_parameters("case", clone.id),
            {"Name": "V1", "Gain": 5, "enabled": True},
        )

    async def test_legacy_uses_library_xml_when_proxy_omits_port_and_range_metadata(self):
        project = LegacyComponentProject()
        component = project.main.components[0]
        component.port_names = []
        component.ports = None
        component.range = None
        library = """<project><Definition name="source3"><form><parameter
            name="Gain" type="Real" min="0" max="10" /></form><svg>
            <port name="A" x="0" y="0" dim="1" type="Real" />
            <port name="B" x="10" y="0" dim="1" type="Real" />
            </svg></Definition></project>"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "master.pslx"
            path.write_text(library, encoding="utf-8")
            backend = LegacyBackend(
                ImmediateExecutor(), version="4.6.2", x64=True,
                automation_module=FakeLegacyAutomation(ComponentApp(project)),
                definition_paths={"master": path},
            )
            await backend.attach()

            ports = await backend.get_component_ports("case", 7)
            legal_range = await backend.component_parameter_range(
                "case", 7, "Gain"
            )

        self.assertEqual([port.name for port in ports], ["A", "B"])
        self.assertEqual(legal_range, (0, 10))

    async def test_legacy_uses_live_canvas_transform_when_port_command_fails(self):
        project = LegacyComponentProject()
        component = project.main.components[0]
        component.location = (378, 342)
        component.port_names = ["A", "B"]
        component.get_port_location = lambda _name: None
        project.main.list_components = lambda: ET.fromstring(
            '<response><components><User id="7" /></components></response>'
        )
        library = """<project><Definition name="source3"><svg>
            <port name="A" x="0" y="0" dim="1" type="Natural" />
            <port name="B" x="36" y="0" dim="1" type="Natural" />
            </svg></Definition></project>"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "master.pslx"
            path.write_text(library, encoding="utf-8")
            case_path = Path(temporary) / "case.pscx"
            case_path.write_text(
                '<project><User id="7" x="378" y="342" orient="3" />'
                '</project>',
                encoding="utf-8",
            )
            backend = LegacyBackend(
                ImmediateExecutor(), version="4.6.2", x64=True,
                automation_module=FakeLegacyAutomation(ComponentApp(project)),
                definition_paths={"master": path, "case": case_path},
            )
            await backend.attach()

            ports = await backend.get_component_ports("case", 7)

        self.assertEqual(
            [(port.name, port.x, port.y) for port in ports],
            [("A", 378, 342), ("B", 378, 306)],
        )

    async def test_legacy_tracks_orientation_for_unsaved_created_component_ports(self):
        project = LegacyComponentProject()
        library = """<project><Definition name="source3"><svg>
            <port name="A" x="0" y="0" dim="1" type="Natural" />
            <port name="B" x="36" y="0" dim="1" type="Natural" />
            </svg></Definition></project>"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "master.pslx"
            path.write_text(library, encoding="utf-8")
            backend = LegacyBackend(
                ImmediateExecutor(), version="4.6.2", x64=True,
                automation_module=FakeLegacyAutomation(ComponentApp(project)),
                definition_paths={"master": path},
            )
            await backend.attach()
            created = await backend.add_component(
                "case", "Main", "master", "source3", (30, 40), 3, {}
            )
            component = project.main.components[-1]
            component.get_port_location = lambda _name: None
            project.main.list_components = lambda: ET.fromstring(
                f'<response><components><User id="{created.id}" />'
                f'</components></response>'
            )

            ports = await backend.get_component_ports(
                "case", created.id
            )

        self.assertEqual(
            [(port.name, port.x, port.y) for port in ports],
            [("A", 30, 40), ("B", 30, 4)],
        )

    async def test_legacy_updates_cached_orientation_after_rotation(self):
        project = LegacyComponentProject()
        library = """<project><Definition name="source3"><svg>
            <port name="A" x="0" y="0" dim="1" type="Natural" />
            <port name="B" x="36" y="0" dim="1" type="Natural" />
            </svg></Definition></project>"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "master.pslx"
            path.write_text(library, encoding="utf-8")
            backend = LegacyBackend(
                ImmediateExecutor(), version="4.6.2", x64=True,
                automation_module=FakeLegacyAutomation(ComponentApp(project)),
                definition_paths={"master": path},
            )
            await backend.attach()
            created = await backend.add_component(
                "case", "Main", "master", "source3", (30, 40), 0, {}
            )
            component = project.main.components[-1]
            component.get_port_location = lambda _name: None
            project.main.list_components = lambda: ET.fromstring(
                f'<response><components><User id="{created.id}" />'
                f'</components></response>'
            )

            await backend.rotate_component("case", created.id, "right")
            ports = await backend.get_component_ports("case", created.id)

        self.assertEqual(
            [(port.name, port.x, port.y) for port in ports],
            [("A", 30, 40), ("B", 30, 76)],
        )

    async def test_legacy_reports_malformed_definition_file_as_backend_error(self):
        project = LegacyComponentProject()
        component = project.main.components[0]
        component.port_names = []
        component.ports = None
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "master.pslx"
            path.write_text("<project>", encoding="utf-8")
            backend = LegacyBackend(
                ImmediateExecutor(), version="4.6.2", x64=True,
                automation_module=FakeLegacyAutomation(ComponentApp(project)),
                definition_paths={"master": path},
            )
            await backend.attach()

            with self.assertRaises(BackendError) as raised:
                await backend.get_component_ports("case", 7)

        self.assertEqual(
            raised.exception.code, "DEFINITION_METADATA_UNAVAILABLE"
        )

    async def test_legacy_discovers_master_library_after_controller_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            installation = Path(temporary) / "PSCAD46"
            executable = installation / "bin" / "win64" / "pscad.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            master_library = installation / "master.pslx"
            master_library.write_text("<project />", encoding="utf-8")

            class Controller:
                def get_param(self, product, display_name):
                    self.request = (product, display_name)
                    return str(executable)

            automation = FakeLegacyAutomation(ComponentApp(LegacyComponentProject()))
            automation.controller = SimpleNamespace(Controller=Controller)
            backend = LegacyBackend(
                ImmediateExecutor(), version="4.6.2", x64=True,
                automation_module=automation,
            )

            discovered = await backend._discover_master_library()

        self.assertEqual(discovered, master_library)

    async def test_legacy_occupied_rectangles_enrich_sparse_canvas_xml_from_project_file(self):
        project = LegacyComponentProject()
        project.main.components[0].location = (999, 999)
        with tempfile.TemporaryDirectory() as temporary:
            case_path = Path(temporary) / "case.pscx"
            case_path.write_text(
                '<project><definitions><Definition name="Main"><schematic>'
                '<User id="7" x="0" y="450" w="40" h="30" />'
                '<User id="999" x="0" y="0" w="500" h="500" />'
                '</schematic></Definition></definitions></project>',
                encoding="utf-8",
            )
            backend, _project, _component = await self.make_legacy_backend(
                project, definition_paths={"case": case_path}
            )

            rectangles = await backend._occupied_rectangles(
                "case", "Main", project.main
            )

        self.assertEqual(rectangles, [Rect(0, 450, 40, 30)])

    async def test_legacy_occupied_rectangles_uses_live_location_when_saved_xml_lacks_id(self):
        project = LegacyComponentProject()
        project.main.components[0].location = (270, 288)
        with tempfile.TemporaryDirectory() as temporary:
            case_path = Path(temporary) / "case.pscx"
            case_path.write_text(
                '<project><definitions><Definition name="Main">'
                '<schematic /></Definition></definitions></project>',
                encoding="utf-8",
            )
            backend, _project, _component = await self.make_legacy_backend(
                project, definition_paths={"case": case_path}
            )

            rectangles = await backend._occupied_rectangles(
                "case", "Main", project.main
            )

        self.assertEqual(rectangles, [Rect(270, 288, 36, 36)])


if __name__ == "__main__":
    unittest.main()
