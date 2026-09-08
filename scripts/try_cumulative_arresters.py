"""Measure current redistribution with cumulative arrester breaker closure."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import accept_five_arresters as lifecycle
import numpy as np

BASELINE = Path('C:/Users/335/Documents/PSCAD-MCP/five_arresters_20260908/delivery-v2')
COLORS = ['#176B91', '#C07017', '#728A30', '#BA5380', '#554B9C']


def load_analysis():
    spec = importlib.util.spec_from_file_location('previous_arrester_analysis', BASELINE / 'analyze_results.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_models(destination):
    changes = {}
    for name, order in lifecycle.CASES.items():
        tree = ET.parse(BASELINE / (name + '.pscx'))
        timers = tree.findall('.//User[@defn="master:tbreakn"]')
        if len(timers) != 5:
            raise RuntimeError('Expected five native timed-breaker blocks')
        changes[name] = []
        for branch, timer in enumerate(timers, start=1):
            slot = order.index(branch)
            values = {'INIT': '0' if slot == 0 else '1', 'NUMS': '1',
                      'TO1': '0.012' if slot == 0 else str(slot * 0.002), 'TO2': '0.012'}
            before = {p.get('name'): p.get('value') for p in timer.findall('./paramlist/param')}
            for p in timer.findall('./paramlist/param'):
                if p.get('name') in values:
                    p.set('value', values[p.get('name')])
            changes[name].append({'branch': branch, 'before': before, 'after': values})
        tree.find('./paramlist[@name="Settings"]/param[@name="description"]').set(
            'value', 'Cumulative closing: previous arrester branches remain connected')
        tree.find('.//Frame/paramlist/param[@name="title"]').set(
            'value', 'Cumulative closing / no previous branch opens')
        ET.indent(tree, space='  ')
        tree.write(destination / (name + '.pscx'), encoding='utf-8', xml_declaration=True)
    workspace = ET.parse(BASELINE / 'FiveArresters.pswx')
    workspace.getroot().set('name', 'CumulativeArresters')
    workspace.write(destination / 'CumulativeArresters.pswx', encoding='utf-8', xml_declaration=True)
    (destination / 'control_changes.json').write_text(json.dumps(changes, indent=2), encoding='utf-8')
    return changes


def characterize(times, channels, order):
    currents = np.vstack([channels[f'I{i}'] for i in range(1, 6)])
    states = np.vstack([channels[f'B{i}'] for i in range(1, 6)])
    if not np.isin(states, [0, 2]).all():
        raise RuntimeError('Unexpected actual breaker status')
    closed = states == 0
    if np.any(np.diff(closed.astype(int), axis=1) < 0):
        raise RuntimeError('A previously closed breaker opened')
    if closed[:, 0].sum() != 1 or not closed[:, -1].all():
        raise RuntimeError('Expected one initially closed and five finally closed switches')
    kcl_error_A = float(np.max(np.abs(channels['ISOURCE'] - currents.sum(axis=0))) * 1000)
    if kcl_error_A >= 0.01:
        raise RuntimeError(f'KCL error {kcl_error_A} A exceeds the unchanged criterion')
    closing_times = []
    stages = []
    for slot, branch in enumerate(order):
        actual_close = float(times[np.flatnonzero(closed[branch - 1])[0]])
        if abs(actual_close - slot * 0.002) > 1.00001e-6:
            raise RuntimeError('Closing event differs by more than one integration step')
        closing_times.append({'branch': branch, 'actual_time_ms': actual_close * 1000})
        start, end = slot * 0.002, (slot + 1) * 0.002
        steady = (times >= start + 0.0005) & (times < end - 0.0002)
        expected = np.array([i in order[:slot + 1] for i in range(1, 6)])
        if not np.all(closed[:, steady] == expected[:, None]):
            raise RuntimeError('Cumulative breaker state does not match the requested schedule')
        if (~expected).any() and np.max(np.abs(currents[~expected][:, steady])) * 1000 >= 0.001:
            raise RuntimeError('An open branch exceeds the unchanged 1 mA leakage criterion')
        means_A = currents[:, steady].mean(axis=1) * 1000
        total_A = float(means_A.sum())
        if total_A <= 500:
            raise RuntimeError('The source is not sufficiently energized for the trial')
        dominant = int(np.argmax(means_A)) + 1
        old = [i - 1 for i in order[:slot]]
        stages.append({'start_ms': start * 1000, 'end_ms': end * 1000,
            'closed_branches': order[:slot + 1], 'new_branch': branch,
            'mean_bus_kV': float(channels['VBUS'][steady].mean()),
            'mean_currents_A': means_A.tolist(), 'total_current_A': total_A,
            'dominant_branch': dominant, 'new_branch_share_pct': float(means_A[branch - 1] / total_A * 100),
            'previous_branches_total_A': float(means_A[old].sum()) if old else 0.0,
            'conducting_branches_over_1A': [i + 1 for i, value in enumerate(means_A) if value > 1]})
    working = (np.abs(currents) > 0.001).sum(axis=0)
    return {'verification': 'PASS', 'samples': len(times), 'step_us': 1,
        'max_KCL_error_A': kcl_error_A, 'no_reopening': True, 'closing_times': closing_times,
        'dominant_sequence': [s['dominant_branch'] for s in stages],
        'dominant_follows_new_branch': all(s['dominant_branch'] == s['new_branch'] for s in stages),
        'single_working_branch_all_samples': bool(working.max() <= 1),
        'max_simultaneous_branches_over_1A': int(working.max()), 'stages': stages}


def plot_comparison(destination, datasets):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(3, 2, figsize=(12.5, 8), sharex=True)
    fig.subplots_adjust(left=0.075, right=0.985, bottom=0.095, top=0.86, hspace=0.15, wspace=0.17)
    for column, (name, (times, channels)) in enumerate(datasets.items()):
        title = '100 -> 90 -> 80 -> 70 -> 60 kV' if column == 0 else '60 -> 70 -> 80 -> 90 -> 100 kV'
        axes[0, column].set_title(title + '\nPrevious switches stay closed', fontsize=12)
        for branch, color in enumerate(COLORS, start=1):
            axes[0, column].plot(times * 1000, channels[f'I{branch}'], color=color, lw=1.6,
                                 label=f'SA{branch}')
        axes[0, column].set_ylim(-0.08, 3.3)
        axes[0, column].legend(ncol=5, frameon=False, fontsize=8, loc='upper left')
        axes[1, column].plot(times * 1000, channels['VBUS'], color='#30363B', lw=1.5)
        axes[1, column].set_ylim(0, 125)
        closed = sum(channels[f'B{i}'] == 0 for i in range(1, 6))
        working = sum(np.abs(channels[f'I{i}']) > 0.001 for i in range(1, 6))
        axes[2, column].step(times * 1000, closed, where='post', color='#30363B', lw=1.5, label='Closed switches')
        axes[2, column].step(times * 1000, working, where='post', color='#176B91', lw=1.4,
                             ls='--', label='Branches > 1 A')
        axes[2, column].set_ylim(-0.2, 5.5)
        axes[2, column].set_yticks(range(6))
        axes[2, column].legend(frameon=False, fontsize=8, loc='upper left')
        axes[2, column].set_xlabel('Time (ms)')
        for row in range(3):
            axes[row, column].set_xlim(0, 10)
            axes[row, column].grid(axis='y', color='#DFE3E6', lw=0.7)
            for event in [2, 4, 6, 8]:
                axes[row, column].axvline(event, color='#C0C5C9', ls=':', lw=0.7)
    axes[0, 0].set_ylabel('Arrester current (kA)')
    axes[1, 0].set_ylabel('Bus voltage (kV)')
    axes[2, 0].set_ylabel('Count')
    fig.suptitle('Cumulative arrester switching: measured PSCAD results', fontsize=16, y=0.98)
    fig.text(0.07, 0.012, 'Illustrative I-V curves; residual voltage specified at 1 kA. '
             '120 kV source / 20 ohm. EMTDC integration and output step: 1 us.', fontsize=9, color='#525B61')
    fig.savefig(destination / 'cumulative_comparison.png', dpi=160, facecolor='white')
    fig.savefig(destination / 'cumulative_comparison.pdf', facecolor='white')
    plt.close(fig)


def main():
    if not __debug__:
        raise RuntimeError('Optimized Python is not supported for this experiment')
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    run = root / 'run'
    run.mkdir()
    os.environ.update(PSCAD_MCP_ACCEPTANCE='1', PSCAD_MCP_ACCEPTANCE_CONCURRENT='1',
        PSCAD_MCP_BACKEND='legacy', PSCAD_MCP_VERSION='4.6.2', PSCAD_MCP_X64='true',
        PSCAD_MCP_WORKSPACE=str(run), PSCAD_MCP_LEGACY_MINIMIZE='true', PSCAD_MCP_LEGACY_EXISTING_POLICY='allow')
    sources = [BASELINE / (name + '.pscx') for name in lifecycle.CASES]
    sources += [BASELINE / 'FiveArresters.pswx', BASELINE / 'analyze_results.py', lifecycle.MASTER, lifecycle.COMPILER]
    report = {'status': 'RUNNING', 'scope': 'Cumulative closure and current redistribution; no exclusivity assumption',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=lifecycle.REPOSITORY, text=True).strip(),
        'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'baseline_hashes': {str(p): lifecycle.sha(p) for p in sources}, 'cases': {}}
    try:
        report['control_changes'] = prepare_models(root)
        report['input_hashes'] = {str(root / (name + '.pscx')): lifecycle.sha(root / (name + '.pscx')) for name in lifecycle.CASES}
        asyncio.run(lifecycle.accept(root, run, report))
        reader = load_analysis()
        reader.ROOT = run
        datasets = {}
        for name, order in lifecycle.CASES.items():
            times, channels = reader.read_case(name)
            report['cases'][name]['observations'] = characterize(times, channels, order)
            datasets[name] = (times, channels)
            with (root / (name + '_channels.csv')).open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['time_s', *channels])
                writer.writerows(zip(times, *channels.values()))
            report['cases'][name]['output_hashes'] = {str(p.relative_to(run)): lifecycle.sha(p)
                for p in (run / (name + '.gf42')).iterdir() if p.suffix in {'.out', '.inf'}}
        plot_comparison(root, datasets)
        if any(lifecycle.sha(Path(p)) != h for p, h in {**report['baseline_hashes'], **report['input_hashes']}.items()):
            raise RuntimeError('An immutable source changed')
        report['status'] = 'PASS'
        report['source_hashes_unchanged'] = True
    except Exception as error:  # noqa: BLE001 - retain all failure evidence at the experiment boundary.
        report['status'] = 'FAIL'
        report['error'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
        traceback.print_exc()
    finally:
        lifecycle.write_report(run, report)
        (root / 'experiment.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'output': str(root),
        'observations': {k: v.get('observations') for k, v in report['cases'].items()},
        'cleanup': report.get('cleanup')}, indent=2), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
