"""Protocols and implementations for parameterized MMC build engines."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..parametric_models import MmcEnginePlan


class MmcEngine(Protocol):
    name: str

    async def execute_candidate(
        self, plan: MmcEnginePlan, service: object
    ) -> dict[str, object]:
        raise NotImplementedError

    def validate(
        self,
        plan: MmcEnginePlan,
        project_path: Path,
        outputs: dict[str, object],
    ) -> dict[str, object]:
        raise NotImplementedError


__all__ = ["MmcEngine"]
