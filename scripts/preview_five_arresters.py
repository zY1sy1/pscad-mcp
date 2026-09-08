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

from PIL import Image, ImageGrab

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('ARRESTER_PREVIEW_SOURCE', 'C:/Users/335/Documents/PSCAD-MCP/five_arresters_20260908'))
OUTPUT = SOURCE / 'native_preview' / datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')
OUTPUT.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(REPOSITORY))
os.environ.update(PSCAD_MCP_ACCEPTANCE='1', PSCAD_MCP_ACCEPTANCE_CONCURRENT='1',
    PSCAD_MCP_WORKSPACE=str(OUTPUT), PSCAD_MCP_BACKEND='legacy', PSCAD_MCP_VERSION='4.6.2',
    PSCAD_MCP_X64='true', PSCAD_MCP_LEGACY_MINIMIZE='true', PSCAD_MCP_LEGACY_EXISTING_POLICY='allow')

from pscad_mcp.acceptance.process_scope import (
    remaining_acceptance_processes,
    require_acceptance_ownership,
)
from pscad_mcp.core.connection_manager import pscad_manager
from pscad_mcp.core.process_inventory import list_pscad_processes


def save_clipboard(path):
    bitmap = ImageGrab.grabclipboard()
    if not isinstance(bitmap, Image.Image):
        raise TypeError('Native PSCAD bitmap was not available on the clipboard')
    if bitmap.width < 500 or bitmap.height < 300:
        raise RuntimeError(f'Native bitmap is collapsed or incomplete: {bitmap.size}')
    bitmap.save(path)
    return {'path': str(path), 'size': list(bitmap.size), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


async def main():
    name = 'five_sa_sequential'
    src = SOURCE / (name + '.pscx')
    path = OUTPUT / src.name
    shutil.copy2(src, path)
    report = {'status': 'RUNNING', 'source_sha256': hashlib.sha256(src.read_bytes()).hexdigest()}
    service = pscad_manager.service
    runtime = None
    active = False
    try:
        print(await service.attach_local(), flush=True)
        runtime = await service.status()
        require_acceptance_ownership(runtime)
        report['runtime'] = runtime
        print('OWNED', runtime['session']['managed_pid'], 'OUTPUT', OUTPUT, flush=True)
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
        report['native_graph'] = save_clipboard(OUTPUT / 'native_graph.png')
        canvas = await service.backend._canvas(name, 'Main')
        await service.backend.executor.run_safe(canvas.select_components, 72, 126, 1440, 900)
        await service.backend.executor.run_safe(canvas.copy_as_bitmap)
        report['native_schematic'] = save_clipboard(OUTPUT / 'native_schematic.png')
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
            (OUTPUT / 'preview_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps({'status': report['status'], 'output': str(OUTPUT),
                             'remaining_owned_pscad': report['remaining_owned_pscad']}, indent=2), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
