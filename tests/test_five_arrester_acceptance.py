"""Five-arrester acceptance must fail closed and release its owned session."""

import ast
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

RUNNER = Path(__file__).parents[1] / "scripts" / "accept_five_arresters.py"
ANALYSIS = Path(
    "C:/Users/335/Documents/PSCAD-MCP/five_arresters_20260908/analyze_results.py"
)


def _optimized_function(path, name, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, str(path), "exec", optimize=1), namespace)  # noqa: S102 - test trusted source under -O.
    return namespace[name]


def test_optimized_runner_refuses_before_argument_parsing():
    parser = Mock(side_effect=AssertionError("Optimized runner reached argument parsing"))
    main = _optimized_function(
        RUNNER, "main", {"argparse": SimpleNamespace(ArgumentParser=parser)}
    )

    with pytest.raises(RuntimeError, match="Optimized Python"):
        main()

    parser.assert_not_called()


@pytest.mark.skipif(not ANALYSIS.is_file(), reason="External model analyzer is absent")
def test_optimized_analysis_refuses_before_reading_evidence():
    reader = Mock(side_effect=AssertionError("Optimized analyzer reached output reading"))
    validate = _optimized_function(ANALYSIS, "validate", {"read_case": reader})

    with pytest.raises(RuntimeError, match="Optimized Python"):
        validate("five_sa_sequential", [1, 2, 3, 4, 5])

    reader.assert_not_called()


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location("five_arrester_acceptance_test", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.sys = SimpleNamespace(exc_info=sys.exc_info)
    return module


def test_equivalent_saved_time_setting_keeps_physical_signature(runner, tmp_path):
    before, after = tmp_path / 'before.pscx', tmp_path / 'after.pscx'
    xml = ('<project><paramlist name="Settings"><param name="time_duration" value="{}"/>'
           '</paramlist><definitions><Definition name="Main"><schematic/>'
           '</Definition></definitions></project>')
    before.write_text(xml.format('0.010'), encoding='utf-8')
    after.write_text(xml.format('0.01'), encoding='utf-8')
    assert runner.physical_signature(before) == runner.physical_signature(after)


def test_changed_time_setting_changes_physical_signature(runner, tmp_path):
    before, after = tmp_path / 'before.pscx', tmp_path / 'after.pscx'
    xml = ('<project><paramlist name="Settings"><param name="time_duration" value="{}"/>'
           '</paramlist><definitions><Definition name="Main"><schematic/>'
           '</Definition></definitions></project>')
    before.write_text(xml.format('0.010'), encoding='utf-8')
    after.write_text(xml.format('0.02'), encoding='utf-8')
    assert runner.physical_signature(before) != runner.physical_signature(after)


def test_external_arrester_data_files_are_discovered_and_copied(runner, tmp_path):
    source, destination = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    destination.mkdir()
    curve = source / "YH10WL_33_50_IV.dat"
    curve.write_text("0.001 1.0 /\nENDFILE:\n", encoding="ascii")
    model = source / "five_sa_sequential.pscx"
    model.write_text(
        '<project><definitions><Definition name="Main"><schematic>'
        '<User defn="master:arrester"><paramlist>'
        '<param name="Cnfg" value="2"/>'
        '<param name="File" value="YH10WL_33_50_IV.dat"/>'
        '<param name="path" value="0"/>'
        '</paramlist></User></schematic></Definition></definitions></project>',
        encoding="utf-8",
    )

    discovered = runner.external_data_files(source, [model])
    assert discovered == [curve.resolve()]

    copied = runner.copy_external_data_files(source, destination, discovered)
    assert copied == [destination / curve.name]
    assert copied[0].read_bytes() == curve.read_bytes()


def _run_cleanup_failure(
    runner, monkeypatch, tmp_path, failure_at, *, shutdown_fails=False,
):
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    name = "five_sa_sequential"
    monkeypatch.setattr(runner, "CASES", {name: [1, 2, 3, 4, 5]})
    source, destination = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    destination.mkdir()
    (source / f"{name}.pscx").write_text(
        '<project><paramlist name="Settings"/><definitions>'
        '<Definition name="Main"><schematic/></Definition>'
        '</definitions></project>',
        encoding="utf-8",
    )

    async def run_safe(operation):
        return operation()

    cleanup_error = TimeoutError(f"cleanup {failure_at} failed")
    backend = SimpleNamespace(
        _project=AsyncMock(return_value=SimpleNamespace(messages=list)),
        executor=SimpleNamespace(run_safe=run_safe),
        project_run_state=AsyncMock(
            side_effect=cleanup_error if failure_at == "status" else None,
            return_value=SimpleNamespace(status="running", progress=0),
        ),
        stop_project=AsyncMock(
            side_effect=cleanup_error if failure_at == "stop" else None,
        ),
    )
    runtime = {
        "licensed": True, "owns_process": True,
        "session": {"managed_pid": 4242},
    }
    service = SimpleNamespace(
        backend=backend,
        attach_local=AsyncMock(return_value="Owned mock PSCAD"),
        status=AsyncMock(return_value=runtime),
        load_projects=AsyncMock(),
        build_project=AsyncMock(),
        save_project=AsyncMock(),
        run_project=AsyncMock(side_effect=RuntimeError("run submission failed")),
        shutdown=AsyncMock(
            side_effect=RuntimeError("owned shutdown failed") if shutdown_fails else None,
        ),
    )
    manager = SimpleNamespace(service=service, shutdown_executor=AsyncMock())
    connection_module = ModuleType("pscad_mcp.core.connection_manager")
    connection_module.pscad_manager = manager
    monkeypatch.setitem(
        sys.modules, "pscad_mcp.core.connection_manager", connection_module,
    )
    emtdc_inventory = Mock(return_value=[])
    monkeypatch.setattr(
        runner, "psutil",
        SimpleNamespace(
            Process=lambda pid: SimpleNamespace(
                create_time=lambda: 100.0, exe=lambda: "C:/owned/pscad.exe",
            ),
            process_iter=emtdc_inventory,
        ),
    )
    pscad_inventory = Mock(return_value=[])
    monkeypatch.setattr(runner, "remaining_acceptance_processes", pscad_inventory)
    report = {"cases": {}}

    with pytest.raises(Exception) as raised:
        asyncio.run(runner.accept(source, destination, report))

    return SimpleNamespace(
        service=service, manager=manager, report=report, error=raised.value,
        saved_report=json.loads((destination / "acceptance.json").read_text(encoding="utf-8")),
        cleanup_error=cleanup_error, pscad_inventory=pscad_inventory,
        emtdc_inventory=emtdc_inventory,
    )


@pytest.mark.parametrize("failure_at", ["status", "stop"])
def test_cleanup_error_still_shuts_down_owned_pscad(
    runner, monkeypatch, tmp_path, failure_at,
):
    result = _run_cleanup_failure(runner, monkeypatch, tmp_path, failure_at)

    result.service.shutdown.assert_awaited_once()
    result.manager.shutdown_executor.assert_awaited_once()
    assert str(result.cleanup_error) in str(result.report["cleanup"]["stop_error"])
    assert isinstance(result.error, RuntimeError)
    assert str(result.error) == "run submission failed"


@pytest.mark.parametrize("failure_at", ["status", "stop"])
def test_shutdown_failure_retains_cleanup_errors_and_queries_owned_processes(
    runner, monkeypatch, tmp_path, failure_at,
):
    result = _run_cleanup_failure(
        runner, monkeypatch, tmp_path, failure_at, shutdown_fails=True,
    )

    cleanup = result.saved_report.get("cleanup", {})
    assert {
        "stop_error": cleanup.get("stop_error"),
        "shutdown_error": cleanup.get("shutdown_error"),
        "pscad_inventory_calls": result.pscad_inventory.call_count,
        "emtdc_inventory_calls": result.emtdc_inventory.call_count,
    } == {
        "stop_error": {"type": "TimeoutError", "message": f"cleanup {failure_at} failed"},
        "shutdown_error": {"type": "RuntimeError", "message": "owned shutdown failed"},
        "pscad_inventory_calls": 1,
        "emtdc_inventory_calls": 1,
    }
    result.service.shutdown.assert_awaited_once()
    result.manager.shutdown_executor.assert_awaited_once()
