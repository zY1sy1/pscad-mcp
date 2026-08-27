from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.main import create_server
from pscad_mcp.tools import app_tools, canvas_tools, creation_tools, project_tools
from pscad_mcp.utils.doc_manager import DocumentationManager


def test_list_projects_keeps_default_result_and_supports_slices():
    values = [{"name": f"case-{index}"} for index in range(5)]
    with patch.object(project_tools, "pscad_manager") as manager:
        manager.service.list_projects = AsyncMock(return_value=values)

        assert asyncio.run(project_tools.list_projects()) == values
        assert asyncio.run(project_tools.list_projects(offset=1, limit=2)) == values[1:3]

    assert manager.service.list_projects.await_args_list == [(), ()]


def test_find_components_keeps_default_result_and_supports_slices():
    values = [{"id": index} for index in range(5)]
    with patch.object(project_tools, "pscad_manager") as manager:
        manager.service.find_components = AsyncMock(return_value=values)

        assert asyncio.run(project_tools.find_components("case")) == values
        assert asyncio.run(
            project_tools.find_components(
                "case",
                definition="master:source3",
                name="Source",
                offset=2,
                limit=2,
            )
        ) == values[2:4]

    assert manager.service.find_components.await_args_list == [
        (("case",), {"definition": None, "name": None}),
        (
            ("case",),
            {"definition": "master:source3", "name": "Source"},
        ),
    ]


def test_get_project_definitions_keeps_default_result_and_supports_slices():
    values = [f"master:item-{index}" for index in range(5)]
    with patch.object(creation_tools, "pscad_manager") as manager:
        manager.service.get_project_definitions = AsyncMock(return_value=values)

        assert asyncio.run(creation_tools.get_project_definitions("case")) == values
        assert asyncio.run(
            creation_tools.get_project_definitions("case", offset=1, limit=3)
        ) == values[1:4]

    assert manager.service.get_project_definitions.await_args_list == [
        (("case",), {}),
        (("case",), {}),
    ]


def test_list_canvas_components_keeps_default_result_and_supports_slices():
    values = [{"id": index} for index in range(5)]
    with patch.object(canvas_tools, "pscad_manager") as manager:
        manager.service.list_canvas_components = AsyncMock(return_value=values)

        assert asyncio.run(canvas_tools.list_canvas_components("case")) == values
        assert asyncio.run(
            canvas_tools.list_canvas_components(
                "case",
                canvas_name="Controls",
                offset=3,
                limit=2,
            )
        ) == values[3:5]

    assert manager.service.list_canvas_components.await_args_list == [
        (("case",), {"canvas_name": "Main"}),
        (("case",), {"canvas_name": "Controls"}),
    ]


@pytest.mark.asyncio
async def test_documentation_tools_keep_default_results_and_support_slices(
    tmp_path,
    monkeypatch,
):
    manager = DocumentationManager(tmp_path / "docs")
    manager.md_dir.mkdir(parents=True)
    for module_name in ("mhi.pscad.alpha", "mhi.pscad.beta", "mhi.pscad.gamma"):
        (manager.md_dir / f"{module_name.replace('.', '_')}.md").write_text(
            f"# {module_name}\n0123456789",
            encoding="utf-8",
        )
    monkeypatch.setattr(app_tools, "doc_manager", manager)

    modules = await app_tools.list_documentation()
    content = await app_tools.read_documentation("mhi.pscad.alpha")

    assert modules == ["mhi.pscad.alpha", "mhi.pscad.beta", "mhi.pscad.gamma"]
    assert await app_tools.list_documentation(offset=1, limit=1) == modules[1:2]
    assert isinstance(modules, list)
    assert await app_tools.read_documentation(
        "mhi.pscad.alpha", offset=3, max_chars=8
    ) == content[3:11]
    assert isinstance(content, str)


PaginatedCall = Callable[[Any, Any], Awaitable[Any]]


def _pagination_calls() -> tuple[tuple[str, PaginatedCall], ...]:
    return (
        ("list_projects", lambda offset, limit: project_tools.list_projects(offset, limit)),
        (
            "find_components",
            lambda offset, limit: project_tools.find_components(
                "case", offset=offset, limit=limit
            ),
        ),
        (
            "get_project_definitions",
            lambda offset, limit: creation_tools.get_project_definitions(
                "case", offset, limit
            ),
        ),
        (
            "list_canvas_components",
            lambda offset, limit: canvas_tools.list_canvas_components(
                "case", "Main", offset, limit
            ),
        ),
        (
            "list_documentation",
            lambda offset, limit: app_tools.list_documentation(offset, limit),
        ),
    )


@pytest.mark.parametrize(("offset", "limit"), ((-1, None), (True, 1), (1.5, 1), ("1", 1)))
@pytest.mark.parametrize(("operation", "call"), _pagination_calls())
def test_item_tools_reject_invalid_offsets(operation, call, offset, limit):
    with pytest.raises(BackendError) as raised:
        asyncio.run(call(offset, limit))

    assert raised.value.code == "INVALID_ARGUMENT"
    assert raised.value.operation == operation


