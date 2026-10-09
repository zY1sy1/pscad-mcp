import xml.etree.ElementTree as ET

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.backend.legacy import LegacyBackend
from tests.backend_fakes import FakeLegacyAutomation, ImmediateExecutor


class SavedProject:
    def __init__(self, dirty=False):
        self.dirty = dirty

    def is_dirty(self):
        return self.dirty

    def get_run_status(self, callback):
        callback("idle", 0.0)


class WorkspaceApplication:
    def __init__(self):
        self.projects = {"Source": SavedProject(), "BuiltCase": SavedProject()}
        self.busy = False
        self.reset_count = 0
        self.loads = []

    def project(self, name):
        return self.projects[name]

    def list_projects(self):
        return [{"name": "master", "type": "Library"},
                *({"name": name, "type": "Case"} for name in self.projects)]

    def is_busy(self):
        return self.busy

    def new_workspace(self):
        self.reset_count += 1
        self.projects.clear()

    def load(self, *files):
        self.loads.append(files)
        for path in files:
            self.projects[ET.parse(path).getroot().get("name")] = SavedProject()


def arrange(tmp_path):
    app = WorkspaceApplication()
    backend = LegacyBackend(ImmediateExecutor(), version="4.6.2", x64=True,
                            automation_module=FakeLegacyAutomation(app))
    backend._app = app
    backend.owns_process = True
    backend._managed_pid = 123
    for name in app.projects:
        path = tmp_path / f"{name}.pscx"
        path.write_text(f'<project name="{name}"/>', encoding="utf-8")
        backend.definition_paths[name] = path
    return backend, app


@pytest.mark.asyncio
async def test_legacy_unload_resets_owned_saved_workspace_and_restores_other_projects(tmp_path):
    backend, app = arrange(tmp_path)
    before = {path: path.read_bytes() for path in backend.definition_paths.values()}
    await backend.unload_project("BuiltCase")
    assert app.reset_count == 1
    assert set(app.projects) == {"Source"}
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.asyncio
async def test_legacy_workspace_reload_reads_project_run_states_without_an_application_busy_api(tmp_path):
    backend, app = arrange(tmp_path)
    app.is_busy = None
    await backend.unload_project("BuiltCase")
    assert app.reset_count == 1
    assert set(app.projects) == {"Source"}


@pytest.mark.asyncio
@pytest.mark.parametrize("blocker", ["foreign", "unknown_pid", "busy", "dirty", "unknown_path"])
async def test_legacy_workspace_reload_never_discards_unverified_or_unsaved_work(tmp_path, blocker):
    backend, app = arrange(tmp_path)
    if blocker == "foreign":
        backend.owns_process = False
    elif blocker == "unknown_pid":
        backend._managed_pid = None
    elif blocker == "busy":
        app.busy = True
    elif blocker == "dirty":
        app.projects["Source"].dirty = True
    else:
        backend.definition_paths.pop("Source")
    with pytest.raises(BackendError):
        await backend.unload_project("BuiltCase")
    assert app.reset_count == 0
    assert set(app.projects) == {"Source", "BuiltCase"}
