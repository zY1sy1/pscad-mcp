import unittest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.backend.modern import ModernBackend
from tests.backend_fakes import (
    FakeApplication,
    FakeLegacyAutomation,
    FakeModernPscad,
    ImmediateExecutor,
)


class TestBackendApplicationLifecycle(unittest.IsolatedAsyncioTestCase):
    def backends(self):
        legacy_app = FakeApplication()
        modern_app = FakeApplication()
        return [
            (
                LegacyBackend(
                    ImmediateExecutor(),
                    version="4.6.2",
                    x64=True,
                    automation_module=FakeLegacyAutomation(legacy_app),
                ),
                legacy_app,
                "legacy",
            ),
            (
                ModernBackend(
                    ImmediateExecutor(),
                    version="5.0.2",
                    x64=True,
                    pscad_module=FakeModernPscad(modern_app),
                    psout_module=False,
                ),
                modern_app,
                "modern",
            ),
        ]

    async def test_attach_and_heartbeat_return_normalized_metadata(self):
        for backend, _app, expected_name in self.backends():
            with self.subTest(backend=expected_name):
                attached = await backend.attach()
                heartbeat = await backend.heartbeat()

                self.assertEqual(attached.backend, expected_name)
                self.assertEqual(attached.version, "4.6.2" if expected_name == "legacy" else "5.0.2")
                self.assertTrue(attached.x64)
                self.assertTrue(heartbeat.alive)
                self.assertTrue(heartbeat.licensed)
                self.assertTrue(heartbeat.owns_process)

    async def test_disconnect_does_not_quit_application(self):
        for backend, app, expected_name in self.backends():
            with self.subTest(backend=expected_name):
                await backend.attach()
                await backend.disconnect()

                self.assertFalse(app.quit_called)
                status = await backend.heartbeat()
                self.assertFalse(status.alive)
                self.assertFalse(status.owns_process)

    async def test_quit_closes_connected_application(self):
        for backend, app, expected_name in self.backends():
            with self.subTest(backend=expected_name):
                await backend.attach()
                await backend.quit()

                self.assertTrue(app.quit_called)
                self.assertFalse((await backend.heartbeat()).alive)

    async def test_legacy_quit_rejects_unverified_shutdown(self):
        app = FakeApplication()

        def quit_without_exit():
            app.quit_called = True

        app.quit = quit_without_exit
        backend = LegacyBackend(
            ImmediateExecutor(),
            version="4.6.2",
            x64=True,
            automation_module=FakeLegacyAutomation(app),
        )

        await backend.attach()

        with self.assertRaises(BackendError) as raised:
            await backend.quit()

        self.assertEqual(raised.exception.code, "SHUTDOWN_UNVERIFIED")
        self.assertTrue(backend.owns_process)

    async def test_legacy_launch_uses_exact_display_name_and_safe_flags(self):
        module = FakeLegacyAutomation()
        backend = LegacyBackend(
            ImmediateExecutor(),
            version="4.6.2",
            x64=False,
            automation_module=module,
        )

        await backend.attach()

        self.assertEqual(
            module.launch_kwargs,
            {
                "pscad_version": "PSCAD 4.6.2 (x86)",
                "silence": True,
                "minimize": True,
                "certificate": False,
            },
        )

    async def test_modern_rejects_legacy_version_before_launch(self):
        module = FakeModernPscad(versions=[("4.6.2", True)])
        backend = ModernBackend(
            ImmediateExecutor(),
            version="4.6.2",
            x64=True,
            pscad_module=module,
            psout_module=False,
        )

        with self.assertRaisesRegex(BackendError, "5.x"):
            await backend.attach()

        self.assertIsNone(module.launch_kwargs)

    async def test_missing_legacy_dependency_has_installation_guidance(self):
        backend = LegacyBackend(
            ImmediateExecutor(),
            version="4.6.2",
            x64=True,
            automation_module=False,
            legacy_wheel=r"D:\installers\mhrc_automation.whl",
        )

        with self.assertRaises(BackendError) as raised:
            await backend.attach()

        self.assertEqual(raised.exception.code, "DEPENDENCY_MISSING")
        self.assertIn(r"D:\installers\mhrc_automation.whl", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
