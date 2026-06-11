"""Mission PRF kernels for point-source fitting (Phase 1B).

TESS: the SPOC pixel response function is published as a 5x5 grid of
oversampled FITS images per camera/CCD (two epochs: sectors 1-3 and 4+) at
the MAST models archive. The nearest grid file to the target's absolute CCD
position is fetched once, cached under the calibration directory with a
checksum (same pattern as the TRILEGAL cache), and turned into an
interpolating kernel for `fit_point_source`.

Kepler: lightkurve's `KeplerPRF` evaluates the mission calibration product
for a channel/cutout; it is adapted to the same kernel signature.

Everything degrades gracefully: no network, no astropy, an unexpected file
layout, or missing mission metadata simply returns None and the caller keeps
the analytic Gaussian kernel with honest `centroid_method` provenance.
"""

from __future__ import annotations

import hashlib
import re
import urllib.request
from pathlib import Path

import numpy as np

from orbitlab.config import settings

_TESS_PRF_BASE = "https://archive.stsci.edu/missions/tess/models/prf_fitsfiles"
# Grid positions are absolute CCD coordinates (from the archive listings).
_TESS_GRID_ROWS = (1, 513, 1025, 1536, 2048)
_TESS_GRID_COLS = (45, 557, 1069, 1580, 2092)
_TESS_NATIVE_SIZE = 13  # PRF images cover 13x13 detector pixels, oversampled
_FETCH_TIMEOUT_SECONDS = 60.0


def _calibration_dir() -> Path:
    return settings.calibration_dir


def _epoch_directory(sector: int | None) -> str:
    return "start_s0001" if sector is not None and sector <= 3 else "start_s0004"


def _nearest(grid: tuple[int, ...], value: float) -> int:
    return min(grid, key=lambda g: abs(g - value))


def _cached_fetch(url: str, cache_name: str) -> Path | None:
    cache_path = _calibration_dir() / "prf" / "tess" / cache_name
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_SECONDS) as response:
            payload = response.read()
        cache_path.write_bytes(payload)
        (cache_path.with_suffix(cache_path.suffix + ".sha256")).write_text(
            hashlib.sha256(payload).hexdigest(), encoding="utf-8"
        )
        return cache_path
    except Exception:
        return None


def _tess_prf_file(camera: int, ccd: int, sector: int | None, ccd_row: float, ccd_col: float) -> Path | None:
    epoch = _epoch_directory(sector)
    directory = f"{_TESS_PRF_BASE}/{epoch}/cam{camera}_ccd{ccd}/"
    row = _nearest(_TESS_GRID_ROWS, ccd_row)
    col = _nearest(_TESS_GRID_COLS, ccd_col)
    # The filename prefix is an epoch timestamp that differs per directory;
    # resolve it from the directory listing instead of hardcoding it.
    listing_cache = _calibration_dir() / "prf" / "tess" / f"listing_{epoch}_cam{camera}_ccd{ccd}.html"
    listing = None
    if listing_cache.exists():
        listing = listing_cache.read_text(encoding="utf-8", errors="replace")
    else:
        try:
            with urllib.request.urlopen(directory, timeout=_FETCH_TIMEOUT_SECONDS) as response:
                listing = response.read().decode("utf-8", errors="replace")
            listing_cache.parent.mkdir(parents=True, exist_ok=True)
            listing_cache.write_text(listing, encoding="utf-8")
        except Exception:
            return None
    pattern = rf"(tess\d+-prf-{camera}-{ccd}-row{row:04d}-col{col:04d}\.fits)"
    match = re.search(pattern, listing)
    if not match:
        return None
    filename = match.group(1)
    return _cached_fetch(directory + filename, filename)


