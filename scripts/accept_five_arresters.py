"""Fresh, isolated acceptance of the user's five-arrester demonstration."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

import psutil

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from pscad_mcp.acceptance.process_scope import (
    acceptance_launch_policy,
    managed_acceptance_pid,
    remaining_acceptance_processes,
    require_acceptance_ownership,
)
from pscad_mcp.core.process_inventory import list_pscad_processes

CASES = {'five_sa_sequential': [1, 2, 3, 4, 5], 'five_sa_reverse': [5, 4, 3, 2, 1]}
MASTER = Path('C:/Program Files (x86)/PSCAD46/master.pslx')
COMPILER = Path('C:/Program Files (x86)/GFortran/4.2.1/bin/gfortran.exe')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def physical_signature(path):
    root = ET.parse(path).getroot()
    main = root.find('./definitions/Definition[@name="Main"]/schematic')
    items = []
    for c in main.findall('User'):
        params = {p.get('name'): p.get('value') for p in c.findall('./paramlist/param')}
        params.pop('BOpen', None)
        if c.get('defn') == 'master:pgb':
            params.pop('enab', None)
        items.append({'id': c.get('id'), 'definition': c.get('defn'),
            'position': [c.get(k) for k in ('x', 'y', 'orient')], 'parameters': params})
    wires = [{'position': [w.get(k) for k in ('x', 'y', 'orient')],
        'vertices': [dict(p.attrib) for p in w.findall('vertex')]} for w in main.findall('Wire')]
    settings = {p.get('name'): str(Decimal(p.get('value')).normalize()) for p in root.findall('./paramlist[@name="Settings"]/param')
                if p.get('name') in {'time_duration', 'time_step', 'sample_step', 'StartType', 'PlotType'}}
    payload = {'components': sorted(items, key=lambda c: c['id']),
               'wires': sorted(wires, key=lambda w: json.dumps(w, sort_keys=True)), 'settings': settings}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def write_report(directory, report):
    (directory / 'acceptance.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


async def accept(source, destination, report):
    from pscad_mcp.core.connection_manager import pscad_manager

    service = pscad_manager.service
    runtime = None
    current_case = None
    model_paths = []
    for name in CASES:
        src, dst = source / (name + '.pscx'), destination / (name + '.pscx')
        shutil.copy2(src, dst)
        model_paths.append(dst)
        # GUI streaming is independent of EMTDC disk output and electrical logic.
        tree = ET.parse(dst)
        for p in tree.findall('.//User[@defn="master:pgb"]/paramlist/param[@name="enab"]'):
            p.set('value', '0')
        tree.write(dst, encoding='utf-8', xml_declaration=True)
        assert physical_signature(src) == physical_signature(dst)
    try:
        print(await service.attach_local(), flush=True)
        runtime = await service.status()
        report['runtime'] = runtime
        require_acceptance_ownership(runtime)
        pid = managed_acceptance_pid(runtime)
        if not runtime.get('licensed') or pid is None:
            raise RuntimeError('Licensed owned PSCAD instance required')
        owned = psutil.Process(pid)
        report['owned_process'] = {'pid': pid, 'created_at': owned.create_time(), 'executable': owned.exe()}
        print('OWNED PSCAD PID', pid, flush=True)
        write_report(destination, report)
        workspace = source / 'FiveArresters.pswx'
        if workspace.is_file():
            shutil.copy2(workspace, destination / workspace.name)
            await service.load_projects([str(destination / workspace.name)])
            report['workspace_load'] = {'path': str(destination / workspace.name), 'relocated': True}
        else:
            await service.load_projects([str(p) for p in model_paths])
        for path in model_paths:
            name = path.stem
            entry = report['cases'][name] = {'model_sha256_before_build': sha(path)}
            print('BUILD', name, flush=True)
            await service.build_project(name)
            project = await service.backend._project(name)
            entry['build_messages'] = [m._asdict() for m in await service.backend.executor.run_safe(project.messages)]
            errors = [m for m in entry['build_messages'] if m['status'].lower() == 'error']
            if errors:
                raise RuntimeError('Build failed: ' + json.dumps(errors))
            await service.save_project(name, confirm=True)
            if physical_signature(path) != physical_signature(source / path.name):
                raise RuntimeError('Electrical model changed on PSCAD save')
            current_case = name
            print(await service.run_project(name), flush=True)
            deadline = time.monotonic() + 600
            last_progress = None
            while True:
                await asyncio.sleep(1)
                state = await service.backend.project_run_state(name)
                progress = (state.status, None if state.progress is None else int(state.progress) // 10)
                if progress != last_progress:
                    print(name, state, flush=True)
                    last_progress = progress
                if state.status.lower() in {'idle', 'stopped', 'completed', 'complete', 'ready'}:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError(name)
            current_case = None
            entry['run_messages'] = [m._asdict() for m in await service.backend.executor.run_safe(project.messages)]
            if any(m['status'].lower() == 'error' for m in entry['run_messages']):
                raise RuntimeError('PSCAD reported a run error')
            entry['model_sha256'] = sha(path)
            entry['physical_signature'] = physical_signature(path)
            entry['elapsed_complete_at'] = time.time()
            write_report(destination, report)
    finally:
        original_error = sys.exception()
        cleanup = report['cleanup'] = {'owned_pid': managed_acceptance_pid(runtime) if runtime else None}
        cleanup_problems = []
        try:
            try:
                if current_case is not None:
                    state = await service.backend.project_run_state(current_case)
                    if state.status.lower() in {'running', 'paused', 'starting'}:
                        await service.backend.stop_project(current_case)
            except Exception as error:  # noqa: BLE001 - still attempt owned-instance shutdown.
                cleanup['stop_error'] = {'type': type(error).__name__, 'message': str(error)}
            try:
                await service.shutdown()
            except Exception as error:  # noqa: BLE001 - inventory and original failure must survive shutdown errors.
                cleanup['shutdown_error'] = {'type': type(error).__name__, 'message': str(error)}
                cleanup_problems.append('Owned PSCAD shutdown failed')
            try:
                cleanup['remaining_owned_pscad'] = remaining_acceptance_processes(runtime, list_pscad_processes) if runtime else []
                if cleanup['remaining_owned_pscad']:
                    cleanup_problems.append('Owned PSCAD instance did not exit')
                # A child executable is owned only when its full path is in this run.
                emtdc_paths = {str(destination / (name + '.gf42') / (name + '.exe')).casefold() for name in CASES}
                remaining_emtdc = []
                for proc in psutil.process_iter(['pid', 'exe']):
                    if (proc.info.get('exe') or '').casefold() in emtdc_paths:
                        remaining_emtdc.append(proc.info)
                cleanup['remaining_owned_emtdc'] = remaining_emtdc
                if remaining_emtdc:
                    cleanup_problems.append('Owned EMTDC executable did not exit')
            except Exception as error:  # noqa: BLE001 - retain failed cleanup evidence.
                cleanup['inventory_error'] = {'type': type(error).__name__, 'message': str(error)}
                cleanup_problems.append('Owned process inventory failed')
        finally:
            await pscad_manager.shutdown_executor()
            write_report(destination, report)
        if cleanup_problems and original_error is None:
            raise RuntimeError('; '.join(cleanup_problems))


def main():
    if not __debug__:
        raise RuntimeError('Optimized Python is not supported for acceptance; run without -O or PYTHONOPTIMIZE')
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if os.environ.get('PSCAD_MCP_ACCEPTANCE') != '1' or os.environ.get('PSCAD_MCP_ACCEPTANCE_CONCURRENT') != '1':
        raise SystemExit('PSCAD_MCP_ACCEPTANCE=1 and PSCAD_MCP_ACCEPTANCE_CONCURRENT=1 are required')
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    source = args.source.resolve()
    os.environ.update(PSCAD_MCP_BACKEND='legacy', PSCAD_MCP_VERSION='4.6.2', PSCAD_MCP_X64='true',
        PSCAD_MCP_WORKSPACE=str(destination), PSCAD_MCP_LEGACY_MINIMIZE='true',
        PSCAD_MCP_LEGACY_EXISTING_POLICY=acceptance_launch_policy())
    immutable = [MASTER, COMPILER, *[source / (name + '.pscx') for name in CASES], source / 'analyze_results.py']
    if (source / 'FiveArresters.pswx').is_file():
        immutable.append(source / 'FiveArresters.pswx')
    report = {'status': 'RUNNING', 'repository': str(REPOSITORY),
        'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPOSITORY, text=True).strip(),
        'runner_sha256': sha(Path(__file__)), 'concurrent_acceptance': True,
        'immutable_inputs': {str(p): sha(p) for p in immutable}, 'cases': {},
        'scope': 'Exclusive five-arrester ideal-switch operation; original physical criteria unchanged',
        'gui_streaming': 'disabled in run copies; full EMTDC disk output retained'}
    write_report(destination, report)
    try:
        subprocess.run(['git', 'merge-base', '--is-ancestor', 'db65d74', 'HEAD'], cwd=REPOSITORY, check=True)
        asyncio.run(accept(source, destination, report))
        spec = importlib.util.spec_from_file_location('arrester_analysis', source / 'analyze_results.py')
        analysis = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(analysis)
        analysis.ROOT = destination
        for name, order in CASES.items():
            metrics, times, channels = analysis.validate(name, order)
            report['cases'][name]['physical_validation'] = metrics
            if name == 'five_sa_sequential':
                analysis.plot(times, channels)
            report['cases'][name]['outputs'] = {str(p.relative_to(destination)): sha(p)
                for p in (destination / (name + '.gf42')).iterdir() if p.suffix in {'.out', '.inf'}}
        assert all(sha(Path(path)) == value for path, value in report['immutable_inputs'].items())
        report['source_hashes_unchanged'] = True
        report['status'] = 'PASS'
    except Exception as error:  # noqa: BLE001 - preserve failure evidence at the CLI boundary.
        report['status'] = 'FAIL'
        report['error'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
        traceback.print_exc()
    finally:
        write_report(destination, report)
    print(json.dumps({'status': report['status'], 'report': str(destination / 'acceptance.json'),
                      'cleanup': report.get('cleanup'), 'error': report.get('error', {}).get('message')}, indent=2), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
