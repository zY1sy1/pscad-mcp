"""Render a native PSCAD model and its native graph frame for delivery QA."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from pscad_mcp.acceptance.process_scope import (
    remaining_acceptance_processes,
    require_acceptance_ownership,
)
from pscad_mcp.core.process_inventory import list_pscad_processes
from scripts.accept_five_arresters import (
    copy_external_data_files,
    external_data_files,
    require_licensed_acceptance,
)


def save_clipboard(path):
    from PIL import Image, ImageGrab

    bitmap = ImageGrab.grabclipboard()
    if not isinstance(bitmap, Image.Image):
        raise TypeError('Native PSCAD bitmap was not available on the clipboard')
    if bitmap.width < 500 or bitmap.height < 300:
        raise RuntimeError(f'Native bitmap is collapsed or incomplete: {bitmap.size}')
    bitmap.save(path)
    return {'path': str(path), 'size': list(bitmap.size), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


async def main():
    require_licensed_acceptance()
    source = Path(os.environ.get('ARRESTER_PREVIEW_SOURCE', 'C:/Users/335/Documents/PSCAD-MCP/five_arresters_20260908'))
    default_output = source / 'native_preview' / datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')
    output = Path(os.environ.get('ARRESTER_PREVIEW_OUTPUT', str(default_output))).resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ.update(PSCAD_MCP_WORKSPACE=str(output), PSCAD_MCP_BACKEND='legacy', PSCAD_MCP_VERSION='4.6.2',
        PSCAD_MCP_X64='true', PSCAD_MCP_LEGACY_MINIMIZE='true', PSCAD_MCP_LEGACY_EXISTING_POLICY='allow')
    # Construct the service only after its process-local workspace is scoped.
    from pscad_mcp.core.connection_manager import pscad_manager

    name = os.environ.get('ARRESTER_PREVIEW_CASE', 'five_sa_sequential')
    src = source / (name + '.pscx')
    path = output / src.name
    shutil.copy2(src, path)
    data_files = external_data_files(source, [src])
    copied_data_files = copy_external_data_files(source, output, data_files)
    report = {'status': 'RUNNING', 'source_sha256': hashlib.sha256(src.read_bytes()).hexdigest(),
              'external_data_files': {
                  str(item.relative_to(output)): hashlib.sha256(item.read_bytes()).hexdigest()
                  for item in copied_data_files
              }}
    service = pscad_manager.service
    runtime = None
    active = False
    try:
        print(await service.attach_local(), flush=True)
        runtime = await service.status()
        require_acceptance_ownership(runtime)
        report['runtime'] = runtime
        print('OWNED', runtime['session']['managed_pid'], 'OUTPUT', output, flush=True)
        await service.load_projects([str(path)])
        project = await service.backend._project(name)
        await service.build_project(name)
        report['build_messages'] = [m._asdict() for m in await service.backend.executor.run_safe(project.messages)]
        if any(m['status'].lower() == 'error' for m in report['build_messages']):
            raise RuntimeError('Native preview build failed')
        await service.run_project(name)
        active = True
        deadline = time.monotonic() + 600
        last = None
        while True:
            await asyncio.sleep(1)
            state = await service.backend.project_run_state(name)
            progress = (state.status, None if state.progress is None else int(state.progress)//10)
            if progress != last:
                print('RUN', state, flush=True)
                last = progress
            if state.status.lower() in {'idle', 'complete', 'completed'}:
                break
            if time.monotonic() > deadline:
                raise TimeoutError('Native display run')
        active = False
        frame_id = int(ET.parse(path).find('.//Frame[@classid="GraphFrame"]').get('id'))
        frame = await service.backend.executor.run_safe(project.graph_frame, 'Main', frame_id)
        await service.backend.executor.run_safe(frame.copy_as_bitmap)
        report['native_graph'] = save_clipboard(output / 'native_graph.png')
        canvas = await service.backend._canvas(name, 'Main')
        await service.backend.executor.run_safe(canvas.select_components, 72, 126, 1440, 900)
        await service.backend.executor.run_safe(canvas.copy_as_bitmap)
        report['native_schematic'] = save_clipboard(output / 'native_schematic.png')
        if hashlib.sha256(src.read_bytes()).hexdigest() != report['source_sha256']:
            raise RuntimeError('Source model changed during native preview')
        report['status'] = 'RENDERED'
    except Exception as error:
        report['status'] = 'FAIL'
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        try:
            try:
                if active:
                    await service.backend.stop_project(name)
            finally:
                await service.shutdown()
        finally:
            await pscad_manager.shutdown_executor()
            report['remaining_owned_pscad'] = remaining_acceptance_processes(runtime, list_pscad_processes) if runtime else []
            (output / 'preview_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps({'status': report['status'], 'output': str(output),
                             'remaining_owned_pscad': report['remaining_owned_pscad']}, indent=2), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