def _kernel_from_oversampled(prf_image: np.ndarray, oversample: int):
    """Build kernel(rows, cols, r0, c0) sampling an oversampled PRF image.

    The PRF array center corresponds to the source position; pixel offsets
    are scaled by the oversampling factor and sampled bilinearly. Output is
    normalized to peak 1 so the fit's amplitude parameter stays meaningful.
    """
    image = np.asarray(prf_image, dtype=np.float64)
    peak = float(np.nanmax(image))
    if not np.isfinite(peak) or peak <= 0:
        return None
    image = np.nan_to_num(image / peak, nan=0.0)
    center_r = (image.shape[0] - 1) / 2.0
    center_c = (image.shape[1] - 1) / 2.0

    def kernel(rows: np.ndarray, cols: np.ndarray, r0: float, c0: float) -> np.ndarray:
        sample_r = (np.asarray(rows, dtype=np.float64) - r0) * oversample + center_r
        sample_c = (np.asarray(cols, dtype=np.float64) - c0) * oversample + center_c
        r_floor = np.floor(sample_r).astype(int)
        c_floor = np.floor(sample_c).astype(int)
        fr = sample_r - r_floor
        fc = sample_c - c_floor
        values = np.zeros(sample_r.shape, dtype=np.float64)
        for dr, dc, weight in (
            (0, 0, (1 - fr) * (1 - fc)),
            (0, 1, (1 - fr) * fc),
            (1, 0, fr * (1 - fc)),
            (1, 1, fr * fc),
        ):
            rr = r_floor + dr
            cc = c_floor + dc
            inside = (rr >= 0) & (rr < image.shape[0]) & (cc >= 0) & (cc < image.shape[1])
            values[inside] += weight[inside] * image[rr[inside], cc[inside]]
        return values

    return kernel


def load_tess_prf_kernel(
    *,
    camera: int | None,
    ccd: int | None,
    sector: int | None,
    ccd_row: float | None,
    ccd_col: float | None,
):
    """Fetch (or replay from cache) the nearest TESS PRF and return a kernel."""
    if not camera or not ccd or ccd_row is None or ccd_col is None:
        return None
    path = _tess_prf_file(int(camera), int(ccd), sector, float(ccd_row), float(ccd_col))
    if path is None:
        return None
    try:
        from astropy.io import fits

        with fits.open(path) as hdul:
            data = next((hdu.data for hdu in hdul if getattr(hdu, "data", None) is not None), None)
        if data is None or np.ndim(data) != 2:
            return None
        oversample = max(int(round(data.shape[0] / _TESS_NATIVE_SIZE)), 1)
        return _kernel_from_oversampled(np.asarray(data), oversample)
    except Exception:
        return None


def load_kepler_prf_kernel(
    *,
    channel: int | None,
    shape: tuple[int, int],
    corner_column: float | None,
    corner_row: float | None,
):
    """Adapt lightkurve's KeplerPRF calibration product to the kernel signature."""
    if not channel or corner_column is None or corner_row is None:
        return None
    try:
        from lightkurve.prf import KeplerPRF

        prf = KeplerPRF(channel=int(channel), shape=shape, column=int(corner_column), row=int(corner_row))
    except Exception:
        return None

    def kernel(rows: np.ndarray, cols: np.ndarray, r0: float, c0: float) -> np.ndarray:
        try:
            image = np.asarray(
                prf(float(c0) + float(corner_column), float(r0) + float(corner_row), 1.0, 1.0, 1.0, 0.0),
                dtype=np.float64,
            )
        except Exception:
            return np.zeros(np.asarray(rows).shape, dtype=np.float64)
        peak = float(np.nanmax(image))
        if not np.isfinite(peak) or peak <= 0:
            return np.zeros(np.asarray(rows).shape, dtype=np.float64)
        image = np.nan_to_num(image / peak, nan=0.0)
        r_idx = np.clip(np.round(np.asarray(rows)).astype(int), 0, image.shape[0] - 1)
        c_idx = np.clip(np.round(np.asarray(cols)).astype(int), 0, image.shape[1] - 1)
        return image[r_idx, c_idx]

    return kernel
