import math

from orbitlab.science.physics import infer_planet_physics


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

