import json
import unittest
from dataclasses import asdict

from pscad_mcp.core.backend.base import (
    BackendError,
    BackendInfo,
    ComponentInfo,
    PortInfo,
    ProjectInfo,
    PscadBackend,
    RunState,
    SimulationSetInfo,
    SimulationTaskInfo,
)
from pscad_mcp.topology.models import TopologySnapshot


class IncompleteBackend:
    async def attach(self):
        return None


class TestBackendRecords(unittest.TestCase):
    def test_normalized_records_are_json_compatible(self):
        records = [
            BackendInfo("legacy", "4.6.2", True, True, False, True, True),
            ProjectInfo("case", "Case", "Example"),
            ComponentInfo(7, "R1", "master:resistor", {"x": 10, "y": 20}),
            PortInfo("A", 10, 20, 1, "electrical"),
            RunState("running", 25.0),
            SimulationSetInfo("Batch1", None, ("CaseA", "CaseB")),
            SimulationTaskInfo("CaseA", "CaseA", "", 1, 1),
            TopologySnapshot("live", "case"),
        ]

        payload = json.loads(json.dumps([asdict(record) for record in records]))

        self.assertEqual(payload[0]["version"], "4.6.2")
        self.assertEqual(payload[2]["location"], {"x": 10, "y": 20})
        self.assertEqual(payload[4]["progress"], 25.0)
        self.assertEqual(payload[5]["tasks"], ["CaseA", "CaseB"])
        self.assertEqual(payload[6]["volley"], 1)
        self.assertEqual(payload[7]["source"], "live")

    def test_backend_error_has_stable_payload(self):
        error = BackendError(
            "NOT_FOUND",
            "Project is missing",
            "legacy",
            "get_project",
            {"name": "case"},
        )

        self.assertEqual(
            error.to_dict(),
            {
                "code": "NOT_FOUND",
                "message": "Project is missing",
                "backend": "legacy",
                "operation": "get_project",
                "details": {"name": "case"},
            },
        )
        json.dumps(error.to_dict())

    def test_aggregate_protocol_rejects_incomplete_backend(self):
        self.assertNotIsInstance(IncompleteBackend(), PscadBackend)


if __name__ == "__main__":
    unittest.main()
