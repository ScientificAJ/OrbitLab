"""Regression tests for the three Operation Friday Beta follow-up fixes.

1. Top-level depth provenance fields are declared on the TCE schema (Fix 2).
2. Analysis requests can narrow/extend the period search window, honored by the
   pipeline, with a baseline diagnostic when the long-period end is physically
   unrecoverable from the observed data span (Fix 3a + 3b).
3. The effective-stellar-context merge prefers job > known_target > catalog and
   never imputes solar defaults itself (Fix 1 wiring).
"""

from __future__ import annotations

import numpy as np
import pytest
from orbitlab.api.schemas import AnalysisJobCreate, TcePayload
from orbitlab.science.pipeline import (
    _apply_request_period_window,
    _baseline_period_note,
    _effective_stellar_context,
    analyze_light_curve_arrays,
)
from orbitlab.science.science_config import get_search_profile, load_science_config


def _tess_transit_curve(*, baseline_days=27.0, period=3.2, depth=0.012, dur=0.12, seed=3):
    rng = np.random.default_rng(seed)
    time = np.linspace(0.0, baseline_days, 4000)
    epoch = 1.0
    flux = 1.0 + rng.normal(0.0, 0.0008, size=time.size)
    phase_time = np.abs(((time - epoch + 0.5 * period) % period) - 0.5 * period)
    flux[phase_time < dur / 2.0] -= depth
    return time, flux


# --- Fix 2: top-level depth provenance --------------------------------------


def test_tce_payload_declares_top_level_depth_provenance():
    payload = TcePayload(
        candidate_id="c1",
        period=3.2,
        epoch=1.0,
        duration=0.12,
        depth=0.0005,
        signal_to_noise=10.0,
        depth_source="phase_window_median",
        model_depth_fraction=0.0005,
        measured_depth_fraction=0.00044,
    )
    assert payload.depth_source == "phase_window_median"
    assert payload.model_depth_fraction == pytest.approx(0.0005)
    assert payload.measured_depth_fraction == pytest.approx(0.00044)
    # Survives serialization (this is exactly what Pydantic was dropping before).
    dumped = payload.model_dump()
    assert dumped["depth_source"] == "phase_window_median"
    assert dumped["measured_depth_fraction"] == pytest.approx(0.00044)


def test_pipeline_surfaces_top_level_depth_provenance():
    time, flux = _tess_transit_curve()
    result = analyze_light_curve_arrays(
        target_id="provenance-check",
        mission="TESS",
        product_uri="x",
        time=time,
        flux=flux,
        vetting_mode="fast",
    )
    tce = result["tces"][0]
    assert tce["depth_source"] is not None
    assert tce["measured_depth_fraction"] is not None
    # The detection_metrics copy stays in lockstep with the top-level value.
    assert tce["depth_source"] == tce["detection_metrics"]["depth_source"]


# --- Fix 3a: honor request period bounds ------------------------------------


def test_apply_request_period_window_narrows_and_records_provenance():
    profile = get_search_profile(load_science_config(), "paper_grade")
    narrowed, request = _apply_request_period_window(
        profile, request_min_period=1.0, request_max_period=10.0
    )
    assert narrowed.min_period == pytest.approx(1.0)
    assert narrowed.max_period == pytest.approx(10.0)
    assert request["honored"] is True
    assert request["clamped"] is False
    assert request["effective_max_period_days"] == pytest.approx(10.0)


def test_apply_request_period_window_clamps_to_safety_bounds():
    profile = get_search_profile(load_science_config(), "paper_grade")
    _, request = _apply_request_period_window(
        profile, request_min_period=0.001, request_max_period=10_000.0
    )
    assert request["clamped"] is True
    assert request["effective_min_period_days"] >= 0.05
    assert request["effective_max_period_days"] <= 120.0


def test_apply_request_period_window_passthrough_when_unset():
    profile = get_search_profile(load_science_config(), "paper_grade")
    same, request = _apply_request_period_window(
        profile, request_min_period=None, request_max_period=None
    )
    assert same is profile
    assert request["honored"] is False
    assert request["effective_max_period_days"] == pytest.approx(profile.max_period)


def test_pipeline_honors_request_period_window():
    time, flux = _tess_transit_curve()
    result = analyze_light_curve_arrays(
        target_id="window-check",
        mission="TESS",
        product_uri="x",
        time=time,
        flux=flux,
        vetting_mode="fast",
        request_min_period=1.0,
        request_max_period=9.0,
    )
    window = result["period_window"]
    assert window["honored"] is True
    assert window["effective_max_period_days"] == pytest.approx(9.0)


