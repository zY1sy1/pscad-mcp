from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import logging
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import pscad_mcp
import pscad_mcp.utils.doc_manager as doc_manager_module
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.main import create_server
from pscad_mcp.tools import app_tools
from pscad_mcp.utils.doc_manager import DocumentationManager, SourceAnalyzer

ROOT = Path(__file__).parents[1]
SETTING = "PSCAD_MCP_DOCUMENTATION_DIR"


def test_manager_construction_does_not_write(tmp_path):
    root = tmp_path / "generated"

    manager = DocumentationManager(root)

    assert manager.base_dir == root.resolve()
    assert manager.md_dir == root.resolve() / "md"
    assert manager.raw_dir == root.resolve() / "raw"
    assert not root.exists()


def test_localappdata_default_is_lazy(tmp_path):
    manager = DocumentationManager.from_environ({"LOCALAPPDATA": str(tmp_path)})

    assert manager.base_dir == (tmp_path / "pscad-mcp" / "docs").resolve()
    assert not manager.base_dir.exists()


def test_home_state_default_is_lazy_without_localappdata(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    manager = DocumentationManager.from_environ({})

    assert manager.base_dir == (
        tmp_path / ".local" / "state" / "pscad-mcp" / "docs"
    ).resolve()
    assert not manager.base_dir.exists()


def test_explicit_absolute_documentation_override_is_lazy(tmp_path):
    root = tmp_path / "private-doc-state"

    manager = DocumentationManager.from_environ({SETTING: str(root)})

    assert manager.base_dir == root.resolve()
    assert manager.issue is None
    assert not root.exists()


def test_absolute_override_does_not_resolve_unused_home(tmp_path, monkeypatch):
    root = tmp_path / "private-doc-state"

    def unexpected_home():
        raise AssertionError("Path.home must not be called")

    monkeypatch.setattr(Path, "home", unexpected_home)

    manager = DocumentationManager.from_environ({SETTING: str(root)})

    assert manager.base_dir == root.resolve()
    assert manager.issue is None


def test_override_string_subclass_is_rejected_without_calling_user_code(
    tmp_path,
):
    class ExplodingString(str):
        def strip(self, *args, **kwargs):
            raise AssertionError("custom strip executed")

    manager = DocumentationManager.from_environ(
        {
            SETTING: ExplodingString(str(tmp_path / "secret")),
            "LOCALAPPDATA": str(tmp_path),
        }
    )

    assert manager.issue == SETTING
    assert not manager.base_dir.exists()


@pytest.mark.parametrize("local_app_data", ("relative", "", None))
def test_invalid_localappdata_falls_back_to_home_without_writing(
    tmp_path,
    monkeypatch,
    local_app_data,
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    manager = DocumentationManager.from_environ(
        {"LOCALAPPDATA": local_app_data}
    )

    assert manager.base_dir == (
        tmp_path / ".local" / "state" / "pscad-mcp" / "docs"
    ).resolve()
    assert not manager.base_dir.exists()


def test_localappdata_string_subclass_does_not_execute_custom_strip(
    tmp_path,
    monkeypatch,
):
    class ExplodingString(str):
        def strip(self, *args, **kwargs):
            raise AssertionError("custom strip executed")

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    manager = DocumentationManager.from_environ(
        {"LOCALAPPDATA": ExplodingString("SECRET_LOCAL_APP_DATA")}
    )

    assert manager.base_dir == (
        tmp_path / ".local" / "state" / "pscad-mcp" / "docs"
    ).resolve()
    assert not manager.base_dir.exists()


def test_invalid_documentation_override_names_only_the_setting():
    secret = "SECRET_RELATIVE_PATH"

    manager = DocumentationManager.from_environ({SETTING: secret})

    assert manager.issue == SETTING
    assert secret not in repr(manager)


def test_invalid_manager_sync_raises_sanitized_backend_error():
    secret = "SECRET_RELATIVE_PATH"
    manager = DocumentationManager.from_environ({SETTING: secret})

    with pytest.raises(BackendError) as raised:
        manager.sync()

    error = raised.value
    assert error.code == "DOCUMENTATION_CONFIG_INVALID"
    assert error.backend == "server"
    assert error.operation == "sync_documentation"
    assert error.details == {"setting": SETTING}
    assert secret not in repr(error.to_dict())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    (
        ("sync_documentation", {}),
        ("list_documentation", {}),
        ("read_documentation", {"module_name": "mhi.pscad"}),
    ),
)
async def test_invalid_configuration_uses_bounded_tool_error_envelope(
    tmp_path,
    monkeypatch,
    tool_name,
    arguments,
):
    secret = "SECRET_RELATIVE_PATH"
    manager = DocumentationManager.from_environ(
        {SETTING: secret, "LOCALAPPDATA": str(tmp_path)}
    )
    monkeypatch.setattr(app_tools, "doc_manager", manager)
    server = create_server(environ={})

    _, structured = await server._tool_manager.call_tool(
        tool_name,
        arguments,
        convert_result=True,
    )

    payload = structured["result"]["error"]
    assert payload["code"] == "DOCUMENTATION_CONFIG_INVALID"
    assert payload["backend"] == "server"
    assert payload["operation"] == tool_name
    assert payload["details"] == {"setting": SETTING}
    assert secret not in repr(payload)
    assert not manager.base_dir.exists()


def test_sync_creates_generated_directories_only_when_called(tmp_path):
    manager = DocumentationManager(tmp_path / "docs")
    manager.MODULES = ()

    assert manager.sync() == []

    assert manager.md_dir.is_dir()
    assert manager.raw_dir.is_dir()


def test_same_root_syncs_are_serialized_across_manager_instances(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "shared"
    managers = [DocumentationManager(root), DocumentationManager(root)]
    for manager in managers:
        manager.MODULES = ("mhi.pscad.fake",)

    start = threading.Barrier(3)
    counter_lock = threading.Lock()
    active = 0
    maximum_active = 0
    markers = []

    def render_doc(_module_name, **_kwargs):
        nonlocal active, maximum_active
        marker = f"complete-{threading.get_ident()}-{time.perf_counter_ns()}"
        with counter_lock:
            active += 1
            maximum_active = max(maximum_active, active)
            markers.append(marker)
        time.sleep(0.04)
        with counter_lock:
            active -= 1
        return f"NAME\n    {marker}\n"

    def synchronize(manager):
        start.wait(timeout=2)
        return manager.sync()

    monkeypatch.setattr(doc_manager_module.importlib.util, "find_spec", lambda _: None)
    monkeypatch.setattr(doc_manager_module.pydoc, "render_doc", render_doc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(synchronize, manager) for manager in managers]
        start.wait(timeout=2)
        results = [future.result(timeout=5) for future in futures]

    assert maximum_active == 1
    assert results == [
        ["Synced mhi.pscad.fake (Enriched)"],
        ["Synced mhi.pscad.fake (Enriched)"],
    ]
    raw = (root / "raw" / "mhi_pscad_fake.txt").read_text(encoding="utf-8")
    markdown = (root / "md" / "mhi_pscad_fake.md").read_text(encoding="utf-8")
    final_marker = next(marker for marker in markers if marker in raw)
    assert final_marker in markdown
    assert list(root.rglob("*.tmp")) == []


@pytest.mark.asyncio
async def test_concurrent_sync_wrappers_leave_complete_files(tmp_path, monkeypatch):
    manager = DocumentationManager(tmp_path / "shared")
    manager.MODULES = ("mhi.pscad.fake",)
    counter_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def render_doc(_module_name, **_kwargs):
        nonlocal active, maximum_active
        marker = f"wrapper-{threading.get_ident()}-{time.perf_counter_ns()}"
        with counter_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.03)
        with counter_lock:
            active -= 1
        return f"NAME\n    {marker}\n"

    monkeypatch.setattr(app_tools, "doc_manager", manager)
    monkeypatch.setattr(doc_manager_module.importlib.util, "find_spec", lambda _: None)
    monkeypatch.setattr(doc_manager_module.pydoc, "render_doc", render_doc)

    for _ in range(4):
        results = await asyncio.gather(
            app_tools.sync_documentation(),
            app_tools.sync_documentation(),
        )
        assert results == [
            ["Synced mhi.pscad.fake (Enriched)"],
            ["Synced mhi.pscad.fake (Enriched)"],
        ]

    assert maximum_active == 1
    raw = (manager.raw_dir / "mhi_pscad_fake.txt").read_text(encoding="utf-8")
    markdown = (manager.md_dir / "mhi_pscad_fake.md").read_text(encoding="utf-8")
    marker = raw.splitlines()[1].strip()
    assert marker.startswith("wrapper-")
    assert marker in markdown
    assert not any("Failed" in result for batch in results for result in batch)
    assert list(manager.base_dir.rglob("*.tmp")) == []


def test_different_documentation_roots_can_sync_in_parallel(tmp_path, monkeypatch):
    managers = [
        DocumentationManager(tmp_path / "first"),
        DocumentationManager(tmp_path / "second"),
    ]
    for manager in managers:
        manager.MODULES = ("mhi.pscad.fake",)

    start = threading.Barrier(3)
    both_active = threading.Event()
    counter_lock = threading.Lock()
    active = 0

    def render_doc(_module_name, **_kwargs):
        nonlocal active
        with counter_lock:
            active += 1
            if active == 2:
                both_active.set()
        both_active.wait(timeout=0.5)
        with counter_lock:
            active -= 1
        return "NAME\n    complete\n"

    def synchronize(manager):
        start.wait(timeout=2)
        return manager.sync()

    monkeypatch.setattr(doc_manager_module.importlib.util, "find_spec", lambda _: None)
    monkeypatch.setattr(doc_manager_module.pydoc, "render_doc", render_doc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(synchronize, manager) for manager in managers]
        start.wait(timeout=2)
        results = [future.result(timeout=5) for future in futures]

    assert both_active.is_set()
    assert all(result == ["Synced mhi.pscad.fake (Enriched)"] for result in results)


def test_source_analyzer_failure_log_does_not_disclose_source_path(
    tmp_path,
    caplog,
):
    source = tmp_path / "SECRET_PRIVATE_SOURCE" / "module.py"
    source.parent.mkdir()
    source.write_text("def invalid(:\n", encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="pscad-mcp.doc_manager"):
        SourceAnalyzer(source)

    messages = "\n".join(caplog.messages)
    assert "SECRET_PRIVATE_SOURCE" not in messages
    assert "SyntaxError" in messages


def test_fallback_outputs_and_logs_are_sanitized(tmp_path, monkeypatch, caplog):
    secret = str(tmp_path / "SECRET_PRIVATE_VENDOR_PATH")
    manager = DocumentationManager(tmp_path / "docs")
    manager.MODULES = ("mhi.pscad.fake",)

    def fail_pydoc(*_args, **_kwargs):
        raise RuntimeError(secret)

    def fail_import(_module_name):
        raise OSError(secret)

    monkeypatch.setattr(doc_manager_module.importlib.util, "find_spec", lambda _: None)
    monkeypatch.setattr(doc_manager_module.pydoc, "render_doc", fail_pydoc)
    monkeypatch.setattr(importlib, "import_module", fail_import)

    with caplog.at_level(logging.WARNING, logger="pscad-mcp.doc_manager"):
        results = manager.sync()

    raw = (manager.raw_dir / "mhi_pscad_fake.txt").read_text(encoding="utf-8")
    markdown = (manager.md_dir / "mhi_pscad_fake.md").read_text(encoding="utf-8")
    messages = "\n".join(caplog.messages)
    assert results == ["Synced mhi.pscad.fake (Enriched)"]
    assert raw == "MANUAL_INSPECTION_FAILED: OSError"
    assert "MANUAL_INSPECTION_FAILED: OSError" in markdown
    assert "pydoc failed for mhi.pscad.fake after RuntimeError" in messages
    assert secret not in repr((results, raw, markdown, messages))


@pytest.mark.asyncio
async def test_sync_failure_logs_and_mcp_result_are_sanitized(
    tmp_path,
    monkeypatch,
    caplog,
):
    secret = str(tmp_path / "SECRET_PRIVATE_DESTINATION")
    manager = DocumentationManager(tmp_path / "docs")
    manager.MODULES = ("mhi.pscad.fake",)

    def fail_write(*_args, **_kwargs):
        raise OSError(secret)

    monkeypatch.setattr(manager, "_atomic_write", fail_write)
    monkeypatch.setattr(app_tools, "doc_manager", manager)
    monkeypatch.setattr(doc_manager_module.importlib.util, "find_spec", lambda _: None)
    monkeypatch.setattr(
        doc_manager_module.pydoc,
        "render_doc",
        lambda *_args, **_kwargs: "NAME\n    safe\n",
    )
    server = create_server(environ={})

    with caplog.at_level(logging.ERROR, logger="pscad-mcp.doc_manager"):
        _, structured = await server._tool_manager.call_tool(
            "sync_documentation",
            {},
            convert_result=True,
        )

    result = structured["result"]
    messages = "\n".join(caplog.messages)
    assert result == ["Failed mhi.pscad.fake: OSError"]
    assert "Failed to sync mhi.pscad.fake after OSError" in messages
    assert secret not in repr((result, messages))
    assert list(manager.raw_dir.iterdir()) == []
    assert list(manager.md_dir.iterdir()) == []


def test_sync_rejects_symlinked_generated_directory(tmp_path, monkeypatch):
    base = tmp_path / "docs"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    try:
        (base / "md").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink unavailable: {type(error).__name__}")
    manager = DocumentationManager(base)
    manager.MODULES = ()
    replacements = []
    monkeypatch.setattr(os, "replace", lambda *args: replacements.append(args))

    with pytest.raises(BackendError) as raised:
        manager.sync()

    assert raised.value.code == "DOCUMENTATION_STORAGE_INVALID"
    assert raised.value.details == {"directory": "md"}
    assert str(outside) not in repr(raised.value.to_dict())
    assert list(outside.iterdir()) == []
    assert replacements == []


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_sync_rejects_junctioned_generated_directory(tmp_path, monkeypatch):
    base = tmp_path / "docs"
    outside = tmp_path / "outside"
    junction = base / "md"
    base.mkdir()
    outside.mkdir()
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        check=False,
        capture_output=True,
        text=True,
    )
    if created.returncode != 0:
        pytest.skip("Windows junction creation unavailable")

    try:
        manager = DocumentationManager(base)
        manager.MODULES = ()
        replacements = []
        monkeypatch.setattr(os, "replace", lambda *args: replacements.append(args))

        with pytest.raises(BackendError) as raised:
            manager.sync()

        assert raised.value.code == "DOCUMENTATION_STORAGE_INVALID"
        assert raised.value.details == {"directory": "md"}
        assert str(outside) not in repr(raised.value.to_dict())
        assert list(outside.iterdir()) == []
        assert replacements == []
    finally:
        if junction.exists():
            os.rmdir(junction)


