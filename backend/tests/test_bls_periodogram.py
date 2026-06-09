import builtins
import sys
import types

import numpy as np
import pytest
from orbitlab.science.bls import (
    BlsResult,
    TransitCandidate,
    _adaptive_duration_grid,
    _build_period_grid,
    _cadence_days,
    _clamp_period_range,
    _largest_valid_odd_window,
    _measured_transit_depth,
    _robust_scatter,
    _transit_detection_snr,
    bin_light_curve_for_search,
    find_multi_planet_candidates,
    mask_transit_windows,
    run_bls,
    sigma_clip_flux,
    transit_safe_flatten,
)


def synthetic_transit_curve(period=3.0, duration=0.12, depth=0.01):
    time = np.linspace(0, 27, 2500, dtype=np.float32)
    flux = np.ones_like(time, dtype=np.float32)

    phase = ((time - 0.5 + 0.5 * period) % period) - 0.5 * period
    flux[np.abs(phase) < duration / 2] -= depth

    trend = 1.0 + 0.002 * np.sin(2 * np.pi * time / 13.5)
    flux *= trend.astype(np.float32)

    return time, flux


def test_run_bls_returns_traceable_search_light_curve_and_metadata():
    time, flux = synthetic_transit_curve()

    result = run_bls(time, flux, min_period=1.0, max_period=30.0, period_samples=2048)

    assert isinstance(result, BlsResult)
    assert result.search_time.size == result.search_flux.size
    assert result.clean_time.size == result.clean_flux.size
    assert result.metadata["max_period_days"] <= result.metadata["baseline_days"] / 2.0 + 1e-6
    assert result.metadata["period_count"] >= 32
    assert "duration" in result.periodogram
    assert np.isfinite(result.periodogram["power"]).any()


def test_run_bls_keeps_detected_period_near_injected_period():
    time, flux = synthetic_transit_curve(period=3.0)

    result = run_bls(time, flux, min_period=1.0, max_period=10.0, period_samples=4096)

    assert abs(result.candidate.period - 3.0) < 0.15
    assert result.candidate.signal_to_noise > 0


def test_run_bls_uses_transit_cadence_weighted_snr():
    rng = np.random.default_rng(7)
    time = np.linspace(0, 27, 2500, dtype=np.float32)
    period = 2.15
    duration = 0.11
    depth = 0.0018
    noise = 0.00045
    flux = 1.0 + rng.normal(0, noise, size=time.size).astype(np.float32)
    phase = ((time - 0.35 + 0.5 * period) % period) - 0.5 * period
    flux[np.abs(phase) < duration / 2] -= depth

    result = run_bls(time, flux, min_period=1.5, max_period=3.0, period_samples=4096)

    old_depth_over_scatter = result.candidate.depth / np.nanstd(result.search_flux - np.nanmedian(result.search_flux))
    assert abs(result.candidate.period - period) < 0.08
    assert result.candidate.signal_to_noise > old_depth_over_scatter * 2
    assert result.metadata["snr_estimator"] == "depth_over_out_of_transit_mad_times_sqrt_in_transit_cadences"


def test_bls_search_binning_caps_fast_cadence_without_losing_transit_period():
    rng = np.random.default_rng(13)
    time = np.linspace(0, 18, 18000, dtype=np.float32)
    period = 1.51
    duration = 0.055
    flux = 1.0 + rng.normal(0, 0.00035, size=time.size).astype(np.float32)
    phase = ((time - 0.22 + 0.5 * period) % period) - 0.5 * period
    flux[np.abs(phase) < duration / 2] -= 0.0022

    binned_time, binned_flux, metadata = bin_light_curve_for_search(time, flux, max_cadences=3000)

    assert metadata["applied"] is True
    assert binned_time.size <= 3000
    assert binned_time.size == binned_flux.size

    result = run_bls(time, flux, min_period=1.0, max_period=2.0, period_samples=1024, max_search_cadences=3000)

    assert result.metadata["search_binning"]["applied"] is True
    assert result.metadata["search_binning"]["search_cadences"] <= 3000
    assert abs(result.candidate.period - period) < 0.08


