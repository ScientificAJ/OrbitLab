from __future__ import annotations

import math
from dataclasses import dataclass

G = 6.67430e-11
DAY = 86400.0
SOLAR_RADIUS = 6.957e8
SOLAR_MASS = 1.98847e30
EARTH_RADIUS = 6.371e6
AU = 1.495978707e11


@dataclass(frozen=True)
class PlanetPhysics:
    radius_ratio: float
    planet_radius_earth: float
    planet_radius_uncertainty_earth: float | None
    semi_major_axis_au: float
    semi_major_axis_uncertainty_au: float | None
    equilibrium_temperature_k: float | None
    habitable_zone_inner_au: float | None
    habitable_zone_outer_au: float | None
    is_in_habitable_zone: bool | None
    is_temperature_habitable: bool | None
    kopparapu_hz: dict[str, float | str | bool | None] | None


KOPPARAPU_2014_1ME_COEFFICIENTS = {
    "recent_venus": (1.776, 2.136e-4, 2.533e-8, -1.332e-11, -3.097e-15),
    "runaway_greenhouse": (1.107, 1.332e-4, 1.580e-8, -8.308e-12, -1.931e-15),
    "maximum_greenhouse": (0.356, 6.171e-5, 1.698e-9, -3.198e-12, -5.575e-16),
    "early_mars": (0.320, 5.547e-5, 1.526e-9, -2.874e-12, -5.011e-16),
}


def _kopparapu_effective_flux(stellar_teff: float, coefficients: tuple[float, float, float, float, float]) -> float:
    teff_offset = stellar_teff - 5780.0
    seff_sun, a, b, c, d = coefficients
    return seff_sun + a * teff_offset + b * teff_offset**2 + c * teff_offset**3 + d * teff_offset**4


def kopparapu_habitable_zone(stellar_teff: float, luminosity_solar: float) -> dict[str, float | str | bool | None]:
    if stellar_teff <= 0 or luminosity_solar <= 0:
        raise ValueError("stellar_teff and luminosity_solar must be positive")
    distances = {}
    fluxes = {}
    for name, coefficients in KOPPARAPU_2014_1ME_COEFFICIENTS.items():
        seff = _kopparapu_effective_flux(stellar_teff, coefficients)
        fluxes[f"{name}_seff"] = seff
        distances[f"{name}_au"] = math.sqrt(luminosity_solar / seff) if seff > 0 else None
    return {
        "model": "Kopparapu et al. 2014 1ME polynomial",
        "calibrated_teff_min_k": 2600.0,
        "calibrated_teff_max_k": 7200.0,
        "within_calibrated_teff_range": 2600.0 <= stellar_teff <= 7200.0,
        "conservative_inner_au": distances["runaway_greenhouse_au"],
        "conservative_outer_au": distances["maximum_greenhouse_au"],
        "optimistic_inner_au": distances["recent_venus_au"],
        "optimistic_outer_au": distances["early_mars_au"],
        **distances,
        **fluxes,
    }


def infer_planet_physics(
    *,
    depth: float,
    period_days: float,
    stellar_radius_solar: float,
    stellar_mass_solar: float,
    stellar_teff: float | None = None,
    depth_uncertainty: float | None = None,
    stellar_radius_uncertainty_solar: float | None = None,
    stellar_mass_uncertainty_solar: float | None = None,
) -> PlanetPhysics:
    if depth < 0 or period_days <= 0 or stellar_radius_solar <= 0 or stellar_mass_solar <= 0:
        raise ValueError("depth must be non-negative, and period, stellar radius, and stellar mass must be positive")
    radius_ratio = math.sqrt(depth)
    planet_radius_m = stellar_radius_solar * SOLAR_RADIUS * radius_ratio
    planet_radius_earth = planet_radius_m / EARTH_RADIUS
    period_seconds = period_days * DAY
    semi_major_axis_m = (G * stellar_mass_solar * SOLAR_MASS * period_seconds**2 / (4 * math.pi**2)) ** (1 / 3)
    semi_major_axis_au = semi_major_axis_m / AU

    radius_unc = None
    if depth_uncertainty is not None or stellar_radius_uncertainty_solar is not None:
        rel_depth = 0.5 * (depth_uncertainty or 0.0) / depth
        rel_radius = (stellar_radius_uncertainty_solar or 0.0) / stellar_radius_solar
        radius_unc = planet_radius_earth * math.sqrt(rel_depth**2 + rel_radius**2)

    axis_unc = None
    if stellar_mass_uncertainty_solar is not None:
        axis_unc = semi_major_axis_au * abs(stellar_mass_uncertainty_solar / stellar_mass_solar) / 3.0

    teq = None
    hz_inner = None
    hz_outer = None
    in_hz = None
    temp_habitable = None
    kopparapu_hz = None

    if stellar_teff and stellar_radius_solar:
        # Stefan-Boltzmann for luminosity L = 4pi R^2 sigma T^4
        # L_solar = 1.0 (relative)
        luminosity_solar = (stellar_radius_solar**2) * (stellar_teff / 5778.0)**4
        
        # Teq = Teff * sqrt(Rs / 2a) * (1 - A)^1/4. Assume A=0.3
        # Rs in AU
        rs_au = (stellar_radius_solar * SOLAR_RADIUS) / AU
        teq = stellar_teff * math.sqrt(rs_au / (2.0 * semi_major_axis_au)) * (0.7**0.25)
        
        kopparapu_hz = kopparapu_habitable_zone(stellar_teff, luminosity_solar)
        hz_inner = kopparapu_hz["conservative_inner_au"]
        hz_outer = kopparapu_hz["conservative_outer_au"]
        in_hz = hz_inner <= semi_major_axis_au <= hz_outer
        temp_habitable = 200.0 <= teq <= 340.0

    return PlanetPhysics(
        radius_ratio=radius_ratio,
        planet_radius_earth=planet_radius_earth,
        planet_radius_uncertainty_earth=radius_unc,
        semi_major_axis_au=semi_major_axis_au,
        semi_major_axis_uncertainty_au=axis_unc,
        equilibrium_temperature_k=teq,
        habitable_zone_inner_au=hz_inner,
        habitable_zone_outer_au=hz_outer,
        is_in_habitable_zone=in_hz,
        is_temperature_habitable=temp_habitable,
        kopparapu_hz=kopparapu_hz,
    )
