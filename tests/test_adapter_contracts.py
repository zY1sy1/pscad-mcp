import unittest

from pscad_mcp.core.pscad_adapter import PscadAdapter


class ImmediateExecutor:
    async def run_safe(self, func, *args, **kwargs):
        kwargs.pop("timeout", None)
        return func(*args, **kwargs)


class FakeSimulationSet:
    def __init__(self, name):
        self.name = name
        self.ran = False
        self.tasks = []

    def run(self):
        self.ran = True

    def add_tasks(self, task):
        self.tasks.append(task)


class FakeProject:
    def __init__(self):
        self.definitions_calls = 0

    def definitions(self):
        self.definitions_calls += 1
        return ["source3", "ground"]


class FakePscad:
    def __init__(self):
        self.project_value = FakeProject()
        self.batch = FakeSimulationSet("Batch1")

    def projects(self):
        return [{"name": "case", "type": "Case"}]

    def project(self, name):
        self.project_name = name
        return self.project_value

    def simulation_sets(self):
        return ["Batch1", "Batch2"]

    def simulation_set(self, name):
        if name != self.batch.name:
            raise KeyError(name)
        return self.batch


class FakePscadModule:
    def __init__(self, *, connected=None, installations=None):
        self.connected = connected
        self.installations = (
            [("4.6.2", True)] if installations is None else installations
        )
        self.connect_calls = 0
        self.launch_kwargs = None

    def connect(self):
        self.connect_calls += 1
        if self.connected is None:
            raise ProcessLookupError("no automation instance")
        return self.connected

    def versions(self):
        return self.installations

    def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return FakePscad()


class TestPscadAdapterContracts(unittest.IsolatedAsyncioTestCase):
    async def test_attach_reuses_existing_instance(self):
        existing = FakePscad()
        module = FakePscadModule(connected=existing)
        adapter = PscadAdapter(
            ImmediateExecutor(),
            pscad_module=module,
            environ={},
        )

        result = await adapter.attach_local()

        self.assertIs(result, existing)
        self.assertFalse(adapter.owns_process)
        self.assertIsNone(adapter.selected_installation)
        self.assertIsNone(module.launch_kwargs)

    async def test_attach_launches_explicit_462(self):
        module = FakePscadModule(installations=[("4.6.2", True)])
        adapter = PscadAdapter(
            ImmediateExecutor(),
            pscad_module=module,
            environ={},
        )

        await adapter.attach_local()

        self.assertEqual(
            module.launch_kwargs,
            {
                "version": "4.6.2",
                "x64": True,
                "minimum": "4.6.2",
                "timeout": 30,
            },
        )
        self.assertTrue(adapter.owns_process)
        self.assertEqual(adapter.selected_installation, ("4.6.2", True))

    async def test_attach_launches_explicit_5x(self):
        module = FakePscadModule(
            installations=[("4.6.2", True), ("5.0.1", False)]
        )
        adapter = PscadAdapter(
            ImmediateExecutor(),
            pscad_module=module,
            environ={
                "PSCAD_MCP_VERSION": "5.0.1",
                "PSCAD_MCP_X64": "false",
            },
        )

        await adapter.attach_local()

        self.assertEqual(module.launch_kwargs["version"], "5.0.1")
        self.assertFalse(module.launch_kwargs["x64"])
        self.assertEqual(module.launch_kwargs["minimum"], "5.0.1")

    async def test_explicit_version_skips_unqualified_existing_instance(self):
        existing = FakePscad()
        module = FakePscadModule(
            connected=existing,
            installations=[("4.6.2", True)],
        )
        adapter = PscadAdapter(
            ImmediateExecutor(),
            pscad_module=module,
            environ={"PSCAD_MCP_VERSION": "4.6.2"},
        )

        await adapter.attach_local()

        self.assertEqual(module.connect_calls, 0)
        self.assertTrue(adapter.owns_process)

    async def test_disconnect_clears_connection_metadata(self):
        module = FakePscadModule(installations=[("4.6.2", True)])
        adapter = PscadAdapter(
            ImmediateExecutor(),
            pscad_module=module,
            environ={},
        )
        await adapter.attach_local()

        adapter.disconnect()

        self.assertFalse(adapter.owns_process)
        self.assertIsNone(adapter.selected_installation)

    async def test_definitions_are_returned_as_names(self):
        adapter = PscadAdapter(ImmediateExecutor())
        adapter._pscad = FakePscad()

        result = await adapter.project_definitions("case")

        self.assertEqual(result, ["source3", "ground"])

    async def test_simulation_sets_are_read_from_application(self):
        adapter = PscadAdapter(ImmediateExecutor())
        adapter._pscad = FakePscad()

        result = await adapter.simulation_set_names()

        self.assertEqual(result, ["Batch1", "Batch2"])

    async def test_simulation_set_is_read_from_application(self):
        adapter = PscadAdapter(ImmediateExecutor())
        adapter._pscad = FakePscad()

        result = await adapter.simulation_set("Batch1")

        self.assertEqual(result.name, "Batch1")


if __name__ == "__main__":
    unittest.main()
