import asyncio
import logging
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from pscad_mcp.core import executor as executor_module
from pscad_mcp.core.executor import RobustExecutor


class _RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class _ResetAfterFirstStateCapture:
    def __init__(self, lock, reset):
        self._lock = lock
        self._reset = reset
        self._armed = True

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._lock.release()
        if self._armed:
            self._armed = False
            self._reset()


class TestExecutorRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_reset_and_shutdown_settle_tokens_for_cancelled_queued_calls(self):
        for action in ("reset", "shutdown"):
            with self.subTest(action=action):
                executor = RobustExecutor(timeout=1)
                first_started = threading.Event()
                release_first = threading.Event()
                queued_ran = threading.Event()

                def first_call():
                    first_started.set()
                    release_first.wait(2)

                def queued_call():
                    queued_ran.set()

                first = asyncio.create_task(executor.run_safe(first_call))
                second = None
                try:
                    self.assertTrue(await asyncio.to_thread(first_started.wait, 0.1))
                    second = asyncio.create_task(executor.run_safe(queued_call))
                    await asyncio.sleep(0.01)
                    getattr(executor, action)()
                    release_first.set()
                    await first
                    with self.assertRaises(asyncio.CancelledError):
                        await second
                    await asyncio.sleep(0)

                    self.assertFalse(queued_ran.is_set())
                    self.assertEqual(executor.snapshot()["in_flight_calls"], 0)
                    self.assertEqual(executor.pending_settlements(), ())
                finally:
                    release_first.set()
                    for task in (first, second):
                        if task is not None and not task.done():
                            task.cancel()
                        if task is not None:
                            try:
                                await task
                            except BaseException:
                                pass
                    executor.shutdown()

    async def test_rejected_submission_does_not_leak_settlement_token(self):
        executor = RobustExecutor(timeout=0.1)
        executor.shutdown()

        with self.assertRaises(RuntimeError):
            await executor.run_safe(lambda: None)

        self.assertEqual(executor.snapshot()["in_flight_calls"], 0)
        self.assertEqual(executor.pending_settlements(), ())

    async def test_failed_worker_initializer_settles_unstarted_submission(self):
        def fail_initializer():
            raise RuntimeError("COM initialization failed")

        executor = RobustExecutor(timeout=0.1, com_initializer=fail_initializer)
        try:
            with self.assertRaises(Exception):
                await executor.run_safe(lambda: None)

            await asyncio.sleep(0)
            snapshot = executor.snapshot()
            self.assertEqual(snapshot["in_flight_calls"], 0)
            self.assertEqual(executor.pending_settlements(), ())
            self.assertFalse(snapshot["healthy"])
            self.assertIn("BrokenThreadPool", snapshot["last_error"])
        finally:
            executor.shutdown()

    async def test_cancel_wait_is_bounded_while_worker_settlement_remains_visible(self):
        executor = RobustExecutor(timeout=1)
        executor.cancel_wait_timeout = 0.02
        started = threading.Event()
        release = threading.Event()

        def blocked_call():
            started.set()
            release.wait(2)

        task = asyncio.create_task(executor.run_safe(blocked_call))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 0.1))
            task.cancel()
            await asyncio.sleep(0.05)

            self.assertTrue(task.done())
            self.assertEqual(executor.snapshot()["in_flight_calls"], 1)
            with self.assertRaises(asyncio.CancelledError):
                await task

            release.set()
            deadline = asyncio.get_running_loop().time() + 0.2
            while executor.snapshot()["in_flight_calls"] and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.001)
            self.assertEqual(executor.snapshot()["in_flight_calls"], 0)
        finally:
            release.set()
            if not task.done():
                task.cancel()
            try:
                await task
            except BaseException:
                pass
            executor.shutdown()

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

    async def test_reset_reports_retiring_previous_worker_generation(self):
        executor = RobustExecutor(timeout=0.2)
        started = threading.Event()
        release = threading.Event()

        def blocked_call():
            started.set()
            release.wait(2)
            return "released"

        try:
            with self.assertRaises(executor_module.ExecutorTimeoutError):
                await executor.run_safe(blocked_call, timeout=0.01)

            before_reset = executor.snapshot()
            self.assertEqual(before_reset["reset_generation"], 0)

            executor.reset()
            during_retirement = executor.snapshot()
            self.assertEqual(during_retirement["reset_generation"], 1)
            self.assertTrue(during_retirement["previous_worker_retiring"])

            release.set()
            await asyncio.sleep(0.05)
            self.assertFalse(executor.snapshot()["previous_worker_retiring"])
        finally:
            release.set()
            await asyncio.sleep(0.05)
            executor.shutdown()

    async def test_reset_cannot_move_captured_generation_to_new_worker(self):
        executor = RobustExecutor(timeout=1)
        old_executor = executor.executor
        old_shutdown = old_executor.shutdown
        old_executor.shutdown = lambda **kwargs: None
        executor._new_executor = lambda: ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="pscad-current",
        )
        executor._state_lock = _ResetAfterFirstStateCapture(
            executor._state_lock,
            executor.reset,
        )
        started = threading.Event()
        release = threading.Event()
        worker_name = []

        def blocked_call():
            worker_name.append(threading.current_thread().name)
            started.set()
            release.wait(2)
            return "released"

        try:
            task = asyncio.create_task(executor.run_safe(blocked_call))
            self.assertTrue(await asyncio.to_thread(started.wait, 1))

            snapshot = executor.snapshot()
            self.assertTrue(worker_name[0].startswith("pscad-com"))
            self.assertEqual(snapshot["reset_generation"], 1)
            self.assertTrue(snapshot["previous_worker_retiring"])

            release.set()
            self.assertEqual(await task, "released")
        finally:
            release.set()
            old_shutdown(wait=False, cancel_futures=True)
            executor.shutdown()


if __name__ == "__main__":
    unittest.main()
