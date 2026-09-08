"""Search voltage scales using a calibrated static equivalent of the PSCAD table."""

from __future__ import annotations

import itertools
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.optimize import brentq, differential_evolution, minimize


@dataclass(frozen=True)
class StaticNetwork:
    current_ka: np.ndarray
    voltage_pu: np.ndarray
    source_kv: float
    source_ohm: float
    on_ohm: float
    off_ohm: float

    def __post_init__(self):
        if (len(self.current_ka) != len(self.voltage_pu) or self.current_ka[0] != 0
                or self.voltage_pu[0] != 0 or not np.all(np.diff(self.current_ka) > 0)
                or not np.all(np.diff(self.voltage_pu) > 0)):
            raise ValueError('I-V coordinates must increase strictly from the origin')
        if not all(np.isfinite(v).all() for v in (self.current_ka, self.voltage_pu)):
            raise ValueError('Finite curve coordinates are required')
        if self.source_kv <= 0 or self.source_ohm <= 0 or self.on_ohm < 0 or self.off_ohm <= self.on_ohm:
            raise ValueError('Invalid source or switch parameters')
        if self.source_kv / self.source_ohm > self.current_ka[-1]:
            raise ValueError('Possible source current exceeds the tabulated I-V domain')

    @classmethod
    def from_pscx(cls, path: Path):
        root = ET.parse(path).getroot()

        def parameters(component):
            return {p.get('name'): p.get('value') for p in component.findall('./paramlist/param')}

        arresters = [parameters(c) for c in root.findall('.//User[@defn="master:arrester"]')]
        breakers = [parameters(c) for c in root.findall('.//User[@defn="master:breaker1"]')]
        sources = [parameters(c) for c in root.findall('.//User[@defn="master:source1"]')]
        if len(arresters) != 5 or len(breakers) != 5 or len(sources) != 1:
            raise ValueError('Expected five arrester branches and one source')
        if any(c['Cnfg'] != '1' or float(c['ISCAL']) != 1 or c['ENAB'] != '1' for c in arresters):
            raise ValueError('Expected enabled, single-stack, user-table arresters')
        curves = [(np.array([0, *[float(c[f'X{i}']) for i in range(1, 12)]]),
                   np.array([0, *[float(c[f'Y{i}']) for i in range(1, 12)]])) for c in arresters]
        if any(not np.array_equal(curves[0][0], x) or not np.array_equal(curves[0][1], y) for x, y in curves):
            raise ValueError('This study requires the same normalized I-V table for all branches')
        source = sources[0]
        if source['ACDC'] != '1' or source['Type'] != '1' or source['Ctrl'] != '0':
            raise ValueError('Expected the original internal DC source with resistive impedance')
        on, off = float(breakers[0]['RON']), float(breakers[0]['ROFF'])
        if any(float(c['RON']) != on or float(c['ROFF']) != off for c in breakers):
            raise ValueError('Expected identical series switches')
        return cls(curves[0][0], curves[0][1], float(source['Esd']), float(source['R1s']), on, off)

    def stage(self, residuals, closed_count):
        values = np.asarray(residuals, dtype=float)
        if values.shape != (5,) or not np.isfinite(values).all() or np.any(values <= 0):
            raise ValueError('Five finite positive residual-voltage scales are required')
        if closed_count not in range(1, 6):
            raise ValueError('The number of closed branches must be 1-5')
        resistance = np.where(np.arange(5) < closed_count, self.on_ohm, self.off_ohm)
        knots = values[:, None] * self.voltage_pu + resistance[:, None] * self.current_ka

        def currents(bus):
            return np.array([np.interp(bus, row, self.current_ka) for row in knots])

        def balance(bus):
            return float(currents(bus).sum()) - (self.source_kv - bus) / self.source_ohm

        bus = brentq(balance, 0, self.source_kv, xtol=1e-11, rtol=1e-14)
        amps = currents(bus)
        total = float(amps.sum())
        return {'bus_kv': bus, 'currents_ka': amps.tolist(), 'total_ka': total,
                'new_share': float(amps[closed_count - 1] / total),
                'new_power_MW': float((bus - self.on_ohm * amps[closed_count - 1]) * amps[closed_count - 1])}

    def stages(self, residuals):
        return [self.stage(residuals, count) for count in range(1, 6)]

    def score(self, residuals):
        return min(self.stage(residuals, count)['new_share'] for count in range(2, 6))


def calibrate(network, report_path):
    observed = json.loads(Path(report_path).read_text(encoding='utf-8'))
    stages = observed['cases']['five_sa_sequential']['observations']['stages']
    predicted = network.stages([100, 90, 80, 70, 60])
    max_current_error_A = max(float(np.max(np.abs(np.array(p['currents_ka']) * 1000 - o['mean_currents_A'])))
                              for p, o in zip(predicted, stages))
    max_voltage_error_kv = max(abs(p['bus_kv'] - o['mean_bus_kV']) for p, o in zip(predicted, stages))
    if max_current_error_A > .01 or max_voltage_error_kv > 1e-5:
        raise RuntimeError('Static model does not match native PSCAD baseline evidence')
    return {'status': 'PASS', 'max_current_error_A': max_current_error_A,
            'max_voltage_error_kV': max_voltage_error_kv, 'reference': str(report_path)}


