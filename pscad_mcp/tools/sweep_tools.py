"""MCP entry points for durable sweeps and constrained scenario selection."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..core.connection_manager import _default_backend_factory, pscad_manager
from ..core.executor import RobustExecutor
from ..core.pscad_config import PscadLaunchConfig
from ..core.service import PscadService
from ..workflows.sweep.service import SweepService
from .registration import register_tool

SweepManifest = Annotated[
    dict[str, Any],
    Field(
        description=(
            "Explicit sweep: source_root inside PSCAD_MCP_WORKSPACE; entry_file and output "
            "paths relative to source_root; project_name; scenarios [{name,updates:"
            "[{component_id,parameters}]}]; outputs [{path,channels}]; optional baseline_scenario, "
            "max_samples, run_timeout_seconds, poll_interval_seconds, output_stability_seconds. "
            "Parameter values are JSON scalars; channels are exact paths."
        )
    ),
]
Objective = Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            "Optional objective {output_path,channel,statistic,direction}; statistic is min, "
            "max, mean, first, last, rms or peak_abs; direction is minimize or maximize."
        )
    ),
]
Constraints = Annotated[
    list[dict[str, Any]] | None,
    Field(
        description=(
            "Up to 32 constraints [{output_path,channel,statistic,operator,value}]; "
            "operator is <=, >= or == and value is a finite number."
        )
    ),
]

_sweep_service: SweepService | None = None
_policy = None


def _new_session() -> PscadService:
    config = PscadLaunchConfig.from_environ()
    executor = RobustExecutor(timeout=config.timeout)

    async def factory():
        backend = await _default_backend_factory(executor)
        if backend.name != "legacy":
            from ..workflows.sweep.store import sweep_error

            raise sweep_error(
                "SWEEP_CAPABILITY_UNAVAILABLE",
                "Sweep execution currently requires the Legacy backend with verified PID ownership.",
            )
        return backend

    return PscadService(
        factory, executor=executor, path_policy=pscad_manager.service.path_policy
    )


def _service() -> SweepService:
    global _sweep_service, _policy
    policy = pscad_manager.service.path_policy
    if _sweep_service is None:
        _policy = policy
        _sweep_service = SweepService(policy, session_factory=_new_session)
    elif _policy is not policy:
        from ..workflows.sweep.store import sweep_error

        raise sweep_error(
            "SWEEP_WORKSPACE_CHANGED",
            "Restart the server before changing an initialized sweep workspace.",
        )
    return _sweep_service


async def shutdown_sweep_service(timeout_s: float = 5) -> None:
    global _sweep_service, _policy
    if _sweep_service is not None:
        await _sweep_service.shutdown(timeout_s)
        _sweep_service = None
        _policy = None


async def plan_parameter_sweep(spec: SweepManifest) -> dict[str, Any]:
    """Validate an explicit sweep and bind its source hashes without launching PSCAD."""
    return await asyncio.to_thread(_service().plan, spec)


async def create_parameter_sweep(
    spec: SweepManifest, expected_plan_hash: str, confirm: bool = False
) -> dict[str, Any]:
    """Create an immutable sweep campaign after confirmation of the exact plan hash."""
    return await asyncio.to_thread(
        _service().create, spec, expected_plan_hash=expected_plan_hash, confirm=confirm
    )


async def run_parameter_sweep(
    campaign_id: str, confirm: bool = False
) -> dict[str, Any]:
    """Start a confirmed background sweep using independent owned Legacy instances."""
    return await _service().start(campaign_id, confirm=confirm)


async def get_parameter_sweep_status(
    campaign_id: str, include_report: bool = False, offset: int = 0, limit: int = 100
) -> dict[str, Any]:
    """Read durable sweep progress and optionally paginated results without contacting PSCAD."""
    return await asyncio.to_thread(
        _service().status,
        campaign_id,
        include_report=include_report,
        offset=offset,
        limit=limit,
    )


async def cancel_parameter_sweep(
    campaign_id: str, confirm: bool = False
) -> dict[str, Any]:
    """Request confirmed cancellation and verified cleanup of only the sweep's owned instance."""
    return await _service().cancel(campaign_id, confirm=confirm)


async def resume_parameter_sweep(
    campaign_id: str, retry_scenarios: list[str] | None = None, confirm: bool = False
) -> dict[str, Any]:
    """Resume a confirmed sweep, preserving completed results and retrying only named failed scenarios."""
    return await _service().resume(
        campaign_id, retry_scenarios=retry_scenarios, confirm=confirm
    )


async def analyze_parameter_sweep(
    campaign_id: str,
    objective: Objective = None,
    constraints: Constraints = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Compare retained channel statistics and rank evaluated scenarios under explicit constraints."""
    return await asyncio.to_thread(
        _service().analyze,
        campaign_id,
        objective=objective,
        constraints=constraints,
        limit=limit,
    )


def register_sweep_tools(mcp: FastMCP) -> None:
    for function in (
        plan_parameter_sweep,
        create_parameter_sweep,
        run_parameter_sweep,
        get_parameter_sweep_status,
        cancel_parameter_sweep,
        resume_parameter_sweep,
        analyze_parameter_sweep,
    ):
        register_tool(mcp, function)
