import unittest
from types import SimpleNamespace

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.backend.modern import ModernBackend
from tests.backend_fakes import FakeModernPscad, ImmediateExecutor
from tests.test_backend_canvas import CanvasApp, CanvasProject, CanvasState


class TestBackendTopology(unittest.IsolatedAsyncioTestCase):
    async def test_modern_snapshot_normalizes_live_objects(self):
        canvas = CanvasState(modern=True)
        component = canvas.add_component(
            "master", "resistor", 10, 20, 0, Name="R1"
        )
        component.ports = lambda: {
            "A": SimpleNamespace(x=10, y=20, dim=1, type="electrical"),
            "B": SimpleNamespace(x=28, y=20, dim=1, type="electrical"),
        }
        canvas.create_wire((10, 20), (30, 20), (30, 40))
        canvas.create_bus((40, 20), (80, 20))
        canvas.add_component("master", "datalabel", 90, 20, 0, Name="ENABLE")
        backend = ModernBackend(
            ImmediateExecutor(),
            version="5.0.2",
            x64=True,
            pscad_module=FakeModernPscad(
                CanvasApp(CanvasProject(canvas), modern=True)
            ),
            psout_module=False,
        )
        await backend.attach()
        snapshot = await backend.inspect_canvas_topology("case", "Main")
        assert snapshot.source == "live"
        assert snapshot.pscad_version == "5.0.2"
        wire = next(item for item in snapshot.conductors if item.kind == "wire")
        bus = next(item for item in snapshot.conductors if item.kind == "bus")
        assert wire.vertices == ((10, 20), (30, 20), (30, 40))
        assert bus.vertices == ((40, 20), (80, 20))
        assert snapshot.components[0].ports[1].absolute == (28, 20)
        assert snapshot.labels[0].name == "ENABLE"
        assert snapshot.source_fingerprint
        assert len(snapshot.source_fingerprint) == 64

    async def test_modern_snapshot_rejects_inventory_drift(self):
        backend, _canvas = make_drifting_modern_backend()
        await backend.attach()
        with self.assertRaises(BackendError) as raised:
            await backend.inspect_canvas_topology("case", "Main")
        self.assertEqual(raised.exception.code, "TOPOLOGY_SNAPSHOT_UNSTABLE")

    async def test_modern_snapshot_traverses_explicit_local_definition(self):
        main = CanvasState(modern=True)
        instance = main.add_component(
            "case", "SubSystem", 72, 0, 0, Name="S1"
        )
        instance.id = 101
        instance._id = ("101",)
        instance.ports = lambda: {
            "IN": SimpleNamespace(
                name="IN", x=54, y=0, dim=1, type="electrical"
            ),
            "OUT": SimpleNamespace(
                name="OUT", x=90, y=0, dim=1, type="electrical"
            ),
        }
        child = CanvasState(modern=True)
        child.create_wire((0, 0), (36, 0))
        definition = SimpleNamespace(
            name="SubSystem",
            scoped_name="case:SubSystem",
            ports=lambda: {
                "IN": SimpleNamespace(
                    name="IN", x=0, y=0, dim=1, type="electrical"
                ),
                "OUT": SimpleNamespace(
                    name="OUT", x=36, y=0, dim=1, type="electrical"
                ),
            },
        )
        project = HierarchyProject(main, child, definition)
        backend = ModernBackend(
            ImmediateExecutor(),
            version="5.0.2",
            x64=True,
            pscad_module=FakeModernPscad(CanvasApp(project, modern=True)),
            psout_module=False,
        )
        await backend.attach()

        snapshot = await backend.inspect_canvas_topology("case", "Main")

        self.assertEqual(
            [canvas.key for canvas in snapshot.canvases],
            ["Main", "Main/101:SubSystem"],
        )
        self.assertEqual(
            snapshot.canvases[1].page_ports,
            (
                "Main/101:SubSystem:IN",
                "Main/101:SubSystem:OUT",
            ),
        )
        self.assertEqual(
            [link.key for link in snapshot.boundary_links],
            [
                "Main:101:IN->Main/101:SubSystem:IN",
                "Main:101:OUT->Main/101:SubSystem:OUT",
            ],
        )
        self.assertEqual(
            snapshot.conductors[0].canvas_key,
            "Main/101:SubSystem",
        )
        self.assertIn(("hierarchy", True), snapshot.capabilities)

    async def test_modern_snapshot_excludes_unavailable_hierarchy_boundary(self):
        main = CanvasState(modern=True)
        instance = main.add_component(
            "case", "SubSystem", 72, 0, 0, Name="S1"
        )
        instance.id = 101
        instance._id = ("101",)
        instance.ports = lambda: {
            "IN": SimpleNamespace(
                name="IN", x=54, y=0, dim=1, type="electrical"
            )
        }
        definition = SimpleNamespace(
            name="SubSystem",
            scoped_name="case:SubSystem",
            ports=lambda: {
                "IN": SimpleNamespace(
                    name="IN", x=0, y=0, dim=1, type="electrical"
                )
            },
        )
        project = HierarchyProject(main, None, definition)
        project.canvases.pop("SubSystem")
        backend = ModernBackend(
            ImmediateExecutor(),
            version="5.0.2",
            x64=True,
            pscad_module=FakeModernPscad(CanvasApp(project, modern=True)),
            psout_module=False,
        )
        await backend.attach()

        snapshot = await backend.inspect_canvas_topology("case", "Main")

        self.assertEqual([canvas.key for canvas in snapshot.canvases], ["Main"])
        self.assertEqual(snapshot.boundary_links, ())
        self.assertIn(
            "live_hierarchy_unavailable:Main/101:SubSystem",
            snapshot.unresolved,
        )
        self.assertIn(("hierarchy", False), snapshot.capabilities)


def make_drifting_modern_backend():
    class DriftingCanvas(CanvasState):
        def __init__(self):
            super().__init__(modern=True)
            self.inventory_reads = 0

        def components(self):
            values = super().components()
            self.inventory_reads += 1
            if self.inventory_reads >= 2 and values:
                values[0].location = (
                    values[0].location[0] + 1,
                    values[0].location[1],
                )
            return values

    canvas = DriftingCanvas()
    canvas.add_component("master", "resistor", 10, 20, 0, Name="R1")
    backend = ModernBackend(
        ImmediateExecutor(),
        version="5.0.2",
        x64=True,
        pscad_module=FakeModernPscad(
            CanvasApp(CanvasProject(canvas), modern=True)
        ),
        psout_module=False,
    )
    return backend, canvas


class HierarchyProject:
    def __init__(self, main, child, definition):
        self.canvases = {"Main": main, "SubSystem": child}
        self.definition = definition

    def canvas(self, name):
        return self.canvases[name]

    def user_canvas(self, name):
        return self.canvases[name]

    def definitions(self):
        return [self.definition]
