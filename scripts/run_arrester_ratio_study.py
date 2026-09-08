"""Optimize copied arrester models, then verify shortlisted ratios in PSCAD."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import subprocess
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import accept_five_arresters as lifecycle
import arrester_ratio_search as search_model
import numpy as np
import try_cumulative_arresters as cumulative

SOURCE = Path('C:/Users/335/Documents/PSCAD-MCP/five_arresters_cumulative_20260908_final')
LABELS = {'ratio_baseline': 'Baseline', 'ratio_geometric': 'Geometric', 'ratio_optimized': 'Optimized',
          'ratio_integer': '1 kV grid', 'ratio_target95': '95% target', 'ratio_target99': '99% target'}


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def verify_plan(root, report):
    if report.get('status') != 'SEARCHED_NOT_NATIVE_VERIFIED':
        raise RuntimeError('A completed search plan is required')
    if report['search_code_sha256'] != lifecycle.sha(Path(search_model.__file__)):
        raise RuntimeError('Search code changed; retain this plan and run a fresh search')
    for path, expected in report['source_hashes'].items():
        if lifecycle.sha(Path(path)) != expected:
            raise RuntimeError('An original source changed after the search')
    for name, candidate in report['search']['candidates'].items():
        if lifecycle.sha(root / 'models' / (name + '.pscx')) != candidate['model_sha256']:
            raise RuntimeError('Candidate model changed after the search')


def prepare_case(directory, name, residuals):
    tree = ET.parse(SOURCE / 'five_sa_sequential.pscx')
    old_name = tree.getroot().get('name')
    tree.getroot().set('name', name)
    for node in tree.iter():
        for key, value in list(node.attrib.items()):
            if value.startswith(old_name + ':'):
                node.set(key, name + value[len(old_name):])
    arresters = tree.findall('.//User[@defn="master:arrester"]')
    for node in arresters:
        params = {p.get('name'): p for p in node.findall('./paramlist/param')}
        branch = int(params['Name'].get('value')[2:])
        params['VSCAL'].set('value', format(residuals[branch - 1], '.12g'))
    for annotation in tree.findall('.//User[@defn="master:annotation"]'):
        params = {p.get('name'): p for p in annotation.findall('./paramlist/param')}
        label = params['AL1'].get('value')
        if label in {'SA1', 'SA2', 'SA3', 'SA4', 'SA5'}:
            branch = int(label[2:])
            params['AL2'].set('value', f'{residuals[branch - 1]:.3f} kV at 1 kA')
    tree.find('.//Frame/paramlist/param[@name="title"]').set('value', LABELS[name] + ' / cumulative closure')
    tree.find('./paramlist[@name="Settings"]/param[@name="description"]').set(
        'value', 'Ratio study / ' + LABELS[name] + ': previous switches remain closed')
    current_limit = '6.5' if name.startswith('ratio_target') else '3.5'
    for output in tree.findall('.//User[@defn="master:pgb"]'):
        params = {p.get('name'): p for p in output.findall('./paramlist/param')}
        if params['Name'].get('value').startswith('I'):
            params['Max'].set('value', current_limit)
    current_graph = tree.find('.//Frame/Graph')
    graph_id = current_graph.get('id')
    for params in tree.findall(f'.//paramlist[@link="{graph_id}"]'):
        params.find('./param[@name="ymax"]').set('value', current_limit)
    ET.indent(tree, space='  ')
    path = directory / (name + '.pscx')
    tree.write(path, encoding='utf-8', xml_declaration=True)
    return path


def prepare(root, report):
    model = search_model.StaticNetwork.from_pscx(SOURCE / 'five_sa_sequential.pscx')
    calibration = search_model.calibrate(model, SOURCE / 'experiment.json')
    print('CALIBRATION', calibration, flush=True)
    report['calibration'] = calibration
    save(root / 'search.json', report)
    results = search_model.search(model)
    report['search'] = results
    cases = root / 'models'
    cases.mkdir()
    for name, candidate in results['candidates'].items():
        path = prepare_case(cases, name, candidate['residual_kv'])
        candidate['model_sha256'] = lifecycle.sha(path)
    workspace = ET.parse(SOURCE / 'CumulativeArresters.pswx')
    workspace.getroot().set('name', 'ArresterRatioStudy')
    projects = workspace.find('./projects')
    projects.clear()
    projects.set('path', '.')
    for name in results['candidates']:
        ET.SubElement(projects, 'project', {'name': name, 'filepath': name + '.pscx'})
    workspace.write(cases / 'ArresterRatioStudy.pswx', encoding='utf-8', xml_declaration=True)
    save(root / 'search.json', report)
    print('CANDIDATES', {name: {'kV': c['residual_kv'], 'worst_share_pct': 100 * c['minimum_new_share']}
                         for name, c in results['candidates'].items()}, flush=True)


def plot_summary(root, candidates, measured):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    names = list(candidates)
    fixed = names[:4]
    colors = {'ratio_baseline': '#59646D', 'ratio_geometric': '#BD7640', 'ratio_optimized': '#176B91',
              'ratio_integer': '#758B31', 'ratio_target95': '#BB527C', 'ratio_target99': '#5C4B90'}
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8))
    fig.subplots_adjust(left=.06, right=.985, bottom=.23, top=.80, wspace=.3)
    for name in fixed:
        axes[0].plot(range(1, 6), candidates[name]['residual_kv'], '-o', color=colors[name], ms=4, label=LABELS[name])
        shares = [s['new_branch_share_pct'] for s in measured[name]['observations']['stages'][1:]]
        axes[1].plot(range(2, 6), shares, '-o', color=colors[name], ms=4, label=LABELS[name])
    axes[0].set(title='Fixed 100-60 kV span', xlabel='Arrester stage', ylabel='Residual at 1 kA (kV)', xticks=range(1, 6))
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].set(title='Measured new-branch share', xlabel='Arrester stage', ylabel='Share (%)', xticks=range(2, 6))
    axes[1].legend(frameon=False, fontsize=8)
    for name in names:
        row = measured[name]['metrics']
        axes[2].scatter(row['maximum_source_current_kA'], row['minimum_new_share_pct'], s=40, color=colors[name])
        label_position = {'ratio_baseline': (3.00, 82.5), 'ratio_geometric': (3.00, 85.0),
                          'ratio_optimized': (3.00, 89.0), 'ratio_integer': (3.00, 87.0),
                          'ratio_target95': (3.35, 96.5), 'ratio_target99': (4.02, 100.0)}[name]
        axes[2].annotate(LABELS[name], (row['maximum_source_current_kA'], row['minimum_new_share_pct']),
                         xytext=label_position, textcoords='data', fontsize=8, color=colors[name],
                         arrowprops={'arrowstyle': '-', 'color': colors[name], 'lw': .6})
    axes[2].set(title='Concentration versus source current', xlabel='Maximum source current (kA)', ylabel='Worst-stage share (%)')
    axes[2].set(xlim=(2.6, 4.7), ylim=(80, 102))
    for ax in axes:
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(color='#E0E4E6', linewidth=.6)
        ax.set_axisbelow(True)
    fig.suptitle('Arrester residual-voltage ratio optimization', fontsize=17, y=.97)
    fig.text(.06, .07, 'Native PSCAD verification | same I-V table, 120 kV / 20 ohm source, cumulative closure\n'
             '95% and 99% cases expand the voltage span; they are tradeoff examples, not equipment ratings.',
             fontsize=9, color='#525B61')
    fig.savefig(root / 'optimization_comparison.png', dpi=170, facecolor='white')
    fig.savefig(root / 'optimization_comparison.pdf', facecolor='white')
    plt.close(fig)


def simulate(root, search_report):
    candidates = search_report['search']['candidates']
    cases = root / 'models'
    run = root / 'runs' / datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')
    run.mkdir(parents=True, exist_ok=False)
    os.environ.update(PSCAD_MCP_ACCEPTANCE='1', PSCAD_MCP_ACCEPTANCE_CONCURRENT='1',
        PSCAD_MCP_BACKEND='legacy', PSCAD_MCP_VERSION='4.6.2', PSCAD_MCP_X64='true',
        PSCAD_MCP_WORKSPACE=str(run), PSCAD_MCP_LEGACY_MINIMIZE='true', PSCAD_MCP_LEGACY_EXISTING_POLICY='allow')
    lifecycle.CASES = {name: [1, 2, 3, 4, 5] for name in candidates}
    report = {'status': 'RUNNING', 'scope': 'Current-share optimization in copied cumulative-close models',
              'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=lifecycle.REPOSITORY, text=True).strip(),
              'runner_sha256': lifecycle.sha(Path(__file__)), 'search_report_sha256': lifecycle.sha(root / 'search.json'),
              'model_hashes': {str(cases / (name + '.pscx')): lifecycle.sha(cases / (name + '.pscx')) for name in candidates},
              'source_hashes': search_report['source_hashes'], 'search_code_sha256': search_report['search_code_sha256'], 'cases': {}}
    try:
        verify_plan(root, search_report)
        asyncio.run(lifecycle.accept(cases, run, report))
        reader = cumulative.load_analysis()
        reader.ROOT = run
        model = search_model.StaticNetwork.from_pscx(SOURCE / 'five_sa_sequential.pscx')
        for name, candidate in candidates.items():
            times, channels = reader.read_case(name)
            observed = cumulative.characterize(times, channels, [1, 2, 3, 4, 5])
            predicted = model.stages(candidate['residual_kv'])
            current_error = max(float(np.max(np.abs(np.array(p['currents_ka']) * 1000 - s['mean_currents_A'])))
                                for p, s in zip(predicted, observed['stages']))
            voltage_error = max(abs(p['bus_kv'] - s['mean_bus_kV']) for p, s in zip(predicted, observed['stages']))
            if current_error > .01 or voltage_error > 1e-5:
                raise RuntimeError(f'Search prediction differs from PSCAD for {name}')
            metrics = {'minimum_new_share_pct': min(s['new_branch_share_pct'] for s in observed['stages'][1:]),
                       'maximum_source_current_kA': float(channels['ISOURCE'].max()),
                       'minimum_steady_bus_kV': min(s['mean_bus_kV'] for s in observed['stages']),
                       'total_arrester_energy_kJ': float(sum(channels[f'E{i}'][-1] for i in range(1, 6))),
                       'maximum_prediction_error_A': current_error, 'maximum_voltage_prediction_error_kV': voltage_error}
            required = {'ratio_target95': 95, 'ratio_target99': 99}.get(name)
            if required and metrics['minimum_new_share_pct'] < required:
                raise RuntimeError(f'{name} did not meet its concentration target')
            report['cases'][name].update(observations=observed, metrics=metrics)
            report['cases'][name]['output_hashes'] = {str(p.relative_to(run)): lifecycle.sha(p)
                for p in (run / (name + '.gf42')).iterdir() if p.suffix in {'.out', '.inf'}}
            with (root / (name + '_channels.csv')).open('w', newline='', encoding='utf-8-sig') as stream:
                writer = csv.writer(stream)
                writer.writerow(['time_s', *channels])
                writer.writerows(zip(times, *channels.values()))
            print('VERIFIED', name, metrics, flush=True)
        baseline = report['cases']['ratio_baseline']['metrics']['minimum_new_share_pct']
        if report['cases']['ratio_optimized']['metrics']['minimum_new_share_pct'] <= baseline:
            raise RuntimeError('The proposed fixed-span optimum did not improve the baseline')
        for path, expected in {**report['source_hashes'], **report['model_hashes']}.items():
            if lifecycle.sha(Path(path)) != expected:
                raise RuntimeError('An original input or prepared model changed')
        plot_summary(root, candidates, report['cases'])
        report['source_hashes_unchanged'] = True
        report['status'] = 'PASS'
    except Exception as error:  # noqa: BLE001 - preserve unsuccessful attempts for diagnosis.
        report['status'] = 'FAIL'
        report['error'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
        traceback.print_exc()
    finally:
        lifecycle.write_report(run, report)
        save(root / 'validation.json', report)
    print(json.dumps({'status': report['status'], 'run': str(run), 'cleanup': report.get('cleanup')}, indent=2), flush=True)
    return report['status'] == 'PASS'


def main():
    if not __debug__:
        raise RuntimeError('Optimized Python is not supported for this study')
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['search', 'simulate'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if args.mode == 'search':
        root.mkdir(parents=True, exist_ok=False)
        sources = [SOURCE / 'five_sa_sequential.pscx', SOURCE / 'experiment.json', SOURCE / 'CumulativeArresters.pswx',
                   lifecycle.MASTER, lifecycle.COMPILER, cumulative.BASELINE / 'analyze_results.py']
        report = {'status': 'SEARCHING', 'source': str(SOURCE),
                  'source_hashes': {str(p): lifecycle.sha(p) for p in sources},
                  'search_code_sha256': lifecycle.sha(Path(search_model.__file__))}
        prepare(root, report)
        report['status'] = 'SEARCHED_NOT_NATIVE_VERIFIED'
        save(root / 'search.json', report)
        return 0
    return 0 if simulate(root, json.loads((root / 'search.json').read_text(encoding='utf-8'))) else 1


if __name__ == '__main__':
    raise SystemExit(main())
