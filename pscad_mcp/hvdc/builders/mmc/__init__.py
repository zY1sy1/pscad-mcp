"""Immutable schema contracts for the Stage A MMC builder."""

from .assets import load_asset_set, load_packaged_asset_set, materialize_library
from .blank import BlankMmcRequest, plan_blank_mmc
from .blank_service import BlankMmcBuilderService
from .executor import MmcExecutor, execute_build
from .models import (
    MmcAcceptanceCheck,
    MmcArmSpec,
    MmcBlueprint,
    MmcBuildPlan,
    MmcBuildRecord,
    MmcBuildState,
    MmcComponentSpec,
    MmcControlContract,
    MmcNetSpec,
    MmcOutputSpec,
    MmcPlanOperation,
    MmcSequencePhase,
    MmcStationSpec,
    SubmoduleTopology,
)
from .schema import SUPPORTED_BLUEPRINT, parse_blueprint, parse_mmc_blueprint
from .service import MmcBuilderService

__all__ = [
    "SUPPORTED_BLUEPRINT",
    "BlankMmcBuilderService",
    "BlankMmcRequest",
    "MmcAcceptanceCheck",
    "MmcArmSpec",
    "MmcBlueprint",
    "MmcBuildPlan",
    "MmcBuildRecord",
    "MmcBuildState",
    "MmcBuilderService",
    "MmcComponentSpec",
    "MmcControlContract",
    "MmcExecutor",
    "MmcNetSpec",
    "MmcOutputSpec",
    "MmcPlanOperation",
    "MmcSequencePhase",
    "MmcStationSpec",
    "SubmoduleTopology",
    "execute_build",
    "load_asset_set",
    "load_packaged_asset_set",
    "materialize_library",
    "parse_blueprint",
    "parse_mmc_blueprint",
    "plan_blank_mmc",
]
