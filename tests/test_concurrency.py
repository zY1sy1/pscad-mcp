import asyncio
import unittest
import time
from pscad_mcp.core.executor import robust_executor

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

if __name__ == "__main__":
    unittest.main()
