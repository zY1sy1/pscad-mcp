import asyncio
import logging
import threading
import unittest

from pscad_mcp.core import executor as executor_module
from pscad_mcp.core.executor import RobustExecutor


class _RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestExecutorRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_success_updates_diagnostic_snapshot(self):
        executor = RobustExecutor()
        try:
            self.assertEqual(await executor.run_safe(lambda: "ok"), "ok")

            self.assertTrue(hasattr(executor, "snapshot"))
            snapshot = executor.snapshot()
            self.assertTrue(snapshot["healthy"])
            self.assertEqual(snapshot["last_operation"], "<lambda>")
            self.assertIsNone(snapshot["last_error"])
            self.assertIsNone(snapshot["last_timeout_seconds"])
        finally:
            executor.shutdown()

    async def test_exception_records_bounded_error_and_traceback(self):
        executor = RobustExecutor()
        handler = _RecordingHandler()
        logger = logging.getLogger("pscad-mcp.executor")
        logger.addHandler(handler)

        def fail():
            raise ValueError("x" * 2_000)

        try:
            with self.assertRaises(ValueError):
                await executor.run_safe(fail)

            self.assertTrue(hasattr(executor, "snapshot"))
            snapshot = executor.snapshot()
            self.assertLessEqual(len(snapshot["last_error"]), 512)
            self.assertEqual(snapshot["last_operation"], "fail")
            self.assertIsNotNone(handler.records[-1].exc_info)
        finally:
            logger.removeHandler(handler)
            executor.shutdown()

    async def test_timeout_marks_executor_unhealthy_until_reset(self):
        executor = RobustExecutor(timeout=0.2)
        started = threading.Event()
        release = threading.Event()

        def blocked_call():
            started.set()
            release.wait(2)
            return "released"

        try:
            with self.assertRaises(RuntimeError) as raised:
                await executor.run_safe(blocked_call, timeout=0.01)
            self.assertTrue(hasattr(executor_module, "ExecutorTimeoutError"))
            self.assertIsInstance(
                raised.exception,
                executor_module.ExecutorTimeoutError,
            )
            self.assertFalse(executor.healthy)
            snapshot = executor.snapshot()
            self.assertFalse(snapshot["healthy"])
            self.assertEqual(snapshot["last_operation"], "blocked_call")
            self.assertEqual(snapshot["last_timeout_seconds"], 0.01)
            self.assertIn("timed out", snapshot["last_error"])

            with self.assertRaises(RuntimeError) as unhealthy:
                await executor.run_safe(lambda: "should not run")
            self.assertTrue(hasattr(executor_module, "ExecutorUnhealthyError"))
            self.assertIsInstance(
                unhealthy.exception,
                executor_module.ExecutorUnhealthyError,
            )

            executor.reset()
            self.assertEqual(await executor.run_safe(lambda: "ok"), "ok")
            snapshot = executor.snapshot()
            self.assertTrue(snapshot["healthy"])
            self.assertIsNone(snapshot["last_error"])
            self.assertIsNone(snapshot["last_timeout_seconds"])
        finally:
            release.set()
            await asyncio.sleep(0.05)
            executor.shutdown()


if __name__ == "__main__":
    unittest.main()
