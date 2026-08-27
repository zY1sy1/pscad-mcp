from dataclasses import replace

from pscad_mcp.core.backend.base import BackendInfo
from pscad_mcp.topology.providers.pscx import PscxSnapshotProvider


class ReadOnlyRecordingBackend:
    name = "legacy"
    version = "4.6.2"
    x64 = True
    owns_process = False

    def __init__(self, project):
        self.project = project
        self.calls = []

    async def attach(self):
        self.calls.append("attach")
        return BackendInfo(
            self.name,
            self.version,
            self.x64,
            True,
            False,
            True,
            self.owns_process,
        )

    async def disconnect(self):
        self.calls.append("disconnect")

    async def inspect_canvas_topology(self, project_name, canvas_name):
        self.calls.append("inspect_canvas_topology")
        saved = PscxSnapshotProvider().read(self.project, canvas_name)
        return replace(saved, source="live", project_path=str(self.project))