def test_generated_markdown_redacts_source_path_and_reports_package_version(tmp_path):
    source = tmp_path / "private-user" / "module.py"
    manager = DocumentationManager(tmp_path / "docs")
    analyzer = type(
        "Analyzer",
        (),
        {"file_path": str(source), "classes": {}, "functions": {}},
    )()

    rendered = manager._extract_enriched_markdown(
        "mhi.pscad.fake",
        "NAME\n",
        analyzer,
    )

    installed_version = importlib.metadata.version("pscad-mcp")
    assert rendered.splitlines()[0] == (
        f"# Module mhi.pscad.fake (pscad-mcp {installed_version})"
    )
    assert str(source) not in rendered


def test_generated_markdown_removes_top_level_pydoc_file_section(tmp_path):
    source = r"C:\Users\private-user\site-packages\mhi\pscad\fake.py"
    raw_doc = "\n".join(
        (
            "NAME",
            "    mhi.pscad.fake",
            "",
            "DESCRIPTION",
            "    The word FILE in normal documentation must remain.",
            "",
            "FILE",
            f"    {source}",
            "    private continuation text",
            "",
            "FUNCTIONS",
            "    def public_function()",
        )
    )
    manager = DocumentationManager(tmp_path / "docs")

    rendered = manager._extract_enriched_markdown(
        "mhi.pscad.fake",
        raw_doc,
        None,
    )

    assert "## FILE" not in rendered
    assert source not in rendered
    assert "private continuation text" not in rendered
    assert "The word FILE in normal documentation must remain." in rendered
    assert "## FUNCTIONS" in rendered
    assert "public_function" in rendered


