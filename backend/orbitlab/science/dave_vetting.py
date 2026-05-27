from __future__ import annotations

import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from orbitlab.science.bls import TransitCandidate


def _finite_arrays(time: np.ndarray, flux: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    t = np.asarray(time, dtype=float)
    f = np.asarray(flux, dtype=float)
    finite = np.isfinite(t) & np.isfinite(f)
    return t[finite], f[finite]


def _robust_scatter(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    median = float(np.nanmedian(arr))
    mad = float(np.nanmedian(np.abs(arr - median)))
    scatter = 1.4826 * mad
    if not np.isfinite(scatter) or scatter <= 0:
        scatter = float(np.nanstd(arr))
    return scatter


def _phase_time(time: np.ndarray, candidate: TransitCandidate, offset_days: float = 0.0) -> np.ndarray:
    return ((time - candidate.epoch - offset_days + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period


def _window_mask(time: np.ndarray, candidate: TransitCandidate, center_days: float, width_days: float) -> np.ndarray:
    return np.abs(_phase_time(time, candidate, center_days)) <= 0.5 * width_days


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _default_modshift_binary() -> Path:
    env_path = os.environ.get("ORBITLAB_DAVE_MODSHIFT")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parents[3] / ".orbitlab" / "external" / "DAVE" / "vetting" / "modshift"


def _box_model_for_modshift(time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate) -> np.ndarray:
    primary = _window_mask(time, candidate, 0.0, candidate.duration)
    baseline_mask = ~primary
    baseline = (
        float(np.nanmedian(flux[baseline_mask]))
        if np.count_nonzero(baseline_mask)
        else float(np.nanmedian(flux))
    )
    depth = _safe_float(candidate.depth)
    if depth is None or depth <= 0:
        depth = max(0.0, baseline - float(np.nanmedian(flux[primary]))) if np.count_nonzero(primary) else 0.0
    model = np.full_like(flux, baseline, dtype=float)
    model[primary] = baseline - float(depth)
    return model


def _run_official_modshift(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    modshift_binary: str | Path | None = None,
    timeout_seconds: int = 15,
) -> dict[str, float]:
    binary = Path(modshift_binary) if modshift_binary is not None else _default_modshift_binary()
    if not binary.exists():
        raise RuntimeError(f"Official DAVE modshift binary is missing at {binary}")
    if not os.access(binary, os.X_OK):
        raise RuntimeError(f"Official DAVE modshift binary is not executable at {binary}")

    model = _box_model_for_modshift(time, flux, candidate)
    with tempfile.NamedTemporaryFile(prefix="orbitlab-dave-modshift-", suffix=".dat", mode="w", delete=False) as handle:
        input_path = Path(handle.name)
        np.savetxt(handle, np.column_stack((time, flux, model)))
    try:
        completed = subprocess.run(
            [
                str(binary),
                str(input_path),
                "orbitlab-modshift",
                "OrbitLab",
                str(float(candidate.period)),
                str(float(candidate.epoch)),
                "0",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    finally:
        input_path.unlink(missing_ok=True)

    fields = completed.stdout.split()
    if len(fields) < 17:
        raise RuntimeError(f"Official DAVE modshift returned an incomplete result: {completed.stdout.strip()}")
    return {
        "mod_sig_pri": float(fields[1]),
        "mod_sig_sec": float(fields[2]),
        "mod_sig_ter": float(fields[3]),
        "mod_sig_pos": float(fields[4]),
        "mod_sig_oe": float(fields[5]),
        "mod_dmm": float(fields[6]),
        "mod_shape": float(fields[7]),
        "mod_sig_fa1": float(fields[8]),
        "mod_sig_fa2": float(fields[9]),
        "mod_Fred": float(fields[10]),
        "mod_ph_pri": float(fields[11]),
        "mod_ph_sec": float(fields[12]),
        "mod_ph_ter": float(fields[13]),
        "mod_ph_pos": float(fields[14]),
        "mod_secdepth": float(fields[15]),
        "mod_secdeptherr": float(fields[16]),
    }


def _official_robovet_flags(modshift: dict[str, float]) -> tuple[list[str], dict[str, Any]]:
    flags: list[str] = []
    comments: list[str] = []
    sig_pri = modshift["mod_sig_pri"]
    sig_sec = modshift["mod_sig_sec"]
    sig_ter = modshift["mod_sig_ter"]
    sig_pos = modshift["mod_sig_pos"]
    sig_oe = modshift["mod_sig_oe"]
    sig_fa1 = modshift["mod_sig_fa1"]
    sig_fa2 = modshift["mod_sig_fa2"]
    fred = modshift["mod_Fred"]

    not_trans_like = 0
    if sig_pri / fred < sig_fa1 and sig_pri > 0:
        flags.append("sig_pri_over_fred_too_low")
        comments.append("SIG_PRI_OVER_FRED_TOO_LOW")
        not_trans_like = 1
    if sig_pri - sig_ter < sig_fa2 and sig_pri > 0 and sig_ter > 0:
        flags.append("sig_pri_minus_sig_ter_too_low")
        comments.append("SIG_PRI_MINUS_SIG_TER_TOO_LOW")
        not_trans_like = 1
    if sig_pri - sig_pos < sig_fa2 and sig_pri > 0 and sig_pos > 0:
        flags.append("sig_pri_minus_sig_pos_too_low")
        comments.append("SIG_PRI_MINUS_SIG_POS_TOO_LOW")
        not_trans_like = 1
    if modshift["mod_dmm"] > 1.5:
        flags.append("indiv_depths_not_consistent")
        comments.append("INDIV_DEPTHS_NOT_CONSISTENT")
        not_trans_like = 1
    if modshift["mod_shape"] > 0.3:
        flags.append("sinusoidal_via_modshift")
        comments.append("SINUSOIDAL_VIA_MODSHIFT")
        not_trans_like = 1

    sig_sec_flag = 0
    if (
        sig_sec / fred > sig_fa1
        and sig_sec > 0
        and (sig_sec - sig_ter > sig_fa2 or sig_ter > 0)
        and (sig_sec - sig_pri > sig_fa2 or sig_pri > 0)
    ):
        flags.append("sig_sec_in_model_shift")
        comments.append("SIG_SEC_IN_MODEL_SHIFT")
        sig_sec_flag = 1
    if sig_oe > sig_fa1:
        flags.append("odd_even_diff")
        comments.append("ODD_EVEN_DIFF")
        sig_sec_flag = 1

    return flags, {
        "disp": "false positive" if not_trans_like > 0 or sig_sec_flag > 0 else "candidate",
        "not_trans_like": not_trans_like,
        "sig_sec": sig_sec_flag,
        "comments": "---".join(comments),
    }


def _erfcinv(value: float) -> float:
    y = min(max(float(value), 1e-300), 2.0 - 1e-16)
    low = -12.0
    high = 12.0
    for _ in range(96):
        mid = 0.5 * (low + high)
        if math.erfc(mid) > y:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def _false_alarm_sigma(probability: float) -> float:
    sigma = math.sqrt(2.0) * _erfcinv(probability)
    if not np.isfinite(sigma):
        return 3.0
    return max(3.0, sigma)


def _dave_sigma_thresholds(time: np.ndarray, candidate: TransitCandidate, objects_evaluated: int) -> dict[str, float]:
    baseline_days = float(np.nanmax(time) - np.nanmin(time)) if time.size else 0.0
    period = max(float(candidate.period), np.finfo(float).eps)
    search_trials = max(float(objects_evaluated), 1.0)
    sigfa1_probability = baseline_days / (period * search_trials)
    sigfa2_probability = baseline_days / period
    return {
        "sigfa1": _false_alarm_sigma(sigfa1_probability),
        "sigfa2": _false_alarm_sigma(sigfa2_probability),
        "objects_evaluated": float(objects_evaluated),
    }


def _depth_significance(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    center_days: float,
    baseline: float,
    scatter: float,
) -> tuple[float, float, int]:
    mask = _window_mask(time, candidate, center_days, candidate.duration)
    count = int(np.count_nonzero(mask))
    if count == 0 or not np.isfinite(scatter) or scatter <= 0:
        return 0.0, 0.0, count
    depth = baseline - float(np.nanmedian(flux[mask]))
    significance = depth / scatter * math.sqrt(count)
    return float(depth), float(significance), count


def _brightening_significance(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    center_days: float,
    baseline: float,
    scatter: float,
) -> tuple[float, float, int]:
    mask = _window_mask(time, candidate, center_days, candidate.duration)
    count = int(np.count_nonzero(mask))
    if count == 0 or not np.isfinite(scatter) or scatter <= 0:
        return 0.0, 0.0, count
    height = float(np.nanmedian(flux[mask])) - baseline
    significance = height / scatter * math.sqrt(count)
    return float(height), float(significance), count


def _transit_depth_series(
    time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate, *, baseline: float
) -> list[float]:
    transit_number = np.floor((time - candidate.epoch) / candidate.period).astype(int)
    primary_mask = _window_mask(time, candidate, 0.0, candidate.duration)
    depths: list[float] = []
    for number in np.unique(transit_number[primary_mask]):
        mask = primary_mask & (transit_number == number)
        if np.count_nonzero(mask):
            depths.append(max(0.0, baseline - float(np.nanmedian(flux[mask]))))
    return depths


def _red_noise_factor(time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate, scatter: float) -> float:
    if time.size < 8 or not np.isfinite(scatter) or scatter <= 0:
        return 1.0
    cadence = np.diff(np.sort(time))
    cadence = cadence[np.isfinite(cadence) & (cadence > 0)]
    if cadence.size == 0:
        return 1.0
    bin_size = max(2, int(round(candidate.duration / float(np.nanmedian(cadence)))))
    if bin_size <= 1 or time.size < bin_size * 3:
        return 1.0
    residual = flux - float(np.nanmedian(flux))
    usable = residual[: residual.size - residual.size % bin_size]
    if usable.size == 0:
        return 1.0
    binned = np.nanmean(usable.reshape(-1, bin_size), axis=1)
    expected = scatter / math.sqrt(bin_size)
    measured = _robust_scatter(binned)
    if not np.isfinite(measured) or not np.isfinite(expected) or expected <= 0:
        return 1.0
    return float(max(1.0, measured / expected))


def run_sweet_test(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    threshold_sigma: float = 3.0,
) -> dict[str, Any]:
    t, f = _finite_arrays(time, flux)
    if t.size < 16 or candidate.period <= 0 or candidate.duration <= 0:
        return {"status": "insufficient_data", "engine": "sweet", "threshold_sigma": threshold_sigma}
    out_of_transit = np.abs(_phase_time(t, candidate)) > candidate.duration
    if np.count_nonzero(out_of_transit) < 8:
        return {"status": "insufficient_data", "engine": "sweet", "threshold_sigma": threshold_sigma}
    oot_time = t[out_of_transit]
    oot_flux = f[out_of_transit] - float(np.nanmedian(f[out_of_transit]))
    rows = []
    max_sigma = 0.0
    for label, period in (
        ("half_period", candidate.period / 2.0),
        ("period", candidate.period),
        ("double_period", candidate.period * 2.0),
    ):
        if period <= 0:
            continue
        omega = 2.0 * math.pi / period
        design = np.column_stack((np.sin(omega * oot_time), np.cos(omega * oot_time), np.ones_like(oot_time)))
        try:
            coefficients, *_ = np.linalg.lstsq(design, oot_flux, rcond=None)
        except np.linalg.LinAlgError:
            continue
        model = design @ coefficients
        residual_scatter = _robust_scatter(oot_flux - model)
        amplitude = float(math.hypot(float(coefficients[0]), float(coefficients[1])))
        amplitude_uncertainty = residual_scatter / math.sqrt(max(oot_time.size / 2.0, 1.0))
        sigma = amplitude / amplitude_uncertainty if amplitude_uncertainty > 0 else 0.0
        max_sigma = max(max_sigma, sigma)
        rows.append(
            {
                "period_tested_days": period,
                "period_label": label,
                "amplitude": amplitude,
                "sigma": sigma,
                "threshold_sigma": threshold_sigma,
                "status": "warning" if sigma >= threshold_sigma else "pass",
            }
        )
    return {
        "status": "warning" if any(row["status"] == "warning" for row in rows) else "pass",
        "engine": "sweet",
        "threshold_sigma": threshold_sigma,
        "max_sigma": max_sigma,
        "periods": rows,
        "source": "DAVE SWEET sinusoid search at P/2, P, and 2P",
    }


def run_model_shift(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    objects_evaluated: int = 20000,
    modshift_binary: str | Path | None = None,
) -> dict[str, Any]:
    t, f = _finite_arrays(time, flux)
    if t.size < 16 or candidate.period <= 0 or candidate.duration <= 0:
        return {"status": "insufficient_data", "engine": "dave_model_shift"}
    modshift = _run_official_modshift(t, f, candidate, modshift_binary=modshift_binary)
    flags, robovet = _official_robovet_flags(modshift)

    return {
        "status": "fail" if flags else "pass",
        "engine": "dave_model_shift",
        "hard_fail": bool(flags),
        "flags": flags,
        "robovet": robovet,
        "primary": {
            "sigma": modshift["mod_sig_pri"],
            "normalized_sigma": modshift["mod_sig_pri"] / modshift["mod_Fred"],
            "phase": modshift["mod_ph_pri"],
        },
        "secondary": {
            "sigma": modshift["mod_sig_sec"],
            "normalized_sigma": modshift["mod_sig_sec"] / modshift["mod_Fred"],
            "phase": modshift["mod_ph_sec"],
            "depth": modshift["mod_secdepth"],
            "depth_error": modshift["mod_secdeptherr"],
        },
        "tertiary": {"sigma": modshift["mod_sig_ter"], "phase": modshift["mod_ph_ter"]},
        "positive": {"sigma": modshift["mod_sig_pos"], "phase": modshift["mod_ph_pos"]},
        "thresholds": {
            "sigfa1": modshift["mod_sig_fa1"],
            "sigfa2": modshift["mod_sig_fa2"],
            "objects_evaluated": float(objects_evaluated),
        },
        "fred": modshift["mod_Fred"],
        "dmm": _safe_float(modshift["mod_dmm"]),
        "shape_metric": _safe_float(modshift["mod_shape"]),
        "odd_even_sigma": _safe_float(modshift["mod_sig_oe"]),
        "modshift": modshift,
        "source": "Official DAVE ModShift binary with DAVE RoboVet thresholds",
    }
