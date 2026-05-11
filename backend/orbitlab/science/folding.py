from __future__ import annotations

import numpy as np

from orbitlab.science.data_quality import require_real_array


def phase_fold(time: np.ndarray, flux: np.ndarray, period: float, epoch: float) -> tuple[np.ndarray, np.ndarray]:
    if period <= 0:
        raise ValueError("period must be positive")
    t = require_real_array("time", time)
    f = require_real_array("flux", flux)
    phase = ((t - epoch + 0.5 * period) % period) / period - 0.5
    order = np.argsort(phase)
    return phase[order].astype(np.float32), f[order].astype(np.float32)


def bin_phase_curve(phase: np.ndarray, flux: np.ndarray, bins: int) -> tuple[np.ndarray, np.ndarray]:
    if bins <= 4:
        raise ValueError("bins must be greater than 4")
    p = np.asarray(phase, dtype=np.float32)
    f = np.asarray(flux, dtype=np.float32)
    edges = np.linspace(-0.5, 0.5, bins + 1, dtype=np.float32)
    indices = np.digitize(p, edges) - 1
    centers = (edges[:-1] + edges[1:]) / 2
    values = np.full(bins, np.nan, dtype=np.float32)
    for idx in range(bins):
        in_bin = indices == idx
        if in_bin.any():
            values[idx] = np.nanmedian(f[in_bin])
    finite = np.isfinite(values)
    if finite.any() and not finite.all():
        values[~finite] = np.interp(centers[~finite], centers[finite], values[finite]).astype(np.float32)
    return centers.astype(np.float32), values.astype(np.float32)

