import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pscad_mcp.core.path_policy import PathPolicy


class TestPathPolicy(unittest.TestCase):
    def test_reads_unscoped_override_from_environment(self):
        with patch.dict(os.environ, {"PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "true"}):
            self.assertTrue(PathPolicy().allow_unscoped_paths)
        with patch.dict(os.environ, {"PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "false"}):
            self.assertFalse(PathPolicy().allow_unscoped_paths)

    def test_rejects_invalid_unscoped_override(self):
        with patch.dict(os.environ, {"PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "maybe"}):
            with self.assertRaisesRegex(
                ValueError, "PSCAD_MCP_ALLOW_UNSCOPED_PATHS"
            ):
                PathPolicy()

    def test_unconfigured_workspace_rejects_relative_path(self):
        policy = PathPolicy(workspace_root=None, allow_unscoped_paths=False)
        with self.assertRaises(ValueError):
            policy.resolve("cases/demo.pscx")

    def test_unconfigured_workspace_rejects_absolute_path(self):
        policy = PathPolicy(workspace_root=None, allow_unscoped_paths=False)
        with self.assertRaises(ValueError):
            policy.resolve(str(Path.cwd() / "cases" / "demo.pscx"))

    def test_explicit_unscoped_mode_preserves_development_resolution(self):
        policy = PathPolicy(workspace_root=None, allow_unscoped_paths=True)
        self.assertEqual(
            policy.resolve("cases/demo.pscx"),
            (Path.cwd() / "cases" / "demo.pscx").resolve(),
        )

    def test_child_resolution_stays_contained_in_all_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = PathPolicy(workspace_root=None, allow_unscoped_paths=True)
            with self.assertRaises(ValueError):
                policy.resolve_child(tmp, "../escape.pscx")

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
