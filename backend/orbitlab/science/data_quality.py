from __future__ import annotations

import numpy as np

from orbitlab.exceptions import RealDataRequiredError


def require_real_array(name: str, values: np.ndarray, *, min_size: int = 8) -> np.ndarray:
    arr = np.asarray(values)
    if arr.size < min_size:
        raise RealDataRequiredError(f"{name} must contain real fetched data")
    if not np.issubdtype(arr.dtype, np.number):
        raise RealDataRequiredError(f"{name} must be numeric")
    finite = np.isfinite(arr)
    if not finite.any():
        raise RealDataRequiredError(f"{name} contains no finite values")
    unique_count = np.unique(arr[finite]).size
    if unique_count <= 2:
        raise RealDataRequiredError(f"{name} looks synthetic or constant; refusing analysis")
    return arr.astype(np.float32, copy=False)


def clean_light_curve(time: np.ndarray, flux: np.ndarray, quality: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    t = require_real_array("time", time)
    f = require_real_array("flux", flux)
    if t.shape != f.shape:
        raise ValueError("time and flux must have the same shape")
    mask = np.isfinite(t) & np.isfinite(f)
    if quality is not None:
        q = np.asarray(quality)
        if q.shape != t.shape:
            raise ValueError("quality must match time and flux shape")
        mask &= q == 0
    t = t[mask]
    f = f[mask]
    median = np.nanmedian(f)
    if not np.isfinite(median) or median == 0:
        raise RealDataRequiredError("flux median is invalid")
    normalized = (f / median).astype(np.float32)
    return t.astype(np.float32), normalized


def apply_manual_jitter_mask(time: np.ndarray, flux: np.ndarray, mask: np.ndarray, *, reason: str) -> tuple[np.ndarray, np.ndarray, dict]:
    if not reason.strip():
        raise ValueError("manual jitter masks require an audit reason")
    t = np.asarray(time)
    f = np.asarray(flux)
    m = np.asarray(mask, dtype=bool)
    if t.shape != f.shape or t.shape != m.shape:
        raise ValueError("time, flux, and mask must have identical shapes")
    kept = ~m
    audit = {
        "reason": reason,
        "masked_cadences": int(m.sum()),
        "input_cadences": int(m.size),
    }
    return t[kept].astype(np.float32), f[kept].astype(np.float32), audit
