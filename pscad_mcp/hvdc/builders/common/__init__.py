"""Implementation-neutral primitives shared by deterministic HVDC builders."""

from .journal import AtomicJournal, WorkspaceBuildLease
from .records import JsonRecord, freeze
from .routing import absolute_port, route_intersects_rectangles, transform_offset, validate_orthogonal_route
from .serialization import canonical_json, content_hash, json_safe

__all__ = [
    "AtomicJournal",
    "JsonRecord",
    "WorkspaceBuildLease",
    "absolute_port",
    "canonical_json",
    "content_hash",
    "freeze",
    "json_safe",
    "route_intersects_rectangles",
    "transform_offset",
    "validate_orthogonal_route",
]
