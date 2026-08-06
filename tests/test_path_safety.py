import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pscad_mcp.core.path_policy import PathPolicy


UNCONFIGURED_ENV = {
    "PSCAD_MCP_WORKSPACE": "",
    "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "false",
}


class TestPathPolicy(unittest.TestCase):
    def test_reads_unscoped_override_from_environment(self):
        for value in ("1", "true", "yes", "on"):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {
                    "PSCAD_MCP_WORKSPACE": "",
                    "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": value,
                },
                clear=False,
            ):
                self.assertTrue(PathPolicy().allow_unscoped_paths)
        for value in ("0", "false", "no", "off"):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {
                    "PSCAD_MCP_WORKSPACE": "",
                    "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": value,
                },
                clear=False,
            ):
                self.assertFalse(PathPolicy().allow_unscoped_paths)

    def test_rejects_invalid_unscoped_override(self):
        with patch.dict(
            os.environ,
            {
                "PSCAD_MCP_WORKSPACE": "",
                "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "maybe",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(
                ValueError, "PSCAD_MCP_ALLOW_UNSCOPED_PATHS"
            ):
                PathPolicy()

    def test_unconfigured_workspace_rejects_relative_path(self):
        with patch.dict(os.environ, UNCONFIGURED_ENV, clear=False):
            policy = PathPolicy(workspace_root=None, allow_unscoped_paths=False)
            with self.assertRaises(ValueError):
                policy.resolve("cases/demo.pscx")

    def test_unconfigured_workspace_rejects_absolute_path(self):
        with patch.dict(os.environ, UNCONFIGURED_ENV, clear=False):
            policy = PathPolicy(workspace_root=None, allow_unscoped_paths=False)
            with self.assertRaises(ValueError):
                policy.resolve(str(Path.cwd() / "cases" / "demo.pscx"))

    def test_explicit_unscoped_mode_preserves_development_resolution(self):
        with patch.dict(
            os.environ,
            {
                "PSCAD_MCP_WORKSPACE": "",
                "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "true",
            },
            clear=False,
        ):
            policy = PathPolicy(workspace_root=None, allow_unscoped_paths=True)
            self.assertEqual(
                policy.resolve("cases/demo.pscx"),
                (Path.cwd() / "cases" / "demo.pscx").resolve(),
            )

    def test_child_resolution_stays_contained_in_all_modes(self):
        with patch.dict(
            os.environ,
            {
                "PSCAD_MCP_WORKSPACE": "",
                "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "true",
            },
            clear=False,
        ), tempfile.TemporaryDirectory() as tmp:
            policy = PathPolicy(workspace_root=None, allow_unscoped_paths=True)
            with self.assertRaises(ValueError):
                policy.resolve_child(tmp, "../escape.pscx")

    def test_resolves_relative_paths_inside_workspace(self):
        with patch.dict(
            os.environ, UNCONFIGURED_ENV, clear=False
        ), tempfile.TemporaryDirectory() as tmp:
            policy = PathPolicy(tmp)
            result = policy.resolve("cases/demo.pscx")
            self.assertEqual(result, (Path(tmp) / "cases" / "demo.pscx").resolve())

    def test_rejects_traversal_outside_workspace(self):
        with patch.dict(
            os.environ, UNCONFIGURED_ENV, clear=False
        ), tempfile.TemporaryDirectory() as tmp:
            policy = PathPolicy(tmp)
            with self.assertRaises(ValueError):
                policy.resolve("../outside.pscx")

    def test_rejects_wrong_suffix(self):
        with patch.dict(
            os.environ, UNCONFIGURED_ENV, clear=False
        ), tempfile.TemporaryDirectory() as tmp:
            policy = PathPolicy(tmp)
            with self.assertRaises(ValueError):
                policy.resolve("cases/demo.txt", suffixes={".pscx", ".pslx"})

    def test_rejects_link_that_resolves_outside_workspace(self):
        with patch.dict(
            os.environ, UNCONFIGURED_ENV, clear=False
        ), tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            (outside / "case.pscx").write_text("case", encoding="utf-8")
            link = workspace / "outside-link"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as symlink_error:
                junction = subprocess.run(
                    [
                        "cmd.exe",
                        "/d",
                        "/c",
                        "mklink",
                        "/J",
                        str(link),
                        str(outside),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if junction.returncode != 0:
                    self.skipTest(
                        "Windows refused temporary symlink and junction creation: "
                        f"{symlink_error}; {junction.stderr.strip()}"
                    )

            policy = PathPolicy(str(workspace))

            with self.assertRaisesRegex(ValueError, "outside the configured"):
                policy.resolve("outside-link/case.pscx", must_exist=True)


if __name__ == "__main__":
    unittest.main()
