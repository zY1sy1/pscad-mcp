"""Contracts for the fixed CIGRE LCC builder."""

from .blank import BlankLccRequest, plan_blank_lcc
from .blank_service import BlankLccBuilderService
from .dynamic_acceptance import (
    DynamicLccAcceptanceRequest,
    evaluate_fixed_lcc_dynamic_samples,
    validate_dynamic_lcc_acceptance_report,
)
from .dynamic_evidence import (
    Trace,
    derive_fixed_lcc_dynamic_evidence,
    normalize_exact_channels,
)
from .fault_event import (
    FixedLccFaultEvent,
    inspect_fixed_lcc_fault_capability,
    validate_fixed_lcc_fault_event,
)
from .models import (
    LccAcceptanceCheck,
    LccBlueprint,
    LccBuildPlan,
    LccBuildRecord,
    LccBuildState,
    LccComponentSpec,
    LccEndpoint,
    LccNetSpec,
    LccOutputSpec,
    LccPlanOperation,
    LccRoute,
)
from .schema import parse_blueprint

SUPPORTED_BLUEPRINT = "cigre_lcc_monopole_v1"

__all__ = [
    "SUPPORTED_BLUEPRINT",
    "BlankLccBuilderService",
    "BlankLccRequest",
    "DynamicLccAcceptanceRequest",
    "FixedLccFaultEvent",
    "LccAcceptanceCheck",
    "LccBlueprint",
    "LccBuildPlan",
    "LccBuildRecord",
    "LccBuildState",
    "LccComponentSpec",
    "LccEndpoint",
    "LccNetSpec",
    "LccOutputSpec",
    "LccPlanOperation",
    "LccRoute",
    "Trace",
    "derive_fixed_lcc_dynamic_evidence",
    "evaluate_fixed_lcc_dynamic_samples",
    "inspect_fixed_lcc_fault_capability",
    "normalize_exact_channels",
    "parse_blueprint",
    "plan_blank_lcc",
    "validate_dynamic_lcc_acceptance_report",
    "validate_fixed_lcc_fault_event",
]
