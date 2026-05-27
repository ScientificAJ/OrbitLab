import math

import numpy as np
import pytest
from orbitlab.science.bls import TransitCandidate
from orbitlab.science.physics import infer_planet_physics
from orbitlab.science.validation import validate_candidate


def test_physics_inference_for_earth_sun_like_case():
    earth_sun_depth = (0.0091577) ** 2
    physics = infer_planet_physics(
        depth=earth_sun_depth,
        period_days=365.25,
        stellar_radius_solar=1.0,
        stellar_mass_solar=1.0,
        depth_uncertainty=earth_sun_depth * 0.1,
        stellar_radius_uncertainty_solar=0.02,
        stellar_mass_uncertainty_solar=0.03,
    )

    assert math.isclose(physics.radius_ratio, 0.0091577, rel_tol=1e-6)
    assert math.isclose(physics.planet_radius_earth, 1.0, rel_tol=0.02)
    assert math.isclose(physics.semi_major_axis_au, 1.0, rel_tol=0.01)
    assert physics.planet_radius_uncertainty_earth is not None
    assert physics.semi_major_axis_uncertainty_au is not None


def test_kopparapu_habitable_zone_uses_paper_coefficients_for_solar_case():
    earth_sun_depth = (0.0091577) ** 2
    physics = infer_planet_physics(
        depth=earth_sun_depth,
        period_days=365.25,
        stellar_radius_solar=1.0,
        stellar_mass_solar=1.0,
        stellar_teff=5778.0,
    )

    hz = physics.kopparapu_hz
    assert hz is not None
    assert hz["within_calibrated_teff_range"] is True
    assert hz["conservative_inner_au"] == pytest.approx(0.950, rel=0.01)
    assert hz["conservative_outer_au"] == pytest.approx(1.676, rel=0.01)
    assert physics.is_in_habitable_zone is True


def test_validation_flags_common_false_positive_risks():
    candidate = TransitCandidate(
        period=5.0,
        epoch=0.0,
        duration=0.2,
        depth=0.001,
        power=10.0,
        signal_to_noise=5.0,
    )
    time = np.linspace(0, 20, 400)
    flux = np.ones_like(time)
    phase = ((time - candidate.epoch) % candidate.period) / candidate.period
    flux[np.abs(phase - 0.5) < candidate.duration / candidate.period / 2] = 0.998

    validation = validate_candidate(
        time,
        flux,
        candidate,
        centroid_shift_pixels=1.5,
        stellar_rotation_period=5.0,
    )

    assert validation.centroid_shift_flag is True
    assert "low_snr" in validation.false_positive_flags
    assert "secondary_eclipse" in validation.false_positive_flags
    assert "stellar_rotation_harmonic" in validation.false_positive_flags
    assert "centroid_shift" in validation.false_positive_flags