def test_generated_heading_falls_back_to_package_version(tmp_path, monkeypatch):
    def missing_distribution(_distribution):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", missing_distribution)
    manager = DocumentationManager(tmp_path / "docs")

    rendered = manager._extract_enriched_markdown(
        "mhi.pscad.fake",
        "NAME\n",
        None,
    )

    assert rendered.splitlines()[0] == (
        f"# Module mhi.pscad.fake (pscad-mcp {pscad_mcp.__version__})"
    )


def test_atomic_write_replaces_destination_without_temp_residue(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "module.md"
    target.write_text("old", encoding="utf-8")
    replacements = []
    fsynced = []
    real_replace = os.replace
    real_fsync = os.fsync

    def record_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    def record_fsync(file_descriptor):
        fsynced.append(file_descriptor)
        real_fsync(file_descriptor)

    monkeypatch.setattr(os, "replace", record_replace)
    monkeypatch.setattr(os, "fsync", record_fsync)

    DocumentationManager._atomic_write(target, "new")

    assert target.read_text(encoding="utf-8") == "new"
    assert replacements[0][0].parent == tmp_path
    assert replacements[0][1] == target
    assert fsynced
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_failure_deletes_only_its_own_temp_file(tmp_path, monkeypatch):
    target = tmp_path / "module.md"
    unrelated = tmp_path / "keep.tmp"
    unrelated.write_text("keep", encoding="utf-8")

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        DocumentationManager._atomic_write(target, "new")

    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert sorted(tmp_path.iterdir()) == [unrelated]


@pytest.mark.asyncio
async def test_sync_wrapper_runs_blocking_work_in_a_thread(tmp_path, monkeypatch):
    manager = DocumentationManager(tmp_path / "docs")
    calls = []

    def sync():
        return ["synced"]

    async def to_thread(function, *args, **kwargs):
        calls.append((function, args, kwargs))
        return function(*args, **kwargs)

    monkeypatch.setattr(manager, "sync", sync)
    monkeypatch.setattr(app_tools, "doc_manager", manager)
    monkeypatch.setattr(asyncio, "to_thread", to_thread)

    assert await app_tools.sync_documentation() == ["synced"]
    assert calls == [(sync, (), {})]


@pytest.mark.asyncio
async def test_server_reads_registered_documentation_resource(tmp_path, monkeypatch):
    manager = DocumentationManager(tmp_path / "docs")
    manager.md_dir.mkdir(parents=True)
    expected = "# Local PSCAD documentation\n"
    (manager.md_dir / "mhi_pscad_fake.md").write_text(expected, encoding="utf-8")
    monkeypatch.setattr(app_tools, "doc_manager", manager)
    server = create_server(environ={})

    templates = await server.list_resource_templates()
    template = next(
        item
        for item in templates
        if str(item.uriTemplate) == "pscad-docs://modules/{module_name}"
    )
    assert template.name == "pscad_documentation_module"
    assert template.description == (
        "Read one locally generated PSCAD API documentation module."
    )
    assert template.mimeType == "text/markdown"

    contents = await server.read_resource("pscad-docs://modules/mhi.pscad.fake")

    assert len(contents) == 1
    assert contents[0].content == expected
    assert contents[0].mime_type == "text/markdown"


def test_importing_main_creates_no_documentation_directories(tmp_path):
    local_app_data = tmp_path / "local-app-data"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    env = os.environ.copy()
    for name in tuple(env):
        if name.startswith("PSCAD_MCP") and "ACCEPTANCE" in name:
            env.pop(name)
    env.pop("PSCAD_MCP_HVDC_SOURCE", None)
    env.pop("PSCAD_MCP_HVDC_LIBRARY", None)
    env["LOCALAPPDATA"] = str(local_app_data)
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    imported = subprocess.run(
        [sys.executable, "-c", "import pscad_mcp.main"],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert imported.returncode == 0, imported.stderr
    assert not (local_app_data / "pscad-mcp" / "docs").exists()
    assert not (cwd / "docs").exists()
