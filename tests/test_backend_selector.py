import unittest

from pscad_mcp.core.backend.selector import (
    BackendChoice,
    BackendSelectionError,
    normalize_legacy_versions,
    select_backend,
)


class TestBackendSelector(unittest.TestCase):
    def test_462_selects_legacy(self):
        choice = select_backend(
            {"PSCAD_MCP_VERSION": "4.6.2"},
            legacy_versions=lambda: [("4.6.2", True)],
            modern_versions=lambda: [("4.6.2", True)],
        )

        self.assertEqual(choice, BackendChoice("legacy", "4.6.2", True))

    def test_5x_selects_modern(self):
        choice = select_backend(
            {"PSCAD_MCP_VERSION": "5.0.2"},
            legacy_versions=lambda: [("4.6.2", True)],
            modern_versions=lambda: [("4.6.2", True), ("5.0.2", True)],
        )

        self.assertEqual(choice, BackendChoice("modern", "5.0.2", True))

    def test_auto_prefers_highest_supported_version_and_x64(self):
        choice = select_backend(
            {},
            legacy_versions=lambda: [("4.6.2", False), ("4.6.2", True)],
            modern_versions=lambda: [("5.0.1", False), ("5.0.1", True)],
        )

        self.assertEqual(choice, BackendChoice("modern", "5.0.1", True))

    def test_auto_ignores_legacy_version_reported_by_modern_library(self):
        choice = select_backend(
            {},
            legacy_versions=lambda: [("4.6.2", True)],
            modern_versions=lambda: [("4.6.2", True)],
        )

        self.assertEqual(choice, BackendChoice("legacy", "4.6.2", True))

    def test_explicit_backend_never_silently_falls_back(self):
        with self.assertRaisesRegex(BackendSelectionError, "modern"):
            select_backend(
                {"PSCAD_MCP_BACKEND": "modern"},
                legacy_versions=lambda: [("4.6.2", True)],
                modern_versions=lambda: [],
            )

    def test_explicit_legacy_rejects_5x_version(self):
        with self.assertRaisesRegex(BackendSelectionError, "5.0.2"):
            select_backend(
                {
                    "PSCAD_MCP_BACKEND": "legacy",
                    "PSCAD_MCP_VERSION": "5.0.2",
                },
                legacy_versions=lambda: [("4.6.2", True)],
                modern_versions=lambda: [("5.0.2", True)],
            )

    def test_rejects_invalid_backend_value(self):
        with self.assertRaisesRegex(ValueError, "PSCAD_MCP_BACKEND"):
            select_backend(
                {"PSCAD_MCP_BACKEND": "old"},
                legacy_versions=lambda: [],
                modern_versions=lambda: [],
            )

    def test_normalizes_legacy_display_names(self):
        self.assertEqual(
            normalize_legacy_versions(
                ["PSCAD 4.6.2 (x86)", "PSCAD 4.6.2 (x64)"]
            ),
            [("4.6.2", False), ("4.6.2", True)],
        )

    def test_error_lists_detected_versions(self):
        with self.assertRaisesRegex(BackendSelectionError, "4.6.2"):
            select_backend(
                {"PSCAD_MCP_VERSION": "5.1.0"},
                legacy_versions=lambda: [("4.6.2", True)],
                modern_versions=lambda: [],
            )


if __name__ == "__main__":
    unittest.main()