def optimize_fixed_span(network):
    runs = []
    best_values, best_score = None, -1.0
    for seed in (11, 23, 37):
        def objective(middle):
            return -network.score([100, *sorted(middle, reverse=True), 60])

        result = differential_evolution(objective, [(60, 100)] * 3, seed=seed,
                                        maxiter=140, popsize=10, tol=1e-8, polish=False)
        values = [100, *sorted(result.x, reverse=True), 60]

        def constraints(z):
            shares = [network.stage([100, *z[:3], 60], k)['new_share'] - z[3] for k in range(2, 6)]
            return [100 - z[0], z[0] - z[1], z[1] - z[2], z[2] - 60, *shares]

        refined = minimize(lambda z: -z[3], [*values[1:4], network.score(values)], method='SLSQP',
                           bounds=[(60, 100)] * 3 + [(0, 1)], constraints={'type': 'ineq', 'fun': constraints},
                           options={'ftol': 1e-12, 'maxiter': 250})
        if refined.success and min(constraints(refined.x)) > -1e-8:
            proposed = [100, *refined.x[:3], 60]
            if network.score(proposed) >= network.score(values):
                values = proposed
        score = network.score(values)
        runs.append({'seed': seed, 'de_success': bool(result.success), 'de_evaluations': int(result.nfev),
                     'refinement_success': bool(refined.success), 'residual_kv': list(map(float, values)),
                     'minimum_new_share': score})
        print('SEARCH', seed, score, list(map(float, values)), flush=True)
        if score > best_score:
            best_values, best_score = values, score
    return list(map(float, best_values)), runs


def integer_grid_search(network, continuous):
    best = [100, *[float(round(v)) for v in continuous[1:4]], 60]
    best_score = network.score(best)
    count = 0
    for ascending in itertools.combinations(range(61, 100), 3):
        values = [100, *reversed(ascending), 60]
        score = 1.0
        for stage in range(2, 6):
            score = min(score, network.stage(values, stage)['new_share'])
            if score < best_score:
                break
        count += 1
        if score > best_score:
            best, best_score = values, score
        if count % 3000 == 0:
            print('INTEGER GRID', count, best_score, best, flush=True)
    return list(map(float, best)), {'combinations': count, 'step_kV': 1, 'minimum_new_share': best_score}


def least_span_target(network, target):
    design_target = target + .0001
    values = [100.0]
    for count in range(2, 6):
        def residual(candidate, count=count):
            scales = [*values, candidate, *([5.0] * (5 - count))]
            return network.stage(scales, count)['new_share'] - design_target

        values.append(brentq(residual, 5, values[-1], xtol=1e-9))

    def constraints(z):
        scales = [100, *z]
        return [100 - z[0], z[0] - z[1], z[1] - z[2], z[2] - z[3],
                *[network.stage(scales, k)['new_share'] - design_target for k in range(2, 6)]]

    result = minimize(lambda z: -z[3], values[1:], method='SLSQP', bounds=[(5, 100)] * 4,
                      constraints={'type': 'ineq', 'fun': constraints}, options={'ftol': 1e-11, 'maxiter': 300})
    if result.success and min(constraints(result.x)) > -1e-8:
        values = [100, *result.x]
    if network.score(values) < target:
        raise RuntimeError('Requested concentration target is not feasible within the search bounds')
    return list(map(float, values)), {'target': target, 'design_target': design_target,
                                     'success': bool(result.success), 'minimum_scale_kV': 5}


def search(network):
    optimized, attempts = optimize_fixed_span(network)
    rounded, integer_evidence = integer_grid_search(network, optimized)
    target95, evidence95 = least_span_target(network, .95)
    target99, evidence99 = least_span_target(network, .99)
    candidates = {
        'ratio_baseline': [100, 90, 80, 70, 60],
        'ratio_geometric': (100 * .6 ** (np.arange(5) / 4)).tolist(),
        'ratio_optimized': optimized,
        'ratio_integer': rounded,
        'ratio_target95': target95,
        'ratio_target99': target99,
    }
    return {'objective': 'Maximize the minimum new-branch share in stages 2-5',
            'primary_constraints': {'first_kV': 100, 'last_kV': 60, 'descending': True},
            'continuous_global_optimum_proven': False, 'search_runs': attempts,
            'integer_grid': integer_evidence, 'expanded_span': {'95pct': evidence95, '99pct': evidence99},
            'candidates': {name: {'residual_kv': values, 'relative_to_first': [v / values[0] for v in values],
                'adjacent_ratios': [values[i + 1] / values[i] for i in range(4)],
                'stages': network.stages(values), 'minimum_new_share': network.score(values)}
                for name, values in candidates.items()}}
