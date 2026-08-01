import asyncio
import threading
import unittest

from pscad_mcp.core.executor import RobustExecutor


class TestExecutorRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_marks_executor_unhealthy_until_reset(self):
        executor = RobustExecutor(timeout=0.2)
        started = threading.Event()
        release = threading.Event()

        def blocked_call():
            started.set()
            release.wait(2)
            return "released"

        try:
            with self.assertRaises(RuntimeError):
                await executor.run_safe(blocked_call, timeout=0.01)
            self.assertFalse(executor.healthy)

            with self.assertRaises(RuntimeError):
                await executor.run_safe(lambda: "should not run")

            executor.reset()
            self.assertEqual(await executor.run_safe(lambda: "ok"), "ok")
        finally:
            release.set()
            await asyncio.sleep(0.05)
            executor.shutdown()


if __name__ == "__main__":
    unittest.main()
