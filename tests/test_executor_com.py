import threading
import unittest

from pscad_mcp.core.executor import RobustExecutor


class TestExecutorComInitialization(unittest.IsolatedAsyncioTestCase):
    async def test_initializes_com_before_first_worker_call(self):
        events = []

        def initialize_com():
            events.append(("com", threading.get_ident()))

        executor = RobustExecutor(com_initializer=initialize_com)
        try:
            worker_id = await executor.run_safe(threading.get_ident)
            self.assertEqual(events, [("com", worker_id)])
        finally:
            executor.shutdown()

    async def test_reset_initializes_com_on_replacement_worker(self):
        worker_ids = []

        def initialize_com():
            worker_ids.append(threading.get_ident())

        executor = RobustExecutor(com_initializer=initialize_com)
        try:
            await executor.run_safe(lambda: None)
            executor.reset()
            await executor.run_safe(lambda: None)
            self.assertEqual(len(worker_ids), 2)
        finally:
            executor.shutdown()


if __name__ == "__main__":
    unittest.main()