def test_multi_candidate_search_preserves_primary_when_residual_is_too_small(monkeypatch):
    from orbitlab.science import bls
    from orbitlab.science.bls import TransitCandidate, find_multi_planet_candidates

    primary = TransitCandidate(
        period=2.0,
        epoch=0.5,
        duration=0.4,
        depth=0.01,
        power=10.0,
        signal_to_noise=8.0,
    )

    def exploding_run_bls(*args, **kwargs):
        raise ValueError("residual too small")

    monkeypatch.setattr(bls, "run_bls", exploding_run_bls)

    time = np.linspace(0, 5, 80)
    flux = 1.0 + 0.001 * np.sin(time)

    candidates = find_multi_planet_candidates(time, flux, initial_candidate=primary)

    assert candidates == [primary]


def test_bls_preprocessing_and_grid_helpers_cover_guardrails(monkeypatch):
    time = np.arange(10, dtype=float)
    flux = np.ones(10, dtype=float)

    assert sigma_clip_flux(time, flux) == (time, flux)
    clipped_time, clipped_flux = sigma_clip_flux(
        time,
        np.array([1.0, 1.01, 1.02, 1.03, 1.04, 1.05, 1.06, 1.07, 1.08, 3.0]),
        sigma=3.0,
    )
    assert clipped_time.size == clipped_flux.size == 9

    with pytest.raises(ValueError, match="same shape"):
        bin_light_curve_for_search(time, flux[:-1])

    unbinned_time, unbinned_flux, metadata = bin_light_curve_for_search(time, flux, max_cadences=0)
    assert np.array_equal(unbinned_time, time)
    assert np.array_equal(unbinned_flux, flux)
    assert metadata["applied"] is False

    assert _largest_valid_odd_window(6, 5) == 5
    assert _largest_valid_odd_window(6, 8) == 5
    assert _largest_valid_odd_window(10, 8) == 7
    assert np.array_equal(transit_safe_flatten(np.arange(6), np.arange(6)), np.arange(6, dtype=np.float32))
    assert _cadence_days(np.ones(4)) == pytest.approx(1.0 / 48.0)

    binned_time, binned_flux, metadata = bin_light_curve_for_search(
        np.array([0.0, 1.0, np.nan, np.nan, 4.0, 5.0]),
        np.array([1.0, 1.01, np.nan, np.nan, 0.99, 1.0]),
        max_cadences=3,
    )
    assert metadata["applied"] is True
    assert binned_time.size == binned_flux.size == 2

    def all_nan_trend(flux, **kwargs):
        return np.full_like(flux, np.nan, dtype=float)

    fake_signal = types.SimpleNamespace(savgol_filter=all_nan_trend)
    monkeypatch.setitem(sys.modules, "scipy.signal", fake_signal)
    assert np.array_equal(
        transit_safe_flatten(np.arange(9), np.linspace(1.0, 1.1, 9)), np.linspace(1.0, 1.1, 9).astype(np.float32)
    )

    def ones_trend(flux, **kwargs):
        return np.ones_like(flux, dtype=float)

    monkeypatch.setitem(sys.modules, "scipy.signal", types.SimpleNamespace(savgol_filter=ones_trend))
    zero_median_flux = np.array([-4.0, -3.0, -2.0, -1.0, 0.0, 0.0, 1.0, 2.0, 3.0])
    assert np.array_equal(transit_safe_flatten(np.arange(9), zero_median_flux), zero_median_flux.astype(np.float32))

    monkeypatch.setattr("orbitlab.science.bls._largest_valid_odd_window", lambda size, preferred: 5)
    branch_flux = np.linspace(1.0, 1.8, 9)
    assert np.allclose(
        transit_safe_flatten(np.arange(9), branch_flux), (branch_flux / np.nanmedian(branch_flux)).astype(np.float32)
    )
    assert np.array_equal(transit_safe_flatten(np.arange(9), np.zeros(9)), np.zeros(9, dtype=np.float32))

    real_import = builtins.__import__

    def reject_scipy_signal(name, *args, **kwargs):
        if name == "scipy.signal":
            raise ImportError("scipy missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("orbitlab.science.bls._largest_valid_odd_window", lambda size, preferred: 7)
    monkeypatch.setattr(builtins, "__import__", reject_scipy_signal)
    with pytest.raises(RuntimeError, match="scipy is required"):
        transit_safe_flatten(np.arange(9), np.linspace(1.0, 1.8, 9))


def test_bls_period_and_duration_grid_edges():
    with pytest.raises(ValueError, match="positive observation baseline"):
        _clamp_period_range(np.ones(8), 1.0, 2.0, min_transits=2.0)

    with pytest.raises(ValueError, match="invalid BLS period range"):
        _clamp_period_range(np.linspace(0.0, 1.0, 32), 0.9, 1.0, min_transits=2.0)

    min_period, max_period, baseline, cadence = _clamp_period_range(
        np.linspace(0.0, 4.0, 32),
        0.1,
        10.0,
        min_transits=2.0,
    )
    assert min_period > 0
    assert max_period == pytest.approx(2.0)
    assert baseline == pytest.approx(4.0)
    assert cadence > 0

    with pytest.raises(ValueError, match="duration_grid"):
        _adaptive_duration_grid(0.02, 1.0, 2.0, np.array([np.nan, -1.0]))

    assert np.array_equal(_adaptive_duration_grid(0.02, 1.0, 2.0, np.array([0.2, 0.1, 0.1])), np.array([0.1, 0.2]))
    assert _adaptive_duration_grid(1.0, 0.00011, 0.00012, None).size >= 1
    assert np.array_equal(_adaptive_duration_grid(1e-8, 1e-8, 1e-8, None), np.array([5e-5]))


def test_build_period_grid_fallbacks_and_cap():
    class _TypeErrorModel:
        def __init__(self):
            self.calls = 0

        def autoperiod(self, durations, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TypeError("legacy signature")
            return np.array([1.0, 2.0, 3.0])

    periods, source = _build_period_grid(
        _TypeErrorModel(),
        np.array([0.1]),
        min_period=1.0,
        max_period=3.0,
        period_samples=16,
        max_period_samples=10,
    )
    assert periods.size <= 10
    assert source.endswith("_capped")

    class _FailingModel:
        def autoperiod(self, durations, **kwargs):
            raise RuntimeError("autoperiod failed")

    periods, source = _build_period_grid(
        _FailingModel(),
        np.array([0.1]),
        min_period=1.0,
        max_period=3.0,
        period_samples=4,
        max_period_samples=100,
    )
    assert periods.size >= 32
    assert source == "geomspace_and_frequency_fallback"

    periods, source = _build_period_grid(
        _FailingModel(),
        np.array([0.1]),
        min_period=1.0,
        max_period=1.0,
        period_samples=32,
        max_period_samples=100,
    )
    assert np.array_equal(periods, np.array([1.0]))
    assert source == "geomspace_and_frequency_fallback"


def test_depth_snr_and_residual_candidate_edges(monkeypatch):
    time = np.linspace(0.0, 10.0, 200)
    flux = np.ones_like(time)
    candidate = TransitCandidate(period=2.0, epoch=0.5, duration=0.1, depth=0.001, power=1.0, signal_to_noise=5.0)

    assert _robust_scatter(np.array([np.nan, np.nan])) == 0.0
    assert _robust_scatter(np.ones(4)) == 0.0
    assert _transit_detection_snr(time, flux, period=0.0, epoch=0.0, duration=0.1, depth=0.001) == 0.0
    assert _transit_detection_snr(time[:3], flux[:3], period=2.0, epoch=0.5, duration=0.01, depth=0.001) == 0.0
    assert _transit_detection_snr(time, flux, period=2.0, epoch=0.5, duration=0.1, depth=0.001) == 0.0
    assert _measured_transit_depth(time, flux, period=0.0, epoch=0.0, duration=0.1) == 0.0
    assert _measured_transit_depth(time[:8], flux[:8], period=2.0, epoch=0.5, duration=0.1) == 0.0
    assert _measured_transit_depth(time, flux, period=2.0, epoch=0.5, duration=0.1) == 0.0

    masked_time, masked_flux = mask_transit_windows(time, flux, candidate)
    assert masked_time.size == masked_flux.size
    assert masked_time.size < time.size

    assert find_multi_planet_candidates(time, flux, initial_candidate=candidate, min_signal_to_noise=6.0) == []

    strong = TransitCandidate(period=2.0, epoch=0.5, duration=0.1, depth=0.001, power=1.0, signal_to_noise=8.0)
    weak = TransitCandidate(period=3.0, epoch=0.5, duration=0.1, depth=0.001, power=1.0, signal_to_noise=1.0)

    class _Result:
        candidate = weak

    monkeypatch.setattr("orbitlab.science.bls.run_bls", lambda *args, **kwargs: _Result())

    candidates = find_multi_planet_candidates(
        np.linspace(0.0, 10.0, 256),
        1.0 + 0.001 * np.sin(np.linspace(0.0, 4.0, 256)),
        initial_candidate=strong,
        preserve_initial_candidate=True,
        min_signal_to_noise=6.0,
    )

    assert candidates == [strong]

    assert find_multi_planet_candidates(time, flux, max_candidates=0) == []

    def failing_run_bls(*args, **kwargs):
        raise RuntimeError("BLS failed")

    monkeypatch.setattr("orbitlab.science.bls.run_bls", failing_run_bls)
    assert find_multi_planet_candidates(np.linspace(0.0, 10.0, 256), 1.0 + 0.001 * np.sin(time[:256])) == []

    class _StrongResult:
        candidate = strong

    monkeypatch.setattr("orbitlab.science.bls.run_bls", lambda *args, **kwargs: _StrongResult())
    residual_time = np.linspace(0.0, 10.0, 256)
    found = find_multi_planet_candidates(
        residual_time,
        1.0 + 0.001 * np.sin(residual_time),
        max_candidates=1,
    )
    assert found == [strong]


def test_run_bls_pre_astropy_error_branches(monkeypatch):
    time = np.linspace(0.0, 10.0, 128)
    flux = 1.0 + 0.001 * np.sin(time)

    monkeypatch.setattr(
        "orbitlab.science.bls.sigma_clip_flux", lambda clean_time, clean_flux: (clean_time[:63], clean_flux[:63])
    )
    with pytest.raises(ValueError, match="at least 64 cadences"):
        run_bls(time, flux)

    monkeypatch.setattr("orbitlab.science.bls.sigma_clip_flux", lambda clean_time, clean_flux: (clean_time, clean_flux))
    monkeypatch.setattr(
        "orbitlab.science.bls.bin_light_curve_for_search",
        lambda *args, **kwargs: (time[:63], flux[:63], {"applied": True}),
    )
    with pytest.raises(ValueError, match="adaptive search binning"):
        run_bls(time, flux)

    monkeypatch.setattr(
        "orbitlab.science.bls.bin_light_curve_for_search",
        lambda *args, **kwargs: (time, flux, {"applied": False}),
    )
    monkeypatch.setitem(sys.modules, "astropy.timeseries", None)
    with pytest.raises(RuntimeError, match="astropy is required"):
        run_bls(time, flux)


def test_run_bls_reports_no_finite_periodogram_power(monkeypatch):
    class _PowerResult:
        period = np.array([1.0, 2.0])
        transit_time = np.array([0.1, 0.2])
        duration = np.array([0.1, 0.1])
        depth = np.array([0.001, 0.001])
        power = np.array([np.nan, np.nan])

    class _FakeBoxLeastSquares:
        def __init__(self, time, flux):
            self.time = time
            self.flux = flux

        def autoperiod(self, durations, **kwargs):
            return np.array([1.0, 2.0])

        def power(self, periods, durations):
            return _PowerResult()

    monkeypatch.setitem(
        sys.modules,
        "astropy.timeseries",
        types.SimpleNamespace(BoxLeastSquares=_FakeBoxLeastSquares),
    )

    time = np.linspace(0.0, 10.0, 128)
    flux = 1.0 + 0.001 * np.sin(time)

    with pytest.raises(ValueError, match="no finite power"):
        run_bls(time, flux, min_period=1.0, max_period=3.0, period_samples=32)
