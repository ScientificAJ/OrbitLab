"""Unit tests for scripts/recover_nigraha_norm_stats.py filtering + stats logic.

These verify the script reproduces upstream data/preprocess.py behavior:
duplicate drop, dropna, the [-2,2] skip guard, and pandas std (ddof=1) -- on a
small deterministic synthetic catalog, so it is independent of the network.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "recover_nigraha_norm_stats.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("recover_nigraha_norm_stats", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def _write_catalog(path: Path) -> None:
    # Three TICs; one duplicate row for TIC 1 (should be dropped, keep='first');
    # one row with a NaN stellar value (dropped by dropna in training path).
    df = pd.DataFrame(
        {
            "TIC_ID": [1, 1, 2, 3, 4],
            "Teff": [5000.0, 9999.0, 6000.0, 7000.0, None],
            "Radius": [1.0, 9.9, 1.5, 2.0, 1.2],
            "logg": [4.5, 0.0, 4.0, 3.5, 4.2],
            "Mass": [1.0, 9.9, 1.2, 1.5, 1.1],
            "lum": [1.0, 99.0, 5.0, 20.0, 2.0],
            "rho": [1.0, 99.0, 0.5, 0.1, 0.8],
            "Disposition": ["KP", "KP", "PC", "EB", "PC"],
        }
    )
    df.to_csv(path, index=False)


def test_filtered_population_drops_dupes_and_nans(mod, tmp_path):
    catalog = tmp_path / "synthetic.csv"
    _write_catalog(catalog)
    df = mod._filtered_population(catalog)
    # TIC 1 duplicate removed (keep first), TIC 4 dropped for NaN Teff -> 3 rows.
    assert len(df) == 3
    assert sorted(df.index.tolist()) == [1, 2, 3]
    # The kept TIC-1 row is the first (Teff 5000), not the duplicate (9999).
    assert df.loc[1, "Teff"] == 5000.0


def test_compute_stats_matches_pandas_median_std(mod, tmp_path):
    catalog = tmp_path / "synthetic.csv"
    _write_catalog(catalog)
    out = mod.compute_stats(catalog)
    assert out["population_size"] == 3

    expected = pd.Series([5000.0, 6000.0, 7000.0])
    teff = out["features"]["Teff"]
    assert teff["standardized"] is True
    assert teff["median"] == pytest.approx(expected.median())
    assert teff["std"] == pytest.approx(expected.std())  # ddof=1


def test_skip_guard_leaves_small_range_features_raw(mod, tmp_path):
    # A catalog where rho is already within [-2, 2] for all rows -> upstream skips
    # normalization for it.
    df = pd.DataFrame(
        {
            "TIC_ID": [1, 2, 3],
            "Teff": [5000.0, 6000.0, 7000.0],
            "Radius": [1.0, 1.5, 2.0],
            "logg": [4.5, 4.0, 3.5],
            "Mass": [1.0, 1.2, 1.5],
            "lum": [1.0, 5.0, 20.0],
            "rho": [0.1, 0.5, 1.9],
            "Disposition": ["KP", "PC", "EB"],
        }
    )
    catalog = tmp_path / "skip.csv"
    df.to_csv(catalog, index=False)
    out = mod.compute_stats(catalog)
    assert out["features"]["rho"]["standardized"] is False
    assert out["features"]["rho"]["reason"] == "already_in_[-2,2]"
    assert out["features"]["Teff"]["standardized"] is True
