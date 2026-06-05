#!/usr/bin/env python3
"""Recover the exact upstream Nigraha scalar-feature standardization constants.

Issue #40: the OrbitLab Nigraha numpy reimplementation fed *raw* physical stellar
values into the CNN's dense head, saturating the pre-sigmoid logit so the
probability stopped discriminating between candidates. The released Nigraha CNN
expects its stellar scalar features to be standardized (subtract median, divide by
std) before the dense head (Rao et al. 2021, MNRAS 502, 2845).

There is no saved scaler artifact upstream: ExoplanetML/Nigraha computes the
standardization inline at preprocess time over the catalog population
(`data/preprocess.py`):

    if -2 < tic_catalog[col].min() and tic_catalog[col].max() < 2:
        continue                              # already in [-2,2] -> skip
    tic_catalog[col] = (tic_catalog[col] - tic_catalog[col].median()) \
                       / tic_catalog[col].std()

Only the stellar-catalog columns are standardized; the transit columns are in
`raw_columns` and pass through unchanged. So of OrbitLab's 11 scalar features,
exactly six are standardized: Teff, Radius, logg, Mass, lum, rho. The five transit
features (Depth, Duration, rp_rs, DepthEven, DepthOdd) stay raw -- which is what
OrbitLab already feeds, so they are already correct.

This script reproduces upstream's preprocessing population EXACTLY (same duplicate
drop, same `keys` projection, same `dropna()` for the training `enableImputation=
False` path, same median-fill, same [-2,2] skip guard, pandas std ddof=1) over the
committed upstream training catalog, and writes the per-feature median/std as a
versioned, provenance-stamped artifact for the adapter to consume.

These are the *exact upstream statistics* recomputed from the committed catalog at
the pinned commit -- not a fabricated scaler.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

# Pinned to the same upstream commit as the released weights (see
# scripts/fetch_nigraha_weights.py).
COMMIT = "c4365b41dd02b187c3210189ffe8e3ead584f4f5"
CATALOG_BASE_URL = (
    f"https://raw.githubusercontent.com/ExoplanetML/Nigraha/{COMMIT}/catalog"
)

# Upstream `build_train_data.sh` builds the training TFRecords from two catalogs,
# each self-normalized over its own population. period_info-tces-dl3.csv is the
# broad general-TCE population (the realistic distribution an arbitrary new TESS
# candidate is drawn from); period_info-toi-exofop.csv is the smaller,
# positive-biased TOI list. We default to the dl3 TCE catalog and also record the
# TOI catalog for transparency.
DEFAULT_CATALOG = "period_info-tces-dl3.csv"
REFERENCE_CATALOGS = ("period_info-tces-dl3.csv", "period_info-toi-exofop.csv")

# Verbatim from upstream data/preprocess.py.
KEYS = [
    "T0", "Depth", "Period", "Duration", "TMag", "Teff", "Radius", "NumTransits",
    "snr", "sde", "Mass", "a", "b", "logg", "distance", "lum", "rho", "rp_rs",
    "DepthOdd", "DepthEven", "Disposition", "tdur",
]
RAW_COLUMNS = [
    "T0", "Depth", "Period", "Duration", "TMag", "Disposition", "NumTransits",
    "snr", "sde", "rp_rs", "DepthOdd", "DepthEven", "tdur",
]

# The six OrbitLab scalar features that upstream actually standardizes (KEYS minus
# RAW_COLUMNS, intersected with OrbitLab's stellar features). a, b, distance are in
# KEYS-but-not-raw too, but they are not OrbitLab Nigraha inputs, so we exclude
# them from the emitted artifact.
ORBITLAB_STELLAR_FEATURES = ["Teff", "Radius", "logg", "Mass", "lum", "rho"]


def _fetch(catalog: str, dest: Path) -> Path:
    target = dest / catalog
    if not target.exists():
        url = f"{CATALOG_BASE_URL}/{catalog}"
        with urlopen(url) as response:
            target.write_bytes(response.read())
    return target


def _filtered_population(path: Path) -> pd.DataFrame:
    """Reproduce upstream data/preprocess.py filtering for the training path."""
    df = pd.read_csv(path, index_col="TIC_ID")
    df = df[~df.index.duplicated(keep="first")]
    have = [k for k in KEYS if k in df.columns]
    df = df[have]
    # Training path uses enableImputation=False -> drop any row with NaN.
    df = df.dropna()
    return df


def compute_stats(path: Path) -> dict:
    """Compute per-feature median/std exactly as upstream would for this catalog."""
    df = _filtered_population(path)
    features: dict[str, dict] = {}
    for col in ORBITLAB_STELLAR_FEATURES:
        if col not in df.columns:
            features[col] = {"standardized": False, "reason": "missing_column"}
            continue
        cmin, cmax = float(df[col].min()), float(df[col].max())
        # Upstream [-2,2] skip guard: already-normalized columns are left raw.
        if -2 < cmin and cmax < 2:
            features[col] = {
                "standardized": False,
                "reason": "already_in_[-2,2]",
                "min": cmin,
                "max": cmax,
            }
            continue
        features[col] = {
            "standardized": True,
            "median": float(df[col].median()),
            "std": float(df[col].std()),  # pandas default ddof=1, matches upstream
            "min": cmin,
            "max": cmax,
        }
    return {"population_size": int(len(df)), "features": features}


def build_artifact(dest: Path) -> dict:
    primary = compute_stats(_fetch(DEFAULT_CATALOG, dest))
    reference = {
        cat: compute_stats(_fetch(cat, dest))
        for cat in REFERENCE_CATALOGS
        if cat != DEFAULT_CATALOG
    }
    return {
        "schema_version": "orbitlab.nigraha.norm_stats.v1",
        "provenance": (
            "Per-feature median/std recomputed from the committed upstream "
            "ExoplanetML/Nigraha catalog at the pinned commit, reproducing "
            "data/preprocess.py training-path filtering exactly (duplicate drop, "
            "KEYS projection, dropna for enableImputation=False, [-2,2] skip "
            "guard, pandas std ddof=1). These are the exact upstream statistics, "
            "not a fabricated scaler."
        ),
        "upstream_commit": COMMIT,
        "model_id": "nigraha-tess-global-nodropout-binary-ensemble",
        "catalog_source": DEFAULT_CATALOG,
        "citation": "Rao et al. 2021, MNRAS 502, 2845; ExoplanetML/Nigraha",
        "ddof": 1,
        "raw_columns_left_unstandardized": [
            f for f in ("Depth", "Duration", "rp_rs", "DepthEven", "DepthOdd")
        ],
        "population_size": primary["population_size"],
        "features": primary["features"],
        "reference_catalogs": reference,
        "generated_at": _dt.datetime.now(_dt.UTC).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover exact upstream Nigraha scalar standardization stats."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            ".orbitlab/models/nigraha/norm_stats_global_nodropout_binary.json"
        ),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".orbitlab/cache/nigraha_catalog"),
        help="Where to cache the fetched upstream catalog CSVs.",
    )
    parser.add_argument(
        "--min-population",
        type=int,
        default=500,
        help="Feasibility gate: abort if the filtered population is smaller.",
    )
    args = parser.parse_args()

    args.cache_dir.mkdir(parents=True, exist_ok=True)
    artifact = build_artifact(args.cache_dir)

    pop = artifact["population_size"]
    n_std = sum(1 for f in artifact["features"].values() if f.get("standardized"))
    if pop < args.min_population or n_std == 0:
        print(
            f"FEASIBILITY GATE FAILED: population={pop} "
            f"(min {args.min_population}), standardized_features={n_std}. "
            "Refusing to write fabricated/implausible constants.",
            file=sys.stderr,
        )
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2) + "\n")

    print(f"catalog_source={artifact['catalog_source']}")
    print(f"upstream_commit={COMMIT}")
    print(f"population_size={pop}")
    print(f"standardized_features={n_std}/{len(ORBITLAB_STELLAR_FEATURES)}")
    for name, f in artifact["features"].items():
        if f.get("standardized"):
            print(f"  {name}: median={f['median']:.6g} std={f['std']:.6g}")
        else:
            print(f"  {name}: raw ({f.get('reason')})")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