def test_analysis_job_schema_accepts_period_bounds():
    payload = AnalysisJobCreate(
        target_id="t", product_uri="p", mission="TESS", min_period=2.0, max_period=20.0
    )
    assert payload.min_period == pytest.approx(2.0)
    assert payload.max_period == pytest.approx(20.0)


def test_analysis_job_schema_rejects_inverted_period_bounds():
    with pytest.raises(ValueError):
        AnalysisJobCreate(
            target_id="t", product_uri="p", mission="TESS", min_period=20.0, max_period=2.0
        )


# --- Fix 3b: baseline diagnostic --------------------------------------------


def test_baseline_period_note_fires_when_window_exceeds_baseline():
    note = _baseline_period_note(baseline_days=27.0, max_period=40.0, min_transits=2.0)
    assert note is not None
    assert note["status"] == "baseline_limited"
    assert note["max_recoverable_period_days"] == pytest.approx(13.5)
    assert "multi-sector" in note["note"]


def test_baseline_period_note_silent_when_window_is_recoverable():
    assert _baseline_period_note(baseline_days=27.0, max_period=10.0, min_transits=2.0) is None


def test_pipeline_emits_baseline_note_for_single_sector_long_period():
    time, flux = _tess_transit_curve(baseline_days=27.0)
    result = analyze_light_curve_arrays(
        target_id="toi700-like",
        mission="TESS",
        product_uri="x",
        time=time,
        flux=flux,
        vetting_mode="fast",
        request_max_period=40.0,
    )
    note = result["period_window_note"]
    assert note is not None
    assert note["status"] == "baseline_limited"


# --- Fix 1 wiring: effective stellar context --------------------------------


class _KnownTarget:
    stellar_teff = 5627.0
    stellar_radius_solar = 1.056
    stellar_mass_solar = 0.895


def test_effective_stellar_context_priority_job_over_known_over_catalog():
    merged, provenance = _effective_stellar_context(
        job_stellar={"teff": 6000.0, "radius_solar": None, "logg": None,
                     "mass_solar": None, "luminosity_solar": None, "density_solar": None},
        known_target=_KnownTarget(),
        catalog_stellar={"radius_solar": 0.4, "mass_solar": 0.42, "logg": 4.9},
    )
    # job wins for teff
    assert merged["teff"] == pytest.approx(6000.0)
    assert provenance["teff"] == "job_request"
    # known_target fills radius/mass (higher priority than catalog)
    assert merged["radius_solar"] == pytest.approx(1.056)
    assert provenance["radius_solar"] == "known_target"
    # catalog fills logg (neither job nor known has it)
    assert merged["logg"] == pytest.approx(4.9)
    assert provenance["logg"] == "tic_catalog"
    # nothing supplies density -> stays None, imputation deferred to the adapter
    assert merged["density_solar"] is None
    assert provenance["density_solar"] == "imputed_solar_default"


def test_effective_stellar_context_honours_density_source_hint():
    """When the catalog context supplies a density_solar_source hint (e.g.
    'derived_from_mass_radius'), the merged provenance must use that hint rather
    than the generic 'tic_catalog' label.
    """
    merged, provenance = _effective_stellar_context(
        job_stellar={"teff": None, "radius_solar": None, "logg": None,
                     "mass_solar": None, "luminosity_solar": None, "density_solar": None},
        known_target=None,
        catalog_stellar={
            "radius_solar": 1.0,
            "mass_solar": 1.0,
            "density_solar": 1.0,
            "density_solar_source": "derived_from_mass_radius",
        },
    )
    assert merged["density_solar"] == pytest.approx(1.0)
    assert provenance["density_solar"] == "derived_from_mass_radius"


def test_effective_stellar_context_tic_catalog_density_when_no_hint():
    """When the catalog returns density_solar without a source hint the provenance
    defaults to 'tic_catalog' (direct catalog measurement assumed).
    """
    merged, provenance = _effective_stellar_context(
        job_stellar={"teff": None, "radius_solar": None, "logg": None,
                     "mass_solar": None, "luminosity_solar": None, "density_solar": None},
        known_target=None,
        catalog_stellar={"density_solar": 0.5},
    )
    assert merged["density_solar"] == pytest.approx(0.5)
    assert provenance["density_solar"] == "tic_catalog"
