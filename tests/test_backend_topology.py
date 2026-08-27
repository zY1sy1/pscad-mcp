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
