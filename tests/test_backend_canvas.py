import unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace

from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.backend.modern import ModernBackend
from tests.backend_fakes import (
    FakeLegacyAutomation,
    FakeModernPscad,
    ImmediateExecutor,
)


class CanvasObject:
    def __init__(self, object_id, definition, location=(1, 1), parameters=None):
        self.id = object_id
        self._id = (str(object_id),)
        self.defn_name = definition
        self.name = (parameters or {}).get("Name", "")
        self.location = tuple(location)
        self.values = dict(parameters or {})

    def get_definition(self):
        return SimpleNamespace(scoped_name=self.defn_name)

    def get_location(self):
        return self.location

    def set_location(self, x, y):
        self.location = (x, y)

    def get_parameters(self):
        return dict(self.values)

    def set_parameters(self, **parameters):
        self.values.update(parameters)
        self.name = self.values.get("Name", self.name)

    def parameters(self, parameters=None):
        if parameters:
            self.set_parameters(**parameters)
        return dict(self.values)


class CanvasWire:
    def __init__(self, object_id, points, definition="WireOrthogonal"):
        self.id = object_id
        self._id = (str(object_id),)
        self.defn_name = definition
        self.name = ""
        self.location = tuple(points[0])
        self._points = [tuple(point) for point in points]

    @property
    def vertices(self):
        x0, y0 = self.location
        return [(x - x0, y - y0) for x, y in self._points]

    @vertices.setter
    def vertices(self, values):
        x0, y0 = self.location
        self._points = [(x0 + x, y0 + y) for x, y in values]

    def endpoints(self):
        return [SimpleNamespace(x=x, y=y) for x, y in (self._points[0], self._points[-1])]

    def get_location(self):
        return self.location

    def parameters(self, parameters=None):
        if parameters:
            self.values = dict(parameters)
        return getattr(self, "values", {})

    def set_parameters(self, **parameters):
        self.values = dict(parameters)


class LegacyCommand:
    def __init__(self, canvas):
        self.canvas = canvas
        self.component = None

    def tag(self, name):
        self.component = ET.Element(name)
        return self.component

    def execute(self):
        class_id = self.component.get("classid")
        object_id = self.canvas.next_id()
        if class_id == "Bus":
            value = CanvasWire(object_id, [(0, 0), (1, 0)], "Bus")
        else:
            value = CanvasObject(object_id, class_id, (1, 1))
        self.canvas.items.append(value)
        return ET.fromstring(
            f'<response><components><component id="{object_id}" />'
            f'</components></response>'
        )


class CanvasState:
    def __init__(self, modern):
        self.modern = modern
        self.items = []
        self._next_id = 100

    def next_id(self):
        self._next_id += 1
        return self._next_id

    def add_component(self, library, name, x=1, y=1, *args, **parameters):
        if args:
            parameters["orient"] = args[0]
        item = CanvasObject(
            self.next_id(), f"{library}:{name}", (x, y), parameters
        )
        self.items.append(item)
        return item

    def create_component(self, definition, x=1, y=1, orient=0, **parameters):
        library, name = definition.split(":", 1)
        return self.add_component(library, name, x, y, orient, **parameters)

    def add_wire(self, *points):
        item = CanvasWire(self.next_id(), points)
        self.items.append(item)
        return item

    def create_wire(self, *points):
        return self.add_wire(*points)

    def create_bus(self, *points):
        item = CanvasWire(self.next_id(), points, "Bus")
        self.items.append(item)
        return item

    def create_connection(self, p1, p2, **kwargs):
        label = kwargs.get("label")
        if label is None:
            self.create_wire(p1, p2)
            return None
        definition = "nodelabel" if kwargs["electrical"] else "datalabel"
        self.add_component("master", definition, *p1, Name=label)
        self.add_component("master", definition, *p2, Name=label)
        return label

    def create_annotation(self, x, y, line1, line2):
        return self.add_component(
            "master", "annotation", x, y, AL1=line1, AL2=line2
        )

    def create_graph_frame(self, x, y):
        item = CanvasObject(self.next_id(), "GraphFrame", (x, y))
        self.items.append(item)
        return item

    def create_control_frame(self, x, y):
        item = CanvasObject(self.next_id(), "ControlFrame", (x, y))
        self.items.append(item)
        return item, []

    def components(self):
        return list(self.items)

    def find_all(self):
        if self.modern:
            return list(self.items)
        return [item for item in self.items if item.defn_name != "ControlFrame"]

    def list_components(self):
        components = ET.Element("components")
        for item in self.items:
            if item.defn_name == "ControlFrame":
                tag, class_id = "Frame", "ControlFrame"
            elif item.defn_name == "GraphFrame":
                tag, class_id = "Frame", "GraphFrame"
            elif item.defn_name in {"Bus", "WireOrthogonal"}:
                tag, class_id = "Wire", item.defn_name
            else:
                tag, class_id = "User", "UserCmp"
            node = ET.SubElement(components, tag)
            node.set("id", str(item.id))
            node.set("classid", class_id)
        response = ET.Element("response")
        response.append(components)
        return response

    def closest_empty_rect(self, width, height, point):
        return SimpleNamespace(x=point[0] + 10, y=point[1] + 10, width=width, height=height)

    def command(self, name):
        self.command_name = name
        return LegacyCommand(self)

    def bus(self, object_id):
        return self.component(object_id)

    def graph_frame(self, object_id):
        return self.component(object_id)

    def canvas_object(self, _kind, object_id):
        return self.component(object_id)

    def component(self, object_id):
        return next(item for item in self.items if item.id == int(object_id))


