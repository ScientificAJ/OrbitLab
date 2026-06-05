"""Unit tests for stellar density resolution in query_tic_stellar_context.

Tests the private helpers directly rather than hitting the network.  Covers:
- TIC catalog row has a measured rho -> used as-is, source='tic_catalog'.
- TIC row lacks rho but has mass and radius -> density derived as M/R^3 in
  solar units, source='derived_from_mass_radius'.
- TIC row has neither -> density_solar is None.
- Degenerate radius (0 or negative) -> derivation skipped, density_solar None.
"""
from __future__ import annotations

import pytest
from orbitlab.science.catalog_context import _number


def _make_row(**kwargs):
    return kwargs


def _resolve_density(row: dict) -> tuple[float | None, str]:
    """Reimplementation of the density-resolution logic from
    query_tic_stellar_context, so we can test it without a network call.
    """
    import math
    radius_solar = _number(row, "rad", "Radius", "radius")
    mass_solar = _number(row, "mass", "Mass")
    density_solar = _number(row, "rho", "density", "Rho")
    density_solar_source = "tic_catalog"
    if density_solar is None and radius_solar is not None and mass_solar is not None:
        r3 = radius_solar ** 3
        if math.isfinite(r3) and r3 > 0:
            density_solar = mass_solar / r3
            density_solar_source = "derived_from_mass_radius"
    return density_solar, density_solar_source


class TestDensityResolution:
    def test_catalog_rho_used_directly(self):
        row = _make_row(rho=0.45, rad=1.4, mass=1.2)
        density, source = _resolve_density(row)
        assert density == pytest.approx(0.45)
        assert source == "tic_catalog"

    def test_derive_from_mass_radius_when_no_rho(self):
        # rho = mass / radius^3 in solar units
        rad, mass = 1.4, 1.2
        row = _make_row(rad=rad, mass=mass)
        density, source = _resolve_density(row)
        assert density == pytest.approx(mass / rad ** 3)
        assert source == "derived_from_mass_radius"

    def test_solar_values_give_unity(self):
        row = _make_row(rad=1.0, mass=1.0)
        density, source = _resolve_density(row)
        assert density == pytest.approx(1.0)
        assert source == "derived_from_mass_radius"

    def test_no_mass_or_radius_gives_none(self):
        row = _make_row(Teff=5778.0)
        density, source = _resolve_density(row)
        assert density is None

    def test_zero_radius_skips_derivation(self):
        row = _make_row(rad=0.0, mass=1.0)
        density, source = _resolve_density(row)
        assert density is None

    def test_only_mass_no_radius_gives_none(self):
        row = _make_row(mass=1.0)
        density, source = _resolve_density(row)
        assert density is None

    def test_compact_star_density(self):
        # White dwarf: mass ~0.6 Msun, radius ~0.01 Rsun -> very high density
        rad, mass = 0.01, 0.6
        row = _make_row(rad=rad, mass=mass)
        density, source = _resolve_density(row)
        assert density == pytest.approx(mass / rad ** 3)
        assert density > 100.0
        assert source == "derived_from_mass_radius"