@pytest.mark.parametrize(
    ("offset", "limit"),
    ((0, 0), (0, 1001), (0, True), (0, 1.5), (0, "1")),
)
@pytest.mark.parametrize(("operation", "call"), _pagination_calls())
def test_item_tools_reject_invalid_limits(operation, call, offset, limit):
    with pytest.raises(BackendError) as raised:
        asyncio.run(call(offset, limit))

    assert raised.value.code == "INVALID_ARGUMENT"
    assert raised.value.operation == operation


@pytest.mark.parametrize("offset", (-1, True, 1.5, "1"))
def test_read_documentation_rejects_invalid_offsets(offset):
    with pytest.raises(BackendError) as raised:
        asyncio.run(app_tools.read_documentation("mhi.pscad", offset=offset))

    assert raised.value.code == "INVALID_ARGUMENT"
    assert raised.value.operation == "read_documentation"


@pytest.mark.parametrize("max_chars", (0, 100001, True, 1.5, "1"))
def test_read_documentation_rejects_invalid_max_chars(max_chars):
    with pytest.raises(BackendError) as raised:
        asyncio.run(app_tools.read_documentation("mhi.pscad", max_chars=max_chars))

    assert raised.value.code == "INVALID_ARGUMENT"
    assert raised.value.operation == "read_documentation"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "base_arguments"),
    (
        ("list_projects", {}),
        ("find_components", {"project_name": "case"}),
        ("get_project_definitions", {"project_name": "case"}),
        ("list_canvas_components", {"project_name": "case"}),
        ("list_documentation", {}),
        ("read_documentation", {"module_name": "mhi.pscad"}),
    ),
)
@pytest.mark.parametrize(("argument_name", "value"), (("offset", True), ("offset", "1")))
async def test_registered_tools_do_not_coerce_invalid_offsets(
    tool_name,
    base_arguments,
    argument_name,
    value,
):
    server = create_server(environ={})
    tool = server._tool_manager.get_tool(tool_name)
    arguments = {**base_arguments, argument_name: value}

    result = await tool.run(arguments)

    assert result["error"]["code"] == "INVALID_ARGUMENT"
    assert result["error"]["operation"] == tool_name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "base_arguments", "bound_name"),
    (
        ("list_projects", {}, "limit"),
        ("find_components", {"project_name": "case"}, "limit"),
        ("get_project_definitions", {"project_name": "case"}, "limit"),
        ("list_canvas_components", {"project_name": "case"}, "limit"),
        ("list_documentation", {}, "limit"),
        ("read_documentation", {"module_name": "mhi.pscad"}, "max_chars"),
    ),
)
@pytest.mark.parametrize("value", (True, "1"))
async def test_registered_tools_do_not_coerce_invalid_result_bounds(
    tool_name,
    base_arguments,
    bound_name,
    value,
):
    server = create_server(environ={})
    tool = server._tool_manager.get_tool(tool_name)

    result = await tool.run({**base_arguments, bound_name: value})

    assert result["error"]["code"] == "INVALID_ARGUMENT"
    assert result["error"]["operation"] == tool_name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "bound_name"),
    (
        ("list_projects", "limit"),
        ("find_components", "limit"),
        ("get_project_definitions", "limit"),
        ("list_canvas_components", "limit"),
        ("list_documentation", "limit"),
        ("read_documentation", "max_chars"),
    ),
)
async def test_registered_pagination_schema_remains_integer_or_null(
    tool_name,
    bound_name,
):
    server = create_server(environ={})
    schema = server._tool_manager.get_tool(tool_name).parameters

    assert schema["properties"]["offset"]["type"] == "integer"
    assert {item["type"] for item in schema["properties"][bound_name]["anyOf"]} == {
        "integer",
        "null",
    }


@pytest.mark.asyncio
async def test_documentation_resource_templates_match_direct_reads(
    tmp_path,
    monkeypatch,
):
    manager = DocumentationManager(tmp_path / "docs")
    manager.md_dir.mkdir(parents=True)
    content = "0123456789" * 30
    (manager.md_dir / "mhi_pscad_types.md").write_text(content, encoding="utf-8")
    monkeypatch.setattr(app_tools, "doc_manager", manager)
    server = create_server(environ={})
    cases = (
        ("pscad-docs://modules/mhi.pscad.types", {}),
        ("pscad-docs://modules/mhi.pscad.types?offset=10", {"offset": 10}),
        (
            "pscad-docs://modules/mhi.pscad.types?max_chars=100",
            {"max_chars": 100},
        ),
        (
            "pscad-docs://modules/mhi.pscad.types?offset=10&max_chars=100",
            {"offset": 10, "max_chars": 100},
        ),
    )

    templates = [str(item.uriTemplate) for item in await server.list_resource_templates()]
    expected_order = [
        "pscad-docs://modules/{module_name}?offset={offset}&max_chars={max_chars}",
        "pscad-docs://modules/{module_name}?offset={offset}",
        "pscad-docs://modules/{module_name}?max_chars={max_chars}",
        "pscad-docs://modules/{module_name}",
    ]
    assert [uri for uri in templates if uri.startswith("pscad-docs://")] == [
        *expected_order,
    ]

    for uri, arguments in cases:
        direct = await app_tools.read_documentation("mhi.pscad.types", **arguments)
        resource = await server.read_resource(uri)
        assert len(resource) == 1
        assert resource[0].content == direct
        assert resource[0].mime_type == "text/markdown"
