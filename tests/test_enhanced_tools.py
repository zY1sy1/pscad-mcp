import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio
import os

# Import the tools we want to test
from pscad_mcp.tools.project_tools import (
    get_component_parameters, 
    set_component_parameters,
    validate_component_parameters,
    get_project_settings
)
from pscad_mcp.tools.simset_tools import (
    create_simulation_set,
    get_simulation_set_details,
    get_simulation_task_parameters,
    list_simulation_set_tasks,
    list_simulation_sets,
    remove_simulation_set,
    remove_tasks_from_set,
    run_simulation_set,
    set_simulation_task_parameters,
)

class TestEnhancedPSCADTools(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Setup mocks for the PSCAD hierarchy
        self.mock_pscad = MagicMock()
        self.mock_project = MagicMock()
        self.mock_component = MagicMock()
        self.mock_sim_set = MagicMock()
        
        # Configure the hierarchy
        self.mock_pscad.project.return_value = self.mock_project
        self.mock_project.component.return_value = self.mock_component
        self.mock_pscad.simulation_set.return_value = self.mock_sim_set
        
        # Patch the connection manager to return our mock pscad
        self.conn_patcher = patch('pscad_mcp.tools.project_tools.pscad_manager')
        self.mock_manager = self.conn_patcher.start()
        self.mock_manager.pscad = self.mock_pscad
        
        # Also patch for simset tools
        self.simset_conn_patcher = patch('pscad_mcp.tools.simset_tools.pscad_manager')
        self.mock_simset_manager = self.simset_conn_patcher.start()
        self.mock_simset_manager.pscad = self.mock_pscad

        # Mock the robust executor to just run the function
        self.exec_patcher = patch('pscad_mcp.core.executor.robust_executor.run_safe', 
                                  side_effect=lambda f, *args, **kwargs: f(*args, **kwargs))
        self.mock_executor = self.exec_patcher.start()

    def tearDown(self):
        self.conn_patcher.stop()
        self.simset_conn_patcher.stop()
        self.exec_patcher.stop()

    async def test_get_component_parameters(self):
        """Test retrieving parameters from a mock component."""
        self.mock_manager.service.get_component_parameters = AsyncMock(
            return_value={"KV": 138.0, "Name": "Bus1"}
        )
        
        result = await get_component_parameters("TestProj", 101)
        
        self.assertEqual(result["KV"], 138.0)
        self.mock_manager.service.get_component_parameters.assert_awaited_once_with(
            "TestProj", 101
        )

    async def test_validate_parameters_success(self):
        """Test parameter validation against a mock range."""
        self.mock_manager.service.validate_component_parameters = AsyncMock(
            return_value={"KV": {"valid": True, "range": "(0.0, 200.0)"}}
        )
        
        params_to_test = {"KV": 138.0}
        result = await validate_component_parameters("TestProj", 101, params_to_test)
        
        self.assertTrue(result["KV"]["valid"])
        self.assertEqual(result["KV"]["range"], "(0.0, 200.0)")

    async def test_validate_parameters_error(self):
        """Test validation behavior when a parameter doesn't exist."""
        self.mock_manager.service.validate_component_parameters = AsyncMock(
            return_value={
                "InvalidParam": {"valid": False, "error": "No range defined"}
            }
        )
        
        params_to_test = {"InvalidParam": 1.0}
        result = await validate_component_parameters("TestProj", 101, params_to_test)
        
        self.assertFalse(result["InvalidParam"]["valid"])
        self.assertIn("No range defined", result["InvalidParam"]["error"])

    async def test_list_simulation_sets(self):
        """Test listing simulation sets."""
        self.mock_simset_manager.service.list_simulation_sets = AsyncMock(
            return_value=["Batch1"]
        )
        
        result = await list_simulation_sets("TestProj")
        
        self.assertIn("Batch1", result)
        self.assertEqual(len(result), 1)

    async def test_run_simulation_set(self):
        """Test triggering a simulation set run."""
        self.mock_simset_manager.service.run_simulation_set = AsyncMock(
            return_value="Simulation set 'Batch1' started."
        )
        result = await run_simulation_set("TestProj", "Batch1")
        
        self.assertIn("started", result)
        self.mock_simset_manager.service.run_simulation_set.assert_awaited_once_with(
            "TestProj", "Batch1"
        )

    async def test_create_simulation_set_routes_to_service(self):
        self.mock_simset_manager.service.create_simulation_set = AsyncMock(
            return_value={"name": "Batch1"}
        )
        result = await create_simulation_set("Batch1")
        self.assertEqual(result, {"name": "Batch1"})
        self.mock_simset_manager.service.create_simulation_set.assert_awaited_once_with(
            "Batch1"
        )

    async def test_remove_simulation_set_routes_confirmation(self):
        self.mock_simset_manager.service.remove_simulation_set = AsyncMock(
            return_value={"removed": "Batch1"}
        )
        result = await remove_simulation_set("Batch1", confirm=True)
        self.assertEqual(result, {"removed": "Batch1"})
        self.mock_simset_manager.service.remove_simulation_set.assert_awaited_once_with(
            "Batch1", confirm=True
        )

    async def test_simulation_set_task_tools_route_to_service(self):
        cases = [
            (list_simulation_set_tasks, ("Batch1",), {"tasks": ["case"]}),
            (remove_tasks_from_set, ("Batch1", ["case"]), {"removed": ["case"]}),
            (get_simulation_task_parameters, ("Batch1", "case"), {"volley": 1}),
            (set_simulation_task_parameters, ("Batch1", "case", {"volley": 2}), {"volley": 2}),
            (get_simulation_set_details, ("Batch1",), {"name": "Batch1"}),
        ]
        for function, args, expected in cases:
            with self.subTest(function=function.__name__):
                service_method = getattr(self.mock_simset_manager.service, function.__name__)
                service_method = AsyncMock(return_value=expected)
                setattr(self.mock_simset_manager.service, function.__name__, service_method)
                if function is remove_tasks_from_set:
                    result = await function(*args, confirm=True)
                    service_method.assert_awaited_once_with(*args, confirm=True)
                else:
                    result = await function(*args)
                    service_method.assert_awaited_once_with(*args)
                self.assertEqual(result, expected)

    async def test_get_project_settings(self):
        """Test retrieving project settings."""
        self.mock_manager.service.get_project_settings = AsyncMock(
            return_value={"Duration": "0.5", "TimeStep": "50"}
        )
        
        result = await get_project_settings("TestProj")
        
        self.assertEqual(result["Duration"], "0.5")
        self.mock_manager.service.get_project_settings.assert_awaited_once_with(
            "TestProj"
        )

if __name__ == '__main__':
    unittest.main()
