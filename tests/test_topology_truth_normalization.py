from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from scripts.normalize_topology_truth import normalize_projects


def _owned_backend(projects: tuple[Path, ...]) -> AsyncMock:
    backend = AsyncMock()
    backend.owns_process = True
    backend.attach.return_value = type(
        "Info", (), {"alive": True, "licensed": True, "owns_process": True}
    )()
    backend.list_projects.return_value = [
        type("Project", (), {"name": path.stem})() for path in projects
    ]
    return backend


@pytest.mark.asyncio
async def test_normalizer_uses_only_load_save_list_and_disconnect(tmp_path):
    projects = tuple(tmp_path / f"case-{index}.pscx" for index in range(2))
    for path in projects:
        path.write_text(f'<project name="{path.stem}"/>', encoding="utf-8")
    backend = _owned_backend(projects)

    result = await normalize_projects(projects, backend)

    assert result == projects
    backend.attach.assert_awaited_once()
    backend.load_projects.assert_awaited_once_with([str(path) for path in projects])
    assert backend.save_project.await_count == len(projects)
    backend.quit.assert_awaited_once()
    backend.disconnect.assert_awaited_once()
    assert {call[0] for call in backend.method_calls} <= {
        "attach",
        "load_projects",
        "list_projects",
        "save_project",
        "quit",
        "disconnect",
    }


@pytest.mark.asyncio
async def test_normalizer_disconnects_when_save_fails(tmp_path):
    project = tmp_path / "case.pscx"
    project.write_text('<project name="case"/>', encoding="utf-8")
    backend = _owned_backend((project,))
    backend.save_project.side_effect = RuntimeError("save failed")

    with pytest.raises(RuntimeError, match="save failed"):
        await normalize_projects((project,), backend)

    backend.quit.assert_awaited_once()
    backend.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_normalizer_cleans_up_an_owned_unlicensed_session(tmp_path):
    project = tmp_path / "case.pscx"
    project.write_text('<project name="case"/>', encoding="utf-8")
    backend = _owned_backend((project,))
    backend.attach.return_value = type(
        "Info", (), {"alive": True, "licensed": False, "owns_process": True}
    )()

    with pytest.raises(RuntimeError, match="owned licensed PSCAD"):
        await normalize_projects((project,), backend)

    backend.quit.assert_awaited_once()
    backend.disconnect.assert_awaited_once()
