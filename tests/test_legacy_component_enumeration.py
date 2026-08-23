import xml.etree.ElementTree as ET

from pscad_mcp.core.backend.legacy import LegacyBackend
from tests.backend_fakes import ImmediateExecutor


class _Component:
    id = 7
    name = "V1"
    defn_name = "master:source3"

    def get_definition(self):
        return type("Definition", (), {"scoped_name": self.defn_name})()

    def get_parameters(self):
        return {"Name": self.name}

    def get_location(self):
        return (10, 5)


class _Command:
    def __init__(self, recorder):
        self.recorder = recorder
        self.root = ET.Element("command")

    def scope(self, scope_name):
        self.root.set("scope", scope_name)
        return ET.SubElement(self.root, "scope")

    def execute(self):
        self.recorder.append(self.root)
        return ET.fromstring(
            '<response success="true"><components>'
            '<User id="7" />'
            '</components></response>'
        )


class _Pscad:
    def __init__(self):
        self.commands = []

    def command(self, name):
        command = _Command(self.commands)
        command.root.set("name", name)
        return command


class _Canvas:
    def __init__(self):
        self._pscad = _Pscad()
        self._scope = {"project": "case", "definition": "Main"}
        self._scope_name = "UserCanvas"
        self.component = _Component()

    def find_all(self):
        raise TypeError("cannot serialize None (type NoneType)")

    def user_cmp(self, component_id):
        assert int(component_id) == self.component.id
        return self.component


class _Project:
    def __init__(self, canvas):
        self.canvas = canvas

    def user_canvas(self, name):
        assert name == "Main"
        return self.canvas


class _App:
    def __init__(self, project):
        self.project_proxy = project

    def project(self, name):
        assert name == "case"
        return self.project_proxy


class _Automation:
    def __init__(self, app):
        self.app = app


async def _make_backend(canvas):
    backend = LegacyBackend(
        ImmediateExecutor(),
        version="4.6.2",
        x64=True,
        automation_module=_Automation(_App(_Project(canvas))),
    )
    backend._app = backend.automation.app
    return backend


def test_legacy_component_enumeration_uses_scope_without_canvas_component_id():
    """4.6.2 UserCanvas.find_all can serialize a None id; use raw XML scope."""
    import asyncio

    async def run():
        canvas = _Canvas()
        backend = await _make_backend(canvas)

        found = await backend.find_components("case", "Main", None, None)

        assert [item.id for item in found] == [7]
        command = canvas._pscad.commands[0]
        assert command.find("scope/component") is None

    asyncio.run(run())
