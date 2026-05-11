from __future__ import annotations

from dataclasses import dataclass
import math

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

    if stellar_teff and stellar_radius_solar:
        # Stefan-Boltzmann for luminosity L = 4pi R^2 sigma T^4
        # L_solar = 1.0 (relative)
        luminosity_solar = (stellar_radius_solar**2) * (stellar_teff / 5778.0)**4
        
        # Teq = Teff * sqrt(Rs / 2a) * (1 - A)^1/4. Assume A=0.3
        # Rs in AU
        rs_au = (stellar_radius_solar * SOLAR_RADIUS) / AU
        teq = stellar_teff * math.sqrt(rs_au / (2.0 * semi_major_axis_au)) * (0.7**0.25)
        
        # Simple HZ boundaries (Kopparapu et al. 2013 simplified)
        hz_inner = math.sqrt(luminosity_solar / 1.1)
        hz_outer = math.sqrt(luminosity_solar / 0.53)
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
    )

