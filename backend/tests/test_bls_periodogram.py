import numpy as np
from orbitlab.science.bls import BlsResult, bin_light_curve_for_search, run_bls


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
