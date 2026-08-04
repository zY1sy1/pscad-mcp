from __future__ import annotations

from collections import namedtuple
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pscad_mcp.core.backend.base import BackendError, ParameterGridRequest, ProjectMessage
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.backend.modern import ModernBackend
from pscad_mcp.core.service import PscadService
from pscad_mcp.tools.data_tools import get_project_output, read_output_file
from tests.backend_fakes import ImmediateExecutor


class LegacyMessageProject:
    def messages(self):
        return [("legacy output", "build", "warning", "case", "", 0, 0)]


class LegacyMessageApp:
    def project(self, name):
        assert name == "case"
        return LegacyMessageProject()


class ModernMessage:
    text = "modern output"
    severity = "error"
    source = {"module": "compiler", "line": 7}


ModernApiMessage = namedtuple(
    "ModernApiMessage",
    "text label status scope name link group classid",
)


class ModernMessageProject:
    def messages(self):
        return [ModernMessage()]


class ModernMessageApp:
    def project(self, name):
        assert name == "case"
        return ModernMessageProject()


class MessageServiceBackend:
    name = "legacy"

    async def project_output(self, project_name):
        return "legacy output"

    async def project_messages(self, project_name):
        return [ProjectMessage("warning", "legacy output", {"source": "build"})]


class OutputServiceBackend(MessageServiceBackend):
    def __init__(self):
        self.calls = []

    async def read_output_file(
        self, file_path, max_samples, channel=None, summary_only=False
    ):
        self.calls.append(
            (file_path, max_samples, channel, summary_only)
        )
        return {"channels": []}


class FakeGridProject:
    pass


class FakeParameterGrid:
    def __init__(self):
        self.calls = []

    def view(self, subject):
        self.calls.append(("view", subject))

    def load(self, filename, folder=None):
        self.calls.append(("load", filename, folder))

    def save(self, filename, folder=None):
        self.calls.append(("save", filename, folder))


class ModernGridApp:
    def __init__(self):
        self.grid = FakeParameterGrid()
        self.parameter_grid = self.grid
        self.project_value = FakeGridProject()

    def project(self, name):
        assert name == "case"
        return self.project_value


class ParameterGridServiceBackend:
    name = "modern"

    def __init__(self):
        self.requests = []

    async def parameter_grid(self, request):
        self.requests.append(request)
        return {
            "action": request.action,
            "project": request.project_name,
            "filename": request.filename,
            "supported": True,
        }


