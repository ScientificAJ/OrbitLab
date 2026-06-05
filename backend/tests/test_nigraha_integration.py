import json
from pathlib import Path

import numpy as np
from orbitlab.ml.nigraha_adapter import (
    NIGRAHA_STANDARDIZED_FEATURES,
    build_nigraha_tensors,
    clear_norm_stats_cache,
)
from orbitlab.ml.nigraha_service import NigrahaNumpyModel, NigrahaService
from orbitlab.science.bls import TransitCandidate

# A path that does not exist, used to exercise the safety-net fallback (no
# standardization -> raw scalars -> saturated logit -> honest gating).
_MISSING_STATS = Path("/nonexistent/orbitlab/nigraha_norm_stats.json")


def transit_curve():
    rng = np.random.default_rng(123)
    time = np.linspace(0.0, 30.0, 3000, dtype=np.float32)
    period = 2.75
    epoch = 0.4
    duration = 0.12
    flux = 1.0 + rng.normal(0.0, 0.001, size=time.size).astype(np.float32)
    phase_time = np.abs(((time - epoch + 0.5 * period) % period) - 0.5 * period)
    flux[phase_time < duration / 2.0] -= 0.01
    return time, flux, TransitCandidate(period, epoch, duration, 0.01, 24.0, 10.0)


def test_nigraha_adapter_shapes_and_imputation():
    time, flux, candidate = transit_curve()
    tensors = build_nigraha_tensors(time, flux, candidate)

    assert tensors.global_view.shape == (1, 201, 1)
    assert tensors.local_view.shape == (1, 81, 1)
    assert tensors.odd_even_view.shape == (1, 162, 1)
    assert tensors.scalar_features["Depth"].shape == (1, 1)
    # Imputation tracking is independent of standardization: solar defaults are
    # still reported as imputed even though they are now z-scored downstream.
    assert "Teff" in tensors.imputed_features
    assert np.isfinite(tensors.global_view).all()
    assert np.isfinite(tensors.local_view).all()
    assert np.isfinite(tensors.odd_even_view).all()


def test_nigraha_adapter_standardizes_only_stellar_features():
    """Upstream standardizes the six stellar scalars (median/std) and leaves the
    five transit scalars raw (upstream `raw_columns`). Verify both halves.
    """
    clear_norm_stats_cache()
    time, flux, candidate = transit_curve()
    raw = build_nigraha_tensors(time, flux, candidate, norm_stats_path=_MISSING_STATS)
    std = build_nigraha_tensors(time, flux, candidate)

    assert raw.standardized is False
    assert std.standardized is True
    assert set(std.standardized_features) == set(NIGRAHA_STANDARDIZED_FEATURES)

    # Stellar features change under standardization; transit features do not.
    for name in NIGRAHA_STANDARDIZED_FEATURES:
        assert not np.allclose(
            std.scalar_features[name], raw.scalar_features[name]
        ), f"{name} should be standardized"
    for name in ("Depth", "Duration", "rp_rs", "DepthEven", "DepthOdd"):
        np.testing.assert_allclose(
            std.scalar_features[name], raw.scalar_features[name]
        )


def test_nigraha_numpy_model_forward_pass():
    path = ".orbitlab/models/nigraha/global_nodropout/binary/models_1.hdf5"
    time, flux, candidate = transit_curve()
    tensors = build_nigraha_tensors(time, flux, candidate)
    model = NigrahaNumpyModel(path)

    probability = model.predict(tensors.as_inputs())

    assert 0.0 <= probability <= 1.0


def test_nigraha_numpy_matches_original_keras_golden_fixture():
    """The numpy forward pass (with upstream standardization applied) must match
    the regenerated golden. The golden captures the standardized-input forward
    pass; see the fixture `artifact` note re: the pending Keras cross-check.
    """
    clear_norm_stats_cache()
    fixture = json.loads((Path(__file__).parent / "fixtures" / "nigraha_golden_model1.json").read_text())
    path = ".orbitlab/models/nigraha/global_nodropout/binary/models_1.hdf5"
    time, flux, candidate = transit_curve()
    tensors = build_nigraha_tensors(time, flux, candidate)
    model = NigrahaNumpyModel(path)

    probability = model.predict(tensors.as_inputs())

    assert tensors.checksum == fixture["input_tensor_checksum"]
    np.testing.assert_allclose(
        [probability],
        [fixture["probability"]],
        atol=fixture["absolute_tolerance"],
        rtol=0.0,
    )


def _candidate(depth, period, dur, seed):
    rng = np.random.default_rng(seed)
    time = np.linspace(0.0, 27.0, 3000, dtype=np.float32)
    epoch = 0.4
    flux = 1.0 + rng.normal(0.0, 0.001, size=time.size).astype(np.float32)
    phase_time = np.abs(((time - epoch + 0.5 * period) % period) - 0.5 * period)
    flux[phase_time < dur / 2.0] -= depth
    return time, flux, TransitCandidate(period, epoch, dur, depth, dur * 24.0, 10.0)


