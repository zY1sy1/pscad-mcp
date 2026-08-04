import asyncio
import unittest
import time
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.backend.base import BackendInfo
from pscad_mcp.core.service import PscadService
from tests.backend_fakes import ImmediateExecutor


class WorkflowBackend:
    name = "legacy"

    def __init__(self):
        self.run_entered = asyncio.Event()
        self.release_run = asyncio.Event()
        self.run_calls = []
        self.active_runs = 0
        self.max_active_runs = 0

    async def heartbeat(self):
        return BackendInfo("legacy", "4.6.2", True, True, False, True, True)

    async def run_project(self, project_name):
        self.run_calls.append(project_name)
        self.active_runs += 1
        self.max_active_runs = max(self.max_active_runs, self.active_runs)
        self.run_entered.set()
        await self.release_run.wait()
        self.active_runs -= 1

class TestConcurrency(unittest.IsolatedAsyncioTestCase):
    """
    Test the executor's ability to handle multiple concurrent AI requests
    by queueing them correctly.
    """

    async def test_sequential_execution(self):
        """
        Verify that multiple concurrent calls are executed one after 
        another, which is critical for the single-threaded COM interface.
        """
        execution_times = []

        def slow_call(name: str):
            time.sleep(0.2)
            execution_times.append((name, time.time()))
            return name

        # Fire 3 requests at once
        tasks = [
            robust_executor.run_safe(slow_call, "task1"),
            robust_executor.run_safe(slow_call, "task2"),
            robust_executor.run_safe(slow_call, "task3")
        ]
        
        results = await asyncio.gather(*tasks)
        
        self.assertEqual(results, ["task1", "task2", "task3"])
        
        # Verify that each task started after the previous one finished
        # (Difference between timestamps should be at least 0.2s)
        for i in range(1, len(execution_times)):
            diff = execution_times[i][1] - execution_times[i-1][1]
            self.assertGreaterEqual(diff, 0.19)

    async def test_service_serializes_state_changing_workflows_but_not_status(self):
        backend = WorkflowBackend()
        service = PscadService(lambda: backend, executor=ImmediateExecutor())
        service._backend = backend

        first = asyncio.create_task(service.run_project("first"))
        await asyncio.wait_for(backend.run_entered.wait(), timeout=0.2)

        second = asyncio.create_task(service.run_project("second"))
        status = await asyncio.wait_for(service.status(), timeout=0.2)
        await asyncio.sleep(0)

        self.assertTrue(status["connected"])
        self.assertEqual(backend.run_calls, ["first"])
        self.assertEqual(backend.max_active_runs, 1)
        self.assertFalse(second.done())

        backend.release_run.set()
        await asyncio.gather(first, second)

        self.assertEqual(backend.run_calls, ["first", "second"])
        self.assertEqual(backend.max_active_runs, 1)

if __name__ == "__main__":
    unittest.main()
