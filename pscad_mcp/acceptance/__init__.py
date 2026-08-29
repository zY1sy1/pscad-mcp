"""Scoped LCC/MMC acceptance evidence and environment preflight."""

from .baseline import (
    CAPABILITY_STATES,
    LICENSED_STATUSES,
    PROGRAM_SCOPES,
    SCOPE_BUILDER_PATHS,
    apply_scope_report,
    canonical_program_baseline,
    program_baseline_sha256,
    validate_program_baseline,
)
from .evidence import build_run_metadata, index_explicit_reports
from .preflight import PreflightRequest, run_static_preflight

__all__ = [
    "CAPABILITY_STATES",
    "LICENSED_STATUSES",
    "PROGRAM_SCOPES",
    "SCOPE_BUILDER_PATHS",
    "PreflightRequest",
    "apply_scope_report",
    "build_run_metadata",
    "canonical_program_baseline",
    "index_explicit_reports",
    "program_baseline_sha256",
    "run_static_preflight",
    "validate_program_baseline",
]
