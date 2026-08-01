import tempfile
import unittest
from pathlib import Path

from pscad_mcp.core.path_policy import PathPolicy


class TestPathPolicy(unittest.TestCase):
    def test_resolves_relative_paths_inside_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = PathPolicy(tmp)
            result = policy.resolve("cases/demo.pscx")
            self.assertEqual(result, (Path(tmp) / "cases" / "demo.pscx").resolve())

    def test_rejects_traversal_outside_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = PathPolicy(tmp)
            with self.assertRaises(ValueError):
                policy.resolve("../outside.pscx")

    def test_rejects_wrong_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = PathPolicy(tmp)
            with self.assertRaises(ValueError):
                policy.resolve("cases/demo.txt", suffixes={".pscx", ".pslx"})


if __name__ == "__main__":
    unittest.main()
