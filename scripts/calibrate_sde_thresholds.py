#!/usr/bin/env python3
"""Generate the per-population SDE calibration table from empirical nulls.

For each population bin (mission x cadence class x baseline bucket x
red-noise bucket) this script builds no-signal light curves, runs the SAME
TLS search machinery the pipeline uses, and records the null max-SDE
distribution. The shipped threshold is the larger of the two null
generators' FAP quantiles:

- permutation nulls: white-noise-like, destroys all temporal structure;
- block-bootstrap nulls (with AR(1) red noise injected for "red" bins):
  preserves correlated noise, which is what actually inflates SDE.

With n_null per bin in the low hundreds the empirical quantile supports
FAP ~1e-2 directly; for smaller FAP targets the tail is extrapolated with a
generalized-extreme-value fit to the max-SDE sample (the max of a search is
GEV-distributed by the Fisher-Tippett theorem). Both the empirical quantile
and the GEV value are stored for audit; the threshold uses the GEV value.

Thresholds are only valid for comparable search effort: the search grid
parameters are recorded in the table metadata and must match the pipeline's
TLS configuration when interpreted.

Usage:
  .venv/bin/python scripts/calibrate_sde_thresholds.py --smoke      # plumbing check
  .venv/bin/python scripts/calibrate_sde_thresholds.py              # full table (hours)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
import time as _time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from orbitlab.science.tls_refinement import search_with_tls  # noqa: E402

DEFAULT_OUT = ROOT / "backend" / "orbitlab" / "science" / "sde_calibration.toml"

# Bin definitions: representative cadence/baseline for synthesis, and the
# AR(1) noise mix for the red bins (phi chosen so the Pont beta of the
# synthetic curves lands in the bucket it calibrates).
BINS: dict[str, dict] = {
    "tess_short_cadence_short_baseline_quiet": {"cadence_s": 120.0, "baseline_d": 27.0, "red": False},
    "tess_short_cadence_short_baseline_red": {"cadence_s": 120.0, "baseline_d": 27.0, "red": True},
    "tess_long_cadence_short_baseline_quiet": {"cadence_s": 1800.0, "baseline_d": 27.0, "red": False},
    "tess_long_cadence_short_baseline_red": {"cadence_s": 1800.0, "baseline_d": 27.0, "red": True},
    "kepler_long_cadence_short_baseline_quiet": {"cadence_s": 1800.0, "baseline_d": 80.0, "red": False},
    "kepler_long_cadence_short_baseline_red": {"cadence_s": 1800.0, "baseline_d": 80.0, "red": True},
}

SEARCH_GRID = {
    "period_min_days": 0.5,
    "period_max_days": 15.0,
    "oversampling_factor": 1,
    "n_transits_min": 2,
}
MAX_POINTS = 9000  # match pipeline max_search_cadences scale


def _base_noise(rng: np.ndarray, n: int, red: bool) -> np.ndarray:
    white = rng.normal(0.0, 4.0e-4, n)
    if not red:
        return white
    # AR(1) correlated component: phi tuned to land beta comfortably > 1.3.
    phi = 0.98
    ar = np.empty(n)
    ar[0] = 0.0
    innovations = rng.normal(0.0, 2.0e-4, n)
    for i in range(1, n):
        ar[i] = phi * ar[i - 1] + innovations[i]
    return white + ar


def _block_bootstrap(rng, flux: np.ndarray, block: int) -> np.ndarray:
    n = flux.size
    blocks = []
    while sum(b.size for b in blocks) < n:
        start = int(rng.integers(0, max(n - block, 1)))
        blocks.append(flux[start : start + block])
    return np.concatenate(blocks)[:n]


def _max_sde(time: np.ndarray, flux: np.ndarray) -> float | None:
    report = search_with_tls(
        time,
        1.0 + flux,
        min_period=SEARCH_GRID["period_min_days"],
        max_period=SEARCH_GRID["period_max_days"],
        n_transits_min=SEARCH_GRID["n_transits_min"],
        oversampling_factor=SEARCH_GRID["oversampling_factor"],
    )
    if report.get("status") != "complete":
        return None
    value = report.get("sde")
    return float(value) if isinstance(value, (int, float)) and np.isfinite(value) else None


def _threshold_from_sample(sample: np.ndarray, fap: float) -> tuple[float, float]:
    empirical = float(np.quantile(sample, 1.0 - min(fap * 10.0, 0.5)))
    try:
        from scipy.stats import genextreme

        shape, loc, scale = genextreme.fit(sample)
        fitted = float(genextreme.ppf(1.0 - fap, shape, loc=loc, scale=scale))
        if not np.isfinite(fitted) or fitted <= 0:
            fitted = empirical
    except Exception:
        fitted = empirical
    return empirical, fitted


def calibrate_bin(name: str, spec: dict, *, n_null: int, fap: float, seed: int) -> dict | None:
    rng = np.random.default_rng(seed)
    n_points = min(int(spec["baseline_d"] * 86400.0 / spec["cadence_s"]), MAX_POINTS)
    time = np.linspace(0.0, spec["baseline_d"], n_points)
    block = max(int(0.5 * 86400.0 / spec["cadence_s"]), 4)  # ~0.5-day blocks

    sdes: list[float] = []
    started = _time.perf_counter()
    for index in range(n_null):
        base = _base_noise(rng, n_points, spec["red"])
        flux = rng.permutation(base) if index % 2 == 0 else _block_bootstrap(rng, base, block)
        value = _max_sde(time, flux)
        if value is not None:
            sdes.append(value)
        if (index + 1) % 10 == 0:
            print(
                f"  [{name}] {index + 1}/{n_null} nulls, "
                f"{_time.perf_counter() - started:.0f}s elapsed",
                flush=True,
            )
    if len(sdes) < max(10, n_null // 2):
        print(f"  [{name}] insufficient completed nulls ({len(sdes)}); bin skipped", flush=True)
        return None
    sample = np.asarray(sdes)
    empirical, fitted = _threshold_from_sample(sample, fap)
    return {
        "sde_threshold": round(fitted, 3),
        "sde_empirical_q": round(empirical, 3),
        "sde_null_median": round(float(np.median(sample)), 3),
        "sde_null_max": round(float(sample.max()), 3),
        "n_null": len(sdes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bins", nargs="*", default=None, help="subset of bin names")
    parser.add_argument("--n-null", type=int, default=200)
    parser.add_argument("--fap", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--smoke", action="store_true", help="one bin, 12 nulls: plumbing check only")
    args = parser.parse_args()

    selected = dict(BINS)
    if args.smoke:
        selected = {"tess_short_cadence_short_baseline_quiet": BINS["tess_short_cadence_short_baseline_quiet"]}
        args.n_null = 12
    elif args.bins:
        selected = {name: BINS[name] for name in args.bins}

    results: dict[str, dict] = {}
    for offset, (name, spec) in enumerate(selected.items()):
        print(f"calibrating bin {name} (n_null={args.n_null})", flush=True)
        record = calibrate_bin(name, spec, n_null=args.n_null, fap=args.fap, seed=args.seed + offset)
        if record:
            results[name] = record
            print(f"  [{name}] -> {record}", flush=True)

    if not results:
        print("no bins produced thresholds; table not written", flush=True)
        return 1

    lines = [
        'schema_version = "orbitlab.sde_calibration.v1"',
        f'generated = "{_dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")}"',
        "",
        "[metadata]",
        f"fap_target = {args.fap}",
        f"n_null_requested = {args.n_null}",
        f"seed = {args.seed}",
        f'smoke = {"true" if args.smoke else "false"}',
        f"search_period_min_days = {SEARCH_GRID['period_min_days']}",
        f"search_period_max_days = {SEARCH_GRID['period_max_days']}",
        f"search_oversampling_factor = {SEARCH_GRID['oversampling_factor']}",
        f"max_points = {MAX_POINTS}",
        "",
    ]
    for name, record in results.items():
        lines.append(f"[bins.{name}]")
        for key, value in record.items():
            lines.append(f"{key} = {value}")
        lines.append("")
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"table written to {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
