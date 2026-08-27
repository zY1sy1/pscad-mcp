from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.executor import robust_executor


async def normalize_projects(
    projects: tuple[Path, ...], backend: Any
) -> tuple[Path, ...]:
    return await _load_owned_projects(projects, backend, save=True)


async def verify_projects(
    projects: tuple[Path, ...], backend: Any
) -> tuple[Path, ...]:
    return await _load_owned_projects(projects, backend, save=False)


async def _load_owned_projects(
    projects: tuple[Path, ...], backend: Any, *, save: bool
) -> tuple[Path, ...]:
    resolved = tuple(path.resolve() for path in projects)
    missing_files = [str(path) for path in resolved if not path.is_file()]
    if missing_files:
        raise FileNotFoundError(f"missing topology projects: {missing_files}")
    expected_names = {
        path: _project_name(path)
        for path in resolved
    }
    info = None
    try:
        info = await backend.attach()
        if not info.alive or not info.licensed or not info.owns_process:
            raise RuntimeError(
                "normalization requires an owned licensed PSCAD process"
            )
        session_details = getattr(backend, "session_details", {})
        if isinstance(session_details, dict):
            managed_pid = session_details.get("managed_pid")
            if managed_pid is not None:
                print(f"ACCEPTANCE_PID={managed_pid}")
        await backend.load_projects([str(path) for path in resolved])
        loaded = {
            item.name.casefold(): item.name
            for item in await backend.list_projects()
        }
        missing = sorted(
            name
            for name in expected_names.values()
            if name.casefold() not in loaded
        )
        if missing:
            raise RuntimeError(f"PSCAD did not load generated projects: {missing}")
        if save:
            for path in resolved:
                await backend.save_project(
                    loaded[expected_names[path].casefold()]
                )
        return resolved
    finally:
        owned = bool(
            getattr(info, "owns_process", False)
            or getattr(backend, "owns_process", False)
        )
        try:
            if owned:
                await backend.quit()
        finally:
            await backend.disconnect()


def _project_name(path: Path) -> str:
    root = ET.parse(path).getroot()
    name = (root.get("name") or "").strip()
    if not name:
        raise ValueError(f"project identity is missing: {path}")
    return name


def _backend(version: str, x64: bool) -> LegacyBackend:
    return LegacyBackend(
        robust_executor,
        version=version,
        x64=x64,
        legacy_existing_policy="reject",
    )


async def normalize_and_verify(
    projects: tuple[Path, ...], *, version: str, x64: bool
) -> tuple[Path, ...]:
    normalized = await normalize_projects(projects, _backend(version, x64))
    return await verify_projects(normalized, _backend(version, x64))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projects-json", type=Path, required=True)
    parser.add_argument("--version", default="4.6.2")
    parser.add_argument("--x64", action="store_true")
    arguments = parser.parse_args()
    projects = tuple(
        Path(value).resolve()
        for value in json.loads(
            arguments.projects_json.read_text(encoding="utf-8")
        )
    )
    asyncio.run(
        normalize_and_verify(
            projects,
            version=arguments.version,
            x64=arguments.x64,
        )
    )
    print("TOPOLOGY_NORMALIZATION_COMPLETE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
