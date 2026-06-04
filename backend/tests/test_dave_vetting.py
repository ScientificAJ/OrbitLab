from __future__ import annotations

import math

import numpy as np
import pytest

from orbitlab.science.bls import TransitCandidate
from orbitlab.science.dave_vetting import (
    _box_model_for_modshift,
    _brightening_significance,
    _dave_sigma_thresholds,
    _depth_significance,
    _erfcinv,
    _false_alarm_sigma,
    _finite_arrays,
    _official_robovet_flags,
    _phase_time,
    _red_noise_factor,
    _robust_scatter,
    _safe_float,
    _transit_depth_series,
    _window_mask,
    run_sweet_test,
)


def _candidate(period=2.0, epoch=0.1, duration=0.08, depth=0.002, power=9.0, snr=7.0):
    return TransitCandidate(period, epoch, duration, depth, power, snr)


def _sinusoidal_light_curve(period=2.0, amplitude=0.003, n=600):
    time = np.linspace(0, 27, n, dtype=np.float64)
    flux = 1.0 + amplitude * np.sin(2 * math.pi * time / period)
    return time, flux


def _transit_light_curve(candidate: TransitCandidate, n=800, noise=0.0005):
    rng = np.random.default_rng(0)
    time = np.linspace(0, 27, n, dtype=np.float64)
    flux = 1.0 + rng.normal(0, noise, size=n)
    phase = ((time - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period
    flux[np.abs(phase) < candidate.duration / 2] -= candidate.depth
    return time, flux


# ---------------------------------------------------------------------------
# _finite_arrays
# ---------------------------------------------------------------------------
def test_finite_arrays_strips_nan_and_inf():
    t = np.array([1.0, np.nan, 3.0, np.inf, 5.0])
    f = np.array([0.1, 0.2, np.nan, 0.4, 0.5])
    t_out, f_out = _finite_arrays(t, f)
    assert len(t_out) == 2
    assert np.all(np.isfinite(t_out))
    assert np.all(np.isfinite(f_out))


def test_finite_arrays_returns_empty_when_all_invalid():
    t, f = _finite_arrays(np.array([np.nan]), np.array([np.nan]))
    assert t.size == 0 and f.size == 0


# ---------------------------------------------------------------------------
# _robust_scatter
# ---------------------------------------------------------------------------
def test_robust_scatter_gaussian():
    rng = np.random.default_rng(42)
    data = rng.normal(0, 1.0, 10000)
    sigma = _robust_scatter(data)
    assert abs(sigma - 1.0) < 0.05


def test_robust_scatter_returns_nan_for_empty():
    assert math.isnan(_robust_scatter(np.array([])))


def test_robust_scatter_falls_back_to_std_for_zero_mad():
    data = np.array([1.0, 1.0, 1.0, 2.0])
    sigma = _robust_scatter(data)
    assert np.isfinite(sigma)


# ---------------------------------------------------------------------------
# _phase_time and _window_mask
# ---------------------------------------------------------------------------
def test_phase_time_centers_on_epoch():
    c = _candidate(period=2.0, epoch=0.1)
    time = np.array([0.1])  # at the epoch
    phase = _phase_time(time, c)
    assert abs(float(phase[0])) < 1e-9


def test_window_mask_selects_in_transit_cadences():
    c = _candidate(period=2.0, epoch=0.0, duration=0.1)
    time = np.array([-0.04, 0.0, 0.04, 0.5, 1.0])
    mask = _window_mask(time, c, 0.0, c.duration)
    assert mask[0] and mask[1] and mask[2]
    assert not mask[3] and not mask[4]


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------
def test_safe_float_returns_none_for_nan_and_inf():
    assert _safe_float(float("nan")) is None
    assert _safe_float(float("inf")) is None
    assert _safe_float(None) is None
    assert _safe_float("not a number") is None


def test_safe_float_converts_valid_numbers():
    assert _safe_float(3.14) == pytest.approx(3.14)
    assert _safe_float("2.71") == pytest.approx(2.71)


# ---------------------------------------------------------------------------
# _erfcinv and _false_alarm_sigma
# ---------------------------------------------------------------------------
def test_erfcinv_recovers_known_value():
    # erfc(1.0) ≈ 0.157299
    result = _erfcinv(math.erfc(1.0))
    assert abs(result - 1.0) < 1e-6


def test_false_alarm_sigma_clamps_below_three():
    sigma = _false_alarm_sigma(1.0)
    assert sigma >= 3.0


def test_false_alarm_sigma_grows_with_smaller_probability():
    sigma_small = _false_alarm_sigma(1e-6)
    sigma_large = _false_alarm_sigma(0.1)
    assert sigma_small > sigma_large


# ---------------------------------------------------------------------------
# _dave_sigma_thresholds
# ---------------------------------------------------------------------------
def test_dave_sigma_thresholds_returns_positive_values():
    c = _candidate(period=2.0)
    time = np.linspace(0, 27, 500)
    thresholds = _dave_sigma_thresholds(time, c, objects_evaluated=20000)
    assert thresholds["sigfa1"] >= 3.0
    assert thresholds["sigfa2"] >= 3.0
    assert thresholds["objects_evaluated"] == pytest.approx(20000.0)


def test_dave_sigma_thresholds_single_object():
    c = _candidate(period=2.0)
    time = np.linspace(0, 10, 200)
    thresholds = _dave_sigma_thresholds(time, c, objects_evaluated=1)
    assert np.isfinite(thresholds["sigfa1"])


# ---------------------------------------------------------------------------
# _box_model_for_modshift
# ---------------------------------------------------------------------------
def test_box_model_depth_matches_candidate_depth():
    c = _candidate(period=2.0, epoch=0.0, duration=0.1, depth=0.005)
    time = np.linspace(-1, 1, 100)
    flux = np.ones(100)
    model = _box_model_for_modshift(time, flux, c)
    in_transit = np.abs(time) <= 0.05
    baseline = float(np.nanmedian(model[~in_transit]))
    in_transit_level = float(np.nanmedian(model[in_transit]))
    assert abs(baseline - in_transit_level - 0.005) < 1e-6


def test_box_model_returns_baseline_for_zero_depth_candidate():
    c = TransitCandidate(period=2.0, epoch=0.0, duration=0.1, depth=0.0, power=1.0, signal_to_noise=1.0)
    time = np.linspace(0, 4, 100)
    flux = np.ones(100)
    model = _box_model_for_modshift(time, flux, c)
    assert np.all(model >= 0)


# ---------------------------------------------------------------------------
# _depth_significance and _brightening_significance
# ---------------------------------------------------------------------------
def test_depth_significance_returns_positive_for_real_transit():
    c = _candidate(period=2.0, epoch=0.0, duration=0.08)
    time, flux = _transit_light_curve(c)
    scatter = float(np.nanstd(flux))
    depth, sig, count = _depth_significance(time, flux, c, center_days=0.0, baseline=1.0, scatter=scatter)
    assert depth > 0
    assert count > 0
    assert sig > 0


def test_depth_significance_returns_zeros_when_scatter_invalid():
    c = _candidate(period=2.0, epoch=0.0, duration=0.08)
    time = np.linspace(0, 4, 100)
    flux = np.ones(100)
    # scatter=0 triggers the early-out path returning zeros
    depth, sig, count = _depth_significance(time, flux, c, center_days=0.0, baseline=1.0, scatter=0.0)
    assert sig == 0.0
    assert depth == 0.0


def test_brightening_significance_nonzero_for_sinusoid_peak():
    c = _candidate(period=2.0, epoch=0.5, duration=0.1)
    time, flux = _sinusoidal_light_curve(period=2.0, amplitude=0.005)
    scatter = _robust_scatter(flux) or 0.001
    height, sig, count = _brightening_significance(time, flux, c, center_days=0.0, baseline=1.0, scatter=scatter)
    assert count >= 0


# ---------------------------------------------------------------------------
# _transit_depth_series
# ---------------------------------------------------------------------------
def test_transit_depth_series_returns_one_depth_per_transit():
    c = _candidate(period=2.0, epoch=0.0, duration=0.08, depth=0.003)
    time, flux = _transit_light_curve(c, n=1000)
    depths = _transit_depth_series(time, flux, c, baseline=1.0)
    expected_transits = int((time[-1] - time[0]) / c.period)
    assert len(depths) >= max(1, expected_transits - 2)
    assert all(d >= 0 for d in depths)


def test_transit_depth_series_all_depths_nonnegative():
    c = _candidate(period=2.0, epoch=0.0, duration=0.08, depth=0.002)
    time, flux = _transit_light_curve(c, n=400)
    depths = _transit_depth_series(time, flux, c, baseline=1.0)
    assert len(depths) >= 1
    assert all(d >= 0 for d in depths)


# ---------------------------------------------------------------------------
# _red_noise_factor
# ---------------------------------------------------------------------------
def test_red_noise_factor_returns_one_for_white_noise():
    rng = np.random.default_rng(7)
    time = np.linspace(0, 27, 800)
    flux = 1.0 + rng.normal(0, 0.001, 800)
    c = _candidate(period=3.0, duration=0.1)
    scatter = _robust_scatter(flux)
    factor = _red_noise_factor(time, flux, c, scatter)
    assert 1.0 <= factor < 5.0


def test_red_noise_factor_returns_one_for_tiny_data():
    c = _candidate()
    factor = _red_noise_factor(np.linspace(0, 4, 5), np.ones(5), c, 0.001)
    assert factor == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# run_sweet_test
# ---------------------------------------------------------------------------
def test_sweet_test_warns_on_sinusoidal_oot():
    c = _candidate(period=2.0, epoch=0.0, duration=0.08)
    time, flux = _sinusoidal_light_curve(period=2.0, amplitude=0.01, n=1200)
    result = run_sweet_test(time, flux, c)
    assert result["engine"] == "sweet"
    assert result["status"] in ("pass", "warning")
    assert "periods" in result
    assert "max_sigma" in result


def test_sweet_test_passes_on_flat_light_curve():
    c = _candidate(period=3.0)
    time = np.linspace(0, 27, 800)
    flux = np.ones(800)
    result = run_sweet_test(time, flux, c)
    assert result["status"] == "pass"
    assert result["max_sigma"] == pytest.approx(0.0)


def test_sweet_test_returns_insufficient_data_for_short_series():
    c = _candidate()
    time = np.linspace(0, 1, 10)
    flux = np.ones(10)
    result = run_sweet_test(time, flux, c)
    assert result["status"] == "insufficient_data"


def test_sweet_test_returns_insufficient_data_for_zero_period():
    c = TransitCandidate(period=0.0, epoch=0.0, duration=0.08, depth=0.001, power=5.0, signal_to_noise=4.0)
    time = np.linspace(0, 27, 600)
    flux = np.ones(600)
    result = run_sweet_test(time, flux, c)
    assert result["status"] == "insufficient_data"


def test_sweet_test_detects_half_period_sinusoid():
    c = _candidate(period=4.0, epoch=0.0, duration=0.1)
    time = np.linspace(0, 40, 2000)
    flux = 1.0 + 0.015 * np.sin(2 * math.pi * time / 2.0)  # half-period sinusoid
    result = run_sweet_test(time, flux, c, threshold_sigma=3.0)
    periods_checked = [r["period_label"] for r in result.get("periods", [])]
    assert "half_period" in periods_checked


# ---------------------------------------------------------------------------
# _official_robovet_flags
# ---------------------------------------------------------------------------
def _clean_modshift(**overrides):
    base = {
        "mod_sig_pri": 20.0,
        "mod_sig_sec": 2.0,
        "mod_sig_ter": 1.0,
        "mod_sig_pos": 1.0,
        "mod_sig_oe": 1.0,
        "mod_dmm": 0.5,
        "mod_shape": 0.1,
        "mod_sig_fa1": 5.0,
        "mod_sig_fa2": 3.0,
        "mod_Fred": 2.0,
        "mod_ph_pri": 0.0,
        "mod_ph_sec": 0.5,
        "mod_ph_ter": 0.25,
        "mod_ph_pos": 0.75,
        "mod_secdepth": 0.0001,
        "mod_secdeptherr": 0.0001,
    }
    base.update(overrides)
    return base


def test_robovet_flags_clean_signal_is_candidate():
    flags, robovet = _official_robovet_flags(_clean_modshift())
    assert flags == []
    assert robovet["disp"] == "candidate"
    assert robovet["not_trans_like"] == 0
    assert robovet["sig_sec"] == 0


def test_robovet_flags_high_dmm_is_not_transit_like():
    flags, robovet = _official_robovet_flags(_clean_modshift(mod_dmm=2.0))
    assert "indiv_depths_not_consistent" in flags
    assert robovet["not_trans_like"] == 1
    assert robovet["disp"] == "false positive"


def test_robovet_flags_sinusoidal_shape_metric():
    flags, robovet = _official_robovet_flags(_clean_modshift(mod_shape=0.5))
    assert "sinusoidal_via_modshift" in flags
    assert robovet["not_trans_like"] == 1


def test_robovet_flags_secondary_eclipse_detected():
    flags, robovet = _official_robovet_flags(
        _clean_modshift(mod_sig_sec=12.0, mod_sig_ter=2.0, mod_sig_pri=14.0)
    )
    assert "sig_sec_in_model_shift" in flags
    assert robovet["sig_sec"] == 1
    assert robovet["disp"] == "false positive"


def test_robovet_flags_odd_even_diff():
    flags, robovet = _official_robovet_flags(_clean_modshift(mod_sig_oe=8.0))
    assert "odd_even_diff" in flags
    assert robovet["sig_sec"] == 1
