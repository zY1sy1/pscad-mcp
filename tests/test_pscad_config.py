import unittest

from pscad_mcp.core.pscad_config import PscadLaunchConfig, select_installation


class TestPscadLaunchConfig(unittest.TestCase):
    def test_prefers_highest_version_then_x64(self):
        config = PscadLaunchConfig.from_environ({})

        result = select_installation(
            [("4.6.2", False), ("5.0.1", False), ("5.0.1", True)],
            config,
        )

        self.assertEqual(result, ("5.0.1", True))

    def test_selects_explicit_462_x64(self):
        config = PscadLaunchConfig.from_environ(
            {"PSCAD_MCP_VERSION": "4.6.2", "PSCAD_MCP_X64": "true"}
        )

        result = select_installation(
            [("4.6.2", False), ("4.6.2", True)],
            config,
        )

        self.assertEqual(result, ("4.6.2", True))

    def test_rejects_invalid_boolean(self):
        with self.assertRaisesRegex(ValueError, "PSCAD_MCP_X64"):
            PscadLaunchConfig.from_environ({"PSCAD_MCP_X64": "maybe"})

    def test_rejects_non_positive_timeout(self):
        with self.assertRaisesRegex(ValueError, "PSCAD_MCP_LAUNCH_TIMEOUT"):
            PscadLaunchConfig.from_environ({"PSCAD_MCP_LAUNCH_TIMEOUT": "0"})

    def test_reports_installed_alternatives(self):
        config = PscadLaunchConfig.from_environ(
            {"PSCAD_MCP_VERSION": "5.0.0"}
        )

        with self.assertRaisesRegex(ValueError, "4.6.2"):
            select_installation([("4.6.2", True)], config)

    def test_reports_no_installations(self):
        with self.assertRaisesRegex(ValueError, "none"):
            select_installation([], PscadLaunchConfig.from_environ({}))


if __name__ == "__main__":
    unittest.main()