class SnappingLegacyCanvas(CanvasState):
    def __init__(self):
        super().__init__(modern=False)

    def add_component(self, library, name, x=1, y=1, *args, **parameters):
        snapped_x = round(x / 18) * 18
        snapped_y = round(y / 18) * 18
        return super().add_component(
            library, name, snapped_x, snapped_y, *args, **parameters
        )


class CanvasProject:
    def __init__(self, canvas):
        self.main = canvas

    def canvas(self, name):
        return self.main

    def user_canvas(self, name):
        return self.main

    def component(self, object_id):
        return self.main.component(object_id)


class CanvasApp:
    def __init__(self, project, modern):
        self.project_proxy = project
        self.version = "5.0.2" if modern else "4.6.2"

    def project(self, name):
        return self.project_proxy

    def is_alive(self): return True
    def is_busy(self): return False
    def licensed(self): return True
    def quit(self): pass


class TestBackendCanvasContracts(unittest.IsolatedAsyncioTestCase):
    async def make_backends(self):
        result = []
        for modern in (False, True):
            canvas = CanvasState(modern)
            project = CanvasProject(canvas)
            app = CanvasApp(project, modern)
            if modern:
                backend = ModernBackend(
                    ImmediateExecutor(), version="5.0.2", x64=True,
                    pscad_module=FakeModernPscad(app), psout_module=False,
                )
            else:
                automation = FakeLegacyAutomation(app)
                automation.component_command_factory = canvas.canvas_object
                backend = LegacyBackend(
                    ImmediateExecutor(), version="4.6.2", x64=True,
                    automation_module=automation,
                )
            await backend.attach()
            result.append((backend, canvas))
        return result

    async def test_component_and_wire_creation_match(self):
        for backend, _canvas in await self.make_backends():
            with self.subTest(backend=backend.name):
                component = await backend.add_component(
                    "case", "Main", "master", "resistor", (10, 20), 3,
                    {"R": "2 [ohm]"},
                )
                wire = await backend.create_wire(
                    "case", "Main", [(10, 20), (30, 20)]
                )
                self.assertEqual(component.definition, "master:resistor")
                self.assertEqual(component.location, {"x": 10, "y": 20})
                self.assertEqual(wire["endpoints"], [[10, 20], [30, 20]])

    async def test_legacy_accepts_and_reports_vendor_grid_snapping(self):
        canvas = SnappingLegacyCanvas()
        project = CanvasProject(canvas)
        app = CanvasApp(project, modern=False)
        backend = LegacyBackend(
            ImmediateExecutor(),
            version="4.6.2",
            x64=True,
            automation_module=FakeLegacyAutomation(app),
        )
        await backend.attach()

        component = await backend.add_component(
            "case", "Main", "master", "datalabel", (690, 540), 0, {}
        )

        self.assertEqual(component.location, {"x": 684, "y": 540})

    async def test_bus_connection_and_annotation_creation_match(self):
        for backend, _canvas in await self.make_backends():
            with self.subTest(backend=backend.name):
                bus = await backend.create_bus(
                    "case", "Main", [(1, 2), (21, 2)], {"Name": "B1"}
                )
                connection = await backend.create_connection(
                    "case", "Main", (2, 3), (12, 3), "L1", False
                )
                annotation = await backend.create_annotation(
                    "case", "Main", (5, 6), "line 1", "line 2"
                )
                self.assertEqual(bus["endpoints"], [[1, 2], [21, 2]])
                self.assertEqual(connection, {"label": "L1"})
                self.assertEqual(annotation.definition, "master:annotation")

    async def test_frames_list_and_empty_space_match(self):
        for backend, _canvas in await self.make_backends():
            with self.subTest(backend=backend.name):
                graph = await backend.create_graph_frame(
                    "case", "Main", (7, 8)
                )
                control = await backend.create_control_frame(
                    "case", "Main", (9, 10)
                )
                listed = await backend.list_canvas_components("case", "Main")
                empty = await backend.find_empty_space(
                    "case", "Main", 4, 5, (1, 1)
                )
                self.assertEqual(graph["id"], 101)
                self.assertEqual(control["control_ids"], [])
                self.assertEqual(len(listed), 2)
                self.assertEqual(empty, {"x": 11, "y": 11, "width": 4, "height": 5})


if __name__ == "__main__":
    unittest.main()
