"""Compatibility adapters from canonical topology records."""

from .hvdc import topology_to_hvdc_evidence
from .lcc import lcc_port_contracts, topology_to_lcc_graph

__all__ = [
    "lcc_port_contracts",
    "topology_to_hvdc_evidence",
    "topology_to_lcc_graph",
]
