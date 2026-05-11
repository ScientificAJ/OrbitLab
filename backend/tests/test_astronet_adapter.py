import numpy as np

from orbitlab.ml.astronet_adapter import GLOBAL_BINS, LOCAL_BINS, build_astronet_tensors
from orbitlab.science.bls import TransitCandidate


def injected_transit_curve(period=3.14159, epoch=0.37, duration=0.11, depth=0.018):
    rng = np.random.default_rng(42)
    time = np.linspace(0.0, 80.0, 6000, dtype=np.float32)
    flux = 1.0 + rng.normal(0.0, 0.0015, size=time.size).astype(np.float32)
    phase_time = np.abs(((time - epoch + 0.5 * period) % period) - 0.5 * period)
    flux[phase_time < duration / 2] -= depth
    return time, flux


def test_astronet_adapter_shapes_dtype_and_checksum_are_deterministic():
    time, flux = injected_transit_curve()
    candidate = TransitCandidate(period=3.14159, epoch=0.37, duration=0.11, depth=0.018, power=55.0, signal_to_noise=14.0)

    first = build_astronet_tensors(time, flux, candidate, stellar_radius_solar=1.0, stellar_mass_solar=1.0)
    second = build_astronet_tensors(time, flux, candidate, stellar_radius_solar=1.0, stellar_mass_solar=1.0)

    assert first.global_view.shape == (1, GLOBAL_BINS, 1)
    assert first.local_view.shape == (1, LOCAL_BINS, 1)
    assert first.metadata.shape == (1, 7)
    assert first.global_view.dtype == np.float32
    assert first.local_view.dtype == np.float32
    assert np.isfinite(first.global_view).all()
    assert np.isfinite(first.local_view).all()
    assert first.checksum == second.checksum


def test_astronet_adapter_rejects_nan_flux():
    time, flux = injected_transit_curve()
    flux[:] = np.nan
    candidate = TransitCandidate(period=3.14159, epoch=0.37, duration=0.11, depth=0.018, power=55.0, signal_to_noise=14.0)

    try:
        build_astronet_tensors(time, flux, candidate)
    except Exception as exc:
        assert "finite" in str(exc) or "invalid" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("NaN flux must be rejected")

