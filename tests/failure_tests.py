import asyncio
import unittest
import time
from unittest.mock import patch
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.connection_manager import PSCADConnectionManager

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

    def test_manager_does_not_expose_raw_proxy(self):
        """The service boundary must be the only automation entry point."""
        self.assertFalse(hasattr(PSCADConnectionManager, "pscad"))

if __name__ == "__main__":
    unittest.main()