class TestStructuredProjectMessages(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_messages_are_normalized_to_json_safe_records(self):
        backend = LegacyBackend(
            ImmediateExecutor(),
            version="4.6.2",
            x64=True,
            automation_module=False,
        )
        backend._app = LegacyMessageApp()

        result = await backend.project_messages("case")

        self.assertEqual(result[0].severity, "warning")
        self.assertEqual(result[0].text, "legacy output")
        self.assertEqual(result[0].source["kind"], "build")
        json.dumps([record.__dict__ for record in result])

    async def test_modern_messages_are_normalized_to_json_safe_records(self):
        backend = ModernBackend(
            ImmediateExecutor(),
            version="5.0.2",
            x64=True,
            pscad_module=False,
            psout_module=False,
        )
        backend._app = ModernMessageApp()

        result = await backend.project_messages("case")

        self.assertEqual(result, [ProjectMessage("error", "modern output", ModernMessage.source)])
        json.dumps([record.__dict__ for record in result])

    async def test_modern_mhi_message_fields_preserve_severity_and_source(self):
        message = ModernApiMessage(
            "compile failed",
            "build",
            "warning",
            "case",
            "R1",
            42,
            7,
            99,
        )

        result = ModernBackend._project_message(message)

        self.assertEqual(
            result,
            ProjectMessage(
                "warning",
                "compile failed",
                {
                    "label": "build",
                    "scope": "case",
                    "name": "R1",
                    "link": 42,
                    "group": 7,
                    "classid": 99,
                },
            ),
        )
        json.dumps(result.__dict__)

    async def test_modern_scalar_message_source_remains_a_json_record(self):
        class ScalarSourceMessage:
            text = "compiler output"
            severity = "normal"
            source = "compiler"

        result = ModernBackend._project_message(ScalarSourceMessage())

        self.assertEqual(result.source, {"value": "compiler"})
        json.dumps(result.__dict__)

    async def test_service_keeps_text_output_by_default_and_supports_structured_mode(self):
        backend = MessageServiceBackend()
        service = PscadService(lambda: backend, executor=ImmediateExecutor())
        service._backend = backend

        self.assertEqual(await service.get_project_output("case"), "legacy output")
        self.assertEqual(
            await service.get_project_output("case", structured=True),
            [{"severity": "warning", "text": "legacy output", "source": {"source": "build"}}],
        )

    async def test_output_tool_passes_structured_flag_to_service(self):
        with patch("pscad_mcp.tools.data_tools.pscad_manager") as manager:
            manager.service.get_project_output = AsyncMock(return_value=[])

            result = await get_project_output("case", structured=True)

        self.assertEqual(result, [])
        manager.service.get_project_output.assert_awaited_once_with(
            "case", structured=True
        )

    async def test_service_and_tool_forward_focused_psout_options(self):
        backend = OutputServiceBackend()
        service = PscadService(lambda: backend, executor=ImmediateExecutor())
        service._backend = backend

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.psout"
            path.write_text("placeholder", encoding="utf-8")
            result = await service.read_output_file(
                str(path),
                max_samples=25,
                channel="Root/Voltage/PGB:Data",
                summary_only=True,
            )

        self.assertEqual(result, {"channels": []})
        self.assertEqual(
            backend.calls,
            [(str(path), 25, "Root/Voltage/PGB:Data", True)],
        )

        with patch("pscad_mcp.tools.data_tools.pscad_manager") as manager:
            manager.service.read_output_file = AsyncMock(return_value=result)
            tool_result = await read_output_file(
                str(path),
                max_samples=25,
                channel="Root/Voltage/PGB:Data",
                summary_only=True,
            )

        self.assertEqual(tool_result, result)
        manager.service.read_output_file.assert_awaited_once_with(
            str(path),
            max_samples=25,
            channel="Root/Voltage/PGB:Data",
            summary_only=True,
        )

    async def test_parameter_grid_request_rejects_unknown_actions_and_fields(self):
        backend = ParameterGridServiceBackend()
        service = PscadService(lambda: backend, executor=ImmediateExecutor())
        service._backend = backend

        for request in (
            {"action": "unsupported", "project_name": "case"},
            {"action": "view_project", "project_name": "case", "extra": 1},
        ):
            with self.subTest(request=request):
                with self.assertRaises(BackendError) as raised:
                    await service.parameter_grid(request)
                self.assertEqual(raised.exception.code, "INVALID_ARGUMENT")

    async def test_parameter_grid_normalizes_requests_and_resolves_csv_paths(self):
        backend = ParameterGridServiceBackend()
        service = PscadService(lambda: backend, executor=ImmediateExecutor())
        service._backend = backend

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "grid.csv"
            source.write_text("name,value\n", encoding="utf-8")
            loaded = await service.parameter_grid(
                {
                    "action": "load",
                    "filename": str(source),
                }
            )

        self.assertEqual(loaded["action"], "load")
        self.assertEqual(backend.requests[0].action, "load")
        self.assertEqual(backend.requests[0].filename, str(source.resolve()))

    async def test_existing_settings_tools_can_dispatch_parameter_grid_mode(self):
        backend = ParameterGridServiceBackend()
        service = PscadService(lambda: backend, executor=ImmediateExecutor())
        service._backend = backend

        result = await service.get_project_settings(
            "case", mode="parameter_grid"
        )

        self.assertEqual(result["action"], "view_project")
        self.assertEqual(backend.requests[0].project_name, "case")

    async def test_legacy_parameter_grid_is_an_explicit_capability_failure(self):
        backend = LegacyBackend(
            ImmediateExecutor(),
            version="4.6.2",
            x64=True,
            automation_module=False,
        )

        with self.assertRaises(BackendError) as raised:
            await backend.parameter_grid(
                ParameterGridRequest("view_project", "case", None, None)
            )

        self.assertEqual(raised.exception.code, "CAPABILITY_UNAVAILABLE")

    async def test_modern_parameter_grid_uses_the_vendor_grid_proxy(self):
        app = ModernGridApp()
        backend = ModernBackend(
            ImmediateExecutor(),
            version="5.0.2",
            x64=True,
            pscad_module=False,
            psout_module=False,
        )
        backend._app = app

        viewed = await backend.parameter_grid(
            ParameterGridRequest("view_project", "case", None, None)
        )
        saved = await backend.parameter_grid(
            ParameterGridRequest("save", None, "grid.csv", "D:/out")
        )

        self.assertEqual(viewed["action"], "view_project")
        self.assertEqual(saved["action"], "save")
        self.assertEqual(app.grid.calls[0], ("view", app.project_value))
        self.assertEqual(app.grid.calls[1], ("save", "grid.csv", "D:/out"))


if __name__ == "__main__":
    unittest.main()
