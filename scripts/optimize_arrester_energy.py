"""Energy-fair scheduling for n nonlinear surge-arrester branches.

The optimizer is intentionally a static pre-solver.  It uses each arrester's
external I-V curve and the source Thevenin resistance to estimate the average
power in every cumulative active set, then solves a bounded max-min LP for the
stage dwell times.  The resulting schedule must be rerun in licensed PSCAD.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linprog


def load_curve(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rows = []
    terminated = False
    for raw in path.read_text(encoding="ascii").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "ENDFILE:":
            terminated = True
            continue
        line = line.removesuffix("/").strip()
        current, voltage_pu = map(float, line.split())
        rows.append((current, voltage_pu))
    if not terminated or len(rows) < 2:
        raise ValueError(f"Invalid external curve: {path}")
    arr = np.asarray(rows, dtype=float)
    if np.any(np.diff(arr[:, 0]) <= 0) or np.any(np.diff(arr[:, 1]) <= 0):
        raise ValueError("Curve current and voltage must both increase strictly")
    return arr[:, 0], arr[:, 1]


def branch_current(voltage_kv: float, scale_kv: float, current: np.ndarray,
                   voltage_pu: np.ndarray) -> float:
    """Invert V(I) in log-log space; extrapolate flat at the endpoints."""
    if voltage_kv <= 0:
        return 0.0
    v = voltage_kv / scale_kv
    lx = np.log10(current)
    ly = np.log10(voltage_pu)
    return float(10 ** np.interp(np.log10(v), ly, lx))


def equilibrium(active: list[int], scales: list[float], source_kv: float,
                source_r_ohm: float, current: np.ndarray,
                voltage_pu: np.ndarray) -> tuple[float, np.ndarray]:
    """Solve (Vs-Vb)/R=sum(I_i(Vb)) by bisection."""
    def residual(vb: float) -> float:
        return (source_kv - vb) / source_r_ohm - sum(
            branch_current(vb, scales[i], current, voltage_pu) for i in active
        )

    lo, hi = 0.0, source_kv
    for _ in range(160):
        mid = (lo + hi) / 2
        if residual(mid) > 0:
            lo = mid
        else:
            hi = mid
    vb = (lo + hi) / 2
    currents = np.zeros(len(scales))
    for i in active:
        currents[i] = branch_current(vb, scales[i], current, voltage_pu)
    return vb, currents


def optimize(scales: list[float], order: list[int], curve_path: Path,
             source_kv: float, source_r_ohm: float, energy_limit_kj: float,
             design_target_kj: float, total_ms: float,
             observed_powers: np.ndarray | None = None) -> dict:
    current, voltage_pu = load_curve(curve_path)
    n = len(scales)
    if sorted(order) != list(range(n)):
        raise ValueError("order must be a permutation of branch indices 0..n-1")

    # Stage k has branches order[:k+1] connected.  V*kA is MW = kJ/ms.
    powers = np.zeros((n, n))
    equilibria = []
    for k in range(n):
        active = order[: k + 1]
        vb, currents = equilibrium(active, scales, source_kv, source_r_ohm,
                                   current, voltage_pu)
        powers[:, k] = vb * currents
        equilibria.append({
            "stage": k + 1,
            "active_branches": [i + 1 for i in active],
            "bus_voltage_kV": vb,
            "branch_current_kA": currents.tolist(),
            "branch_power_kJ_per_ms": powers[:, k].tolist(),
        })

    if observed_powers is not None:
        if observed_powers.shape != powers.shape or not np.isfinite(observed_powers).all():
            raise ValueError("Observed power matrix has the wrong shape or non-finite values")
        powers = observed_powers

    # Variables are dwell times tau[0:n] and common floor z.
    # Maximize z, with every branch energy in [z, design_target].
    c = np.zeros(n + 1)
    c[-1] = -1.0
    aub, bub = [], []
    for i in range(n):
        row = np.zeros(n + 1)
        row[:n] = -powers[i]
        row[-1] = 1.0        # z <= E_i
        aub.append(row)
        bub.append(0.0)
        row = np.zeros(n + 1)
        row[:n] = powers[i]   # E_i <= design_target
        aub.append(row)
        bub.append(design_target_kj)
    row = np.zeros(n + 1)
    row[:n] = 1.0            # do not exceed the available active window
    aub.append(row)
    bub.append(total_ms)
    result = linprog(c, A_ub=np.asarray(aub), b_ub=np.asarray(bub),
                     bounds=[(0.0, None)] * n + [(0.0, design_target_kj)],
                     method="highs")
    if not result.success:
        raise RuntimeError(f"Energy schedule LP failed: {result.message}")

    dwell = result.x[:n]
    energies = powers @ dwell
    close_times = np.r_[0.0, np.cumsum(dwell[:-1])]
    return {
        "method": "observed_PSCAD_energy_matrix_plus_max_min_LP" if observed_powers is not None else "static_curve_equilibrium_plus_max_min_LP",
        "curve_file": str(curve_path),
        "voltage_scales_kV": scales,
        "order": [i + 1 for i in order],
        "source_kV": source_kv,
        "source_resistance_ohm": source_r_ohm,
        "energy_limit_kJ": energy_limit_kj,
        "design_target_kJ": design_target_kj,
        "available_active_window_ms": total_ms,
        "stage_power_kJ_per_ms": powers.tolist(),
        "equilibria": equilibria,
        "stage_dwell_ms": dwell.tolist(),
        "close_times_ms": close_times.tolist(),
        "predicted_energy_kJ": energies.tolist(),
        "predicted_common_floor_kJ": float(result.x[-1]),
        "predicted_mean_kJ": float(energies.mean()),
        "predicted_cv_percent": float(100 * energies.std() / energies.mean()) if energies.mean() else 0.0,
        "predicted_range_kJ": float(energies.max() - energies.min()),
        "hard_limit_satisfied": bool(np.all(energies <= energy_limit_kj + 1e-8)),
        "note": "Static pre-solver result; validate with licensed PSCAD using the same curve and schedule.",
    }


def observed_power_matrix(csv_path: Path, schedule_path: Path, n: int) -> np.ndarray:
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    dwell_ms = np.asarray(schedule["stage_dwell_ms"], dtype=float)
    if len(dwell_ms) != n:
        raise ValueError("Calibration schedule branch count differs")
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    time_ms = np.asarray([float(row["time_s"]) * 1000 for row in rows])
    energies = np.asarray([[float(row[f"E{i}"]) for row in rows] for i in range(1, n + 1)])
    boundaries = np.r_[0.0, np.cumsum(dwell_ms)]
    powers = np.zeros((n, n))
    for k in range(n):
        start, end = boundaries[k], min(boundaries[k + 1], time_ms[-1])
        if end <= start:
            raise ValueError("Calibration output does not cover every stage")
        for i in range(n):
            delta = np.interp(end, time_ms, energies[i]) - np.interp(start, time_ms, energies[i])
            powers[i, k] = delta / (end - start)
    return powers


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--curve", type=Path, required=True)
    ap.add_argument("--scales-kv", type=float, nargs="+", required=True)
    ap.add_argument("--source-kv", type=float, default=120.0)
    ap.add_argument("--source-r-ohm", type=float, default=20.0)
    ap.add_argument("--limit-kj", type=float, default=1000.0)
    ap.add_argument("--target-kj", type=float, default=900.0)
    ap.add_argument("--total-ms", type=float, default=250.0)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--calibration-csv", type=Path)
    ap.add_argument("--calibration-schedule", type=Path)
    args = ap.parse_args()
    n = len(args.scales_kv)
    if bool(args.calibration_csv) != bool(args.calibration_schedule):
        ap.error("--calibration-csv and --calibration-schedule must be provided together")
    observed = observed_power_matrix(args.calibration_csv, args.calibration_schedule, n) if args.calibration_csv else None
    result = optimize(args.scales_kv, list(range(n)), args.curve,
                      args.source_kv, args.source_r_ohm, args.limit_kj,
                      min(args.target_kj, args.limit_kj), args.total_ms, observed)
    if observed is not None:
        result["calibration_csv"] = str(args.calibration_csv)
        result["calibration_schedule"] = str(args.calibration_schedule)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "stage_dwell_ms", "close_times_ms", "predicted_energy_kJ",
        "predicted_cv_percent", "predicted_range_kJ", "hard_limit_satisfied")
    }, indent=2))


if __name__ == "__main__":
    main()
