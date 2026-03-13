import asyncio
import unittest
import time
from unittest.mock import MagicMock, patch
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.connection_manager import pscad_manager

class TestModularRobustness(unittest.IsolatedAsyncioTestCase):
    """
    Test the modular robustness components: RobustExecutor and ConnectionManager.
    """

    async def test_executor_timeout(self):
        """Verify the Command/Proxy executor correctly times out."""
        def hang():
            time.sleep(1)
            return "ok"

        # Force a very short timeout
        with patch.object(robust_executor, 'timeout', 0.1):
            with self.assertRaises(RuntimeError) as cm:
                await robust_executor.run_safe(hang)
            self.assertIn("timed out", str(cm.exception))

    @patch('psutil.process_iter')
    def test_manager_process_check(self, mock_iter):
        """Test the singleton manager's OS process check."""
        mock_proc = MagicMock()
        mock_proc.info = {'name': 'PSCAD.exe'}
        mock_iter.return_value = [mock_proc]
        
        self.assertTrue(pscad_manager.is_process_running())

    @patch('pscad_mcp.core.connection_manager.PSCADConnectionManager.is_process_running')
    def test_manager_safe_get_failure(self, mock_running):
        """Verify the manager correctly handles a missing process."""
        mock_running.return_value = False
        pscad_manager._pscad = MagicMock()
        
        with self.assertRaises(RuntimeError) as cm:
            _ = pscad_manager.pscad
        self.assertIn("not running on the system", str(cm.exception))

if __name__ == "__main__":
    unittest.main()