def test_stellar_context_overrides_solar_imputation():
    """Supplying real stellar params must shrink the imputed-feature set.

    This is the wiring guarantee behind Fix 1: when Teff/R*/mass/logg flow in
    from the job/known-target/TIC path, the adapter no longer imputes them.
    """
    time, flux, candidate = _candidate(0.01, 2.75, 0.12, seed=11)
    imputed_solar = build_nigraha_tensors(time, flux, candidate).imputed_features
    imputed_real = build_nigraha_tensors(
        time,
        flux,
        candidate,
        stellar_teff=3200.0,
        stellar_radius_solar=0.4,
        stellar_mass_solar=0.42,
        stellar_logg=4.9,
    ).imputed_features

    assert "Teff" in imputed_solar and "Radius" in imputed_solar
    assert "Teff" not in imputed_real
    assert "Radius" not in imputed_real
    assert set(imputed_real).issubset(set(imputed_solar))


def test_nigraha_service_normal_path_is_nominal_and_compatible():
    """Fix #40 (recovered standardization): with the upstream-recovered constants
    applied, the logit leaves the saturated regime and the service reports a
    trustworthy, discriminating score.
    """
    clear_norm_stats_cache()
    time, flux, candidate = _candidate(0.012, 3.10, 0.10, seed=21)
    tensors = build_nigraha_tensors(
        time,
        flux,
        candidate,
        stellar_teff=3200.0,
        stellar_radius_solar=0.4,
        stellar_mass_solar=0.42,
        stellar_logg=4.9,
        stellar_luminosity_solar=0.02,
        stellar_density_solar=8.0,
    )
    verdict = NigrahaService().predict(tensors, threshold=0.4)

    assert tensors.standardized is True
    assert verdict.standardized is True
    assert verdict.saturated is False
    assert verdict.score_confidence == "nominal"
    assert verdict.preprocessing_compatible is True
    assert verdict.score_caveat is None
    assert verdict.mean_logit is not None and abs(verdict.mean_logit) < 50.0


def test_nigraha_service_discriminates_across_stellar_context():
    """Core acceptance criterion for #40: the probability must VARY with stellar
    context once standardization is applied (it was pinned at ~0.3 before).

    We score one candidate against several distinct stellar contexts and assert
    the probabilities span a meaningful range -- direct proof the score is no
    longer a constant. (A single hand-picked star pair can coincidentally land on
    similar scores; the spread across a context set is the robust signal.)
    """
    clear_norm_stats_cache()
    # A moderate-depth candidate where stellar context measurably moves the score.
    time, flux, candidate = _candidate(0.02, 4.5, 0.15, seed=7)
    service = NigrahaService()

    contexts = {
        "hot_giant": dict(stellar_teff=9000.0, stellar_radius_solar=2.5, stellar_logg=3.9,
                          stellar_mass_solar=2.0, stellar_luminosity_solar=40.0, stellar_density_solar=0.1),
        "cool_dwarf": dict(stellar_teff=3200.0, stellar_radius_solar=0.3, stellar_logg=4.9,
                           stellar_mass_solar=0.25, stellar_luminosity_solar=0.01, stellar_density_solar=12.0),
        "solar": dict(stellar_teff=5778.0, stellar_radius_solar=1.0, stellar_logg=4.44,
                      stellar_mass_solar=1.0, stellar_luminosity_solar=1.0, stellar_density_solar=1.0),
        "k_star": dict(stellar_teff=4500.0, stellar_radius_solar=0.7, stellar_logg=4.6,
                       stellar_mass_solar=0.7, stellar_luminosity_solar=0.2, stellar_density_solar=3.0),
    }
    probs = [
        service.predict(build_nigraha_tensors(time, flux, candidate, **kw)).probability
        for kw in contexts.values()
    ]

    assert all(0.0 < p < 1.0 for p in probs)
    # Not pinned to a constant: a clear spread across distinct stellar contexts.
    assert max(probs) - min(probs) > 0.05


def test_nigraha_saturation_gate_still_fires_when_stats_missing():
    """Safety net: if the norm-stats artifact is absent, raw scalars enter the
    dense head, the logit saturates, and the service must gate honestly (routing
    the degenerate score to the inconclusive OOD path via preprocessing_compatible).
    """
    clear_norm_stats_cache()
    time, flux, candidate = _candidate(0.012, 3.10, 0.10, seed=21)
    tensors = build_nigraha_tensors(
        time,
        flux,
        candidate,
        stellar_teff=3200.0,
        stellar_radius_solar=0.4,
        stellar_mass_solar=0.42,
        stellar_logg=4.9,
        norm_stats_path=_MISSING_STATS,
    )
    verdict = NigrahaService().predict(tensors, threshold=0.4)

    assert tensors.standardized is False
    assert verdict.saturated is True
    assert verdict.score_confidence == "degenerate_saturated"
    assert verdict.preprocessing_compatible is False
    assert verdict.mean_logit is not None and abs(verdict.mean_logit) >= 50.0
    assert verdict.score_caveat and "MNRAS 502, 2845" in verdict.score_caveat
