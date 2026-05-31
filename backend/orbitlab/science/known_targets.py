from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class KnownPlanetPrior:
    name: str
    period_days: float
    period_tolerance_fraction: float = 0.035
    expected_duration_days: float | None = None
    allow_planetary_secondary: bool = False


@dataclass(frozen=True)
class KnownTarget:
    canonical_name: str
    aliases: tuple[str, ...]
    planets: tuple[KnownPlanetPrior, ...]
    stellar_radius_solar: float | None = None
    stellar_mass_solar: float | None = None
    stellar_teff: float | None = None


KNOWN_TARGETS: tuple[KnownTarget, ...] = (
    KnownTarget(
        canonical_name="TRAPPIST-1",
        aliases=("TRAPPIST-1", "TRAPPIST", "TIC 278892590", "278892590"),
        stellar_radius_solar=0.1192,
        stellar_mass_solar=0.0898,
        stellar_teff=2566.0,
        planets=(
            KnownPlanetPrior("TRAPPIST-1 b", 1.51087081, expected_duration_days=0.035),
            KnownPlanetPrior("TRAPPIST-1 c", 2.4218233, expected_duration_days=0.042),
            KnownPlanetPrior("TRAPPIST-1 d", 4.04961, expected_duration_days=0.049),
            KnownPlanetPrior("TRAPPIST-1 e", 6.099615, expected_duration_days=0.056),
            KnownPlanetPrior("TRAPPIST-1 f", 9.20669, expected_duration_days=0.063),
            KnownPlanetPrior("TRAPPIST-1 g", 12.35294, expected_duration_days=0.068),
            KnownPlanetPrior("TRAPPIST-1 h", 18.767, expected_duration_days=0.075),
        ),
    ),
    KnownTarget(
        canonical_name="Kepler-10",
        aliases=("Kepler-10", "Kepler 10", "KOI-72", "KOI 72", "KIC 11904151", "11904151"),
        stellar_radius_solar=1.056,
        stellar_mass_solar=0.895,
        stellar_teff=5627.0,
        planets=(
            KnownPlanetPrior("Kepler-10 b", 0.837491331, period_tolerance_fraction=0.02),
            KnownPlanetPrior("Kepler-10 c", 45.29422297, period_tolerance_fraction=0.02),
            KnownPlanetPrior("Kepler-10 d", 151.04, period_tolerance_fraction=0.02),
        ),
    ),
    KnownTarget(
        canonical_name="HAT-P-7",
        aliases=("HAT-P-7", "HAT P 7", "Kepler-2", "Kepler 2", "KIC 10666592", "10666592"),
        stellar_radius_solar=1.84,
        stellar_mass_solar=1.47,
        stellar_teff=6350.0,
        planets=(
            KnownPlanetPrior(
                "HAT-P-7 b",
                2.204736376,
                period_tolerance_fraction=0.025,
                expected_duration_days=0.17,
                allow_planetary_secondary=True,
            ),
        ),
    ),
)


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _matches_alias(haystack: str, alias: str) -> bool:
    key = _key(alias)
    if not key:
        return False
    return haystack == key or (len(key) >= 6 and key in haystack)


def resolve_known_target(target_id: str) -> KnownTarget | None:
    haystack = _key(target_id)
    for target in KNOWN_TARGETS:
        if any(_matches_alias(haystack, alias) for alias in (target.canonical_name, *target.aliases)):
            return target
    return None


def match_known_planet(
    target: KnownTarget | None,
    period_days: float,
    *,
    tolerance_floor: float = 0.015,
) -> KnownPlanetPrior | None:
    if target is None or period_days <= 0:
        return None
    best: tuple[float, KnownPlanetPrior] | None = None
    for planet in target.planets:
        relative_delta = abs(period_days - planet.period_days) / planet.period_days
        tolerance = max(tolerance_floor, planet.period_tolerance_fraction)
        if relative_delta <= tolerance and (best is None or relative_delta < best[0]):
            best = (relative_delta, planet)
    return best[1] if best else None


def known_target_payload(target: KnownTarget | None) -> dict:
    if target is None:
        return {"status": "unmatched"}
    return {
        "status": "matched",
        "canonical_name": target.canonical_name,
        "planet_periods_days": {planet.name: planet.period_days for planet in target.planets},
    }
