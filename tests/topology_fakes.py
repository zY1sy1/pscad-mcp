from dataclasses import replace

from pscad_mcp.core.backend.base import BackendInfo
from pscad_mcp.topology.connectivity import build_connectivity
from pscad_mcp.topology.models import (
    CandidateEdge,
    EvidenceRef,
    ProjectTopology,
    TopologyComponent,
    TopologyConflict,
    TopologyConductor,
    TopologyLabel,
    TopologyPort,
)
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


def _component(
    object_id,
    point,
    *,
    kind="electrical",
    dimension=1,
    required=None,
):
    key = f"Main:{object_id}"
    return TopologyComponent(
        key=key,
        canvas_key="Main",
        object_id=str(object_id),
        definition="test:component",
        location=point,
        ports=(
            TopologyPort(
                key=f"{key}:P",
                component_key=key,
                name="P",
                absolute=point,
                kind=kind,
                dimension=dimension,
                required=required,
            ),
        ),
    )


def topology_with_unconnected_ports(*, required, optional):
    components = []
    if required:
        components.append(_component(1, (0, 0), required=True))
    if optional:
        components.append(_component(2, (36, 0), required=None))
    return ProjectTopology("case", "4.6.2", components=tuple(components))


def topology_with_seeded_defects():
    components = (
        _component(1, (0, 0), kind="data", dimension=1),
        _component(2, (100, 0), dimension=1),
        _component(3, (120, 0), dimension=3),
    )
    conductors = (
        TopologyConductor(
            "Main:10",
            "Main",
            "10",
            "wire",
            "electrical",
            ((0, 0), (20, 0)),
        ),
        TopologyConductor(
            "Main:11",
            "Main",
            "11",
            "wire",
            "electrical",
            ((100, 0), (120, 0)),
        ),
        TopologyConductor(
            "Main:12",
            "Main",
            "12",
            "wire",
            "electrical",
            ((200, 0), (220, 0)),
        ),
        TopologyConductor(
            "Main:13",
            "Main",
            "13",
            "wire",
            "electrical",
            ((300, 0), (340, 0)),
        ),
        TopologyConductor(
            "Main:14",
            "Main",
            "14",
            "wire",
            "electrical",
            ((320, -20), (320, 20)),
        ),
    )
    labels = (
        TopologyLabel(
            "Main:20",
            "Main",
            "20",
            "DUP",
            "electrical",
            "Main",
            (200, 0),
        ),
        TopologyLabel(
            "Main:21",
            "Main",
            "21",
            "DUP",
            "data",
            "Main",
            (200, 20),
        ),
    )
    topology = build_connectivity(
        ProjectTopology(
            "case",
            "4.6.2",
            components=components,
            conductors=conductors,
            labels=labels,
        )
    ).topology
    conflict = TopologyConflict(
        field="location",
        object_key="Main:1",
        live_value=(0, 0),
        file_value=(18, 0),
        evidence=(
            EvidenceRef("live", "Main:1"),
            EvidenceRef("pscx", "Main:1"),
        ),
    )
    return replace(topology, conflicts=(conflict,))


def topology_with_nearby_dangling_endpoint(*, grid_step):
    topology = ProjectTopology(
        "case",
        "4.6.2",
        components=(_component(1, (18, 0)),),
        conductors=(
            TopologyConductor(
                "Main:10",
                "Main",
                "10",
                "wire",
                "electrical",
                ((0, 0), (0, 18)),
            ),
        ),
        grid_step=grid_step,
    )
    return build_connectivity(topology).topology


def topology_with_incompatible_nearby_ports():
    topology = ProjectTopology(
        "case",
        "4.6.2",
        components=(
            _component(1, (18, 18), kind="data"),
            _component(2, (0, 36), dimension=3),
            _component(3, (0, 0), dimension=1),
        ),
        conductors=(
            TopologyConductor(
                "Main:10",
                "Main",
                "10",
                "wire",
                "electrical",
                ((0, 0), (0, 18)),
            ),
        ),
        grid_step=18,
    )
    return build_connectivity(topology).topology


def topology_with_candidate_only_connection():
    topology = topology_with_nearby_dangling_endpoint(grid_step=18)
    return replace(
        topology,
        candidate_edges=(
            CandidateEdge(
                left="Main:10@(0,0)",
                right="Main:1:P",
                confidence=0.5,
                reasons=("nearby compatible dangling endpoint",),
            ),
        ),
    )
