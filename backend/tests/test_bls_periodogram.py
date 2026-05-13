import numpy as np

from orbitlab.science.bls import BlsResult, run_bls


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
