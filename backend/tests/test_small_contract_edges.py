from __future__ import annotations

import sys
import types

import numpy as np
import orbitlab.science.evidence as evidence_module
import orbitlab.science.tpf_diagnostics as tpf_module
import pytest
from orbitlab.api.schemas import ApertureMaskCreate, MaskCreate
from orbitlab.exceptions import RealDataRequiredError
from orbitlab.science.bls import TransitCandidate
from orbitlab.science.catalog_context import (
    _number,
    _query_nasa_archive_context,
    _table_rows,
    _text,
    query_tic_catalog_context,
    query_tic_stellar_context,
)
from orbitlab.science.data_quality import apply_manual_jitter_mask, clean_light_curve, require_real_array
from orbitlab.science.detrending import _median_cadence_days, detrend_with_wotan
from orbitlab.science.detrending_sensitivity import _finite_float, _spread, run_detrending_sensitivity
from orbitlab.science.evidence import (
    _ml_probability,
    _score_snr,
    build_candidate_evidence,
    estimate_red_noise_beta,
    phase_coverage_score,
)
from orbitlab.science.evidence_packet import build_evidence_packet_files
from orbitlab.science.folding import bin_phase_curve, phase_fold
from orbitlab.science.injection_recovery import (
    InjectionCase,
    _fractional_error,
    _period_recovered,
    inject_tls_like_transit,
    run_injection_recovery,
    summarize_recovery,
)
from orbitlab.science.known_targets import _matches_alias, match_known_planet, resolve_known_target
from orbitlab.science.physics import infer_planet_physics, kopparapu_habitable_zone
from orbitlab.science.science_config import get_search_profile, load_science_config
from orbitlab.science.sector_consistency import (
    SectorObservation,
    _observed_transit_count,
    infer_sector_id,
    summarize_sector_consistency,
)
from orbitlab.science.sector_consistency import (
    _finite_float as sector_finite_float,
)
from orbitlab.science.tls_refinement import (
    _finite_float as tls_finite_float,
)
from orbitlab.science.tls_refinement import (
    _finite_int as tls_finite_int,
)
from orbitlab.science.tls_refinement import (
    refine_with_tls,
    search_with_tls,
)
from orbitlab.science.tpf_diagnostics import (
    TpfLightCurveBundle,
    _candidate_snr_from_flux,
    _centroid,
    _centroid_series,
    aperture_stability_diagnostics,
    bundle_asdict,
    difference_image_diagnostics,
    transit_masks,
)
from orbitlab.science.tpf_diagnostics import (
    _finite_float as tpf_finite_float,
)
from orbitlab.science.tpf_diagnostics import (
    _robust_scatter as tpf_robust_scatter,
)
from orbitlab.science.triceratops_fpp import (
    _aperture_pixels,
    _bin_for_triceratops,
    parse_tess_sector,
    run_triceratops_fpp,
)
from orbitlab.science.validation import (
    _robust_scatter,
    false_positive_flags,
    odd_even_depth,
    odd_even_significance,
    secondary_eclipse_depth,
    secondary_eclipse_snr,
    validate_candidate,
)
from orbitlab.storage import database
from pydantic import ValidationError
from sqlalchemy import create_engine, text


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows
        self.colnames = list(rows[0].keys()) if rows else []

    def __iter__(self):
        return iter(self._rows)


class _ValueItemRaises:
    def item(self):
        raise ValueError("multi-value scalar")

    def __str__(self):
        return "kept-as-object-text"


def test_schema_validators_reject_negative_artifact_indices_and_empty_aperture_mask():
    with pytest.raises(ValidationError, match="artifact mask indices must be non-negative"):
        MaskCreate(target_id="TIC 1", indices=[2, -1], reason="bad cadence")

    with pytest.raises(ValidationError, match="aperture mask must be a non-empty 2D grid"):
        ApertureMaskCreate(target_id="TIC 1", product_uri="mast:uri", mask=[], reason="empty")


def test_physics_guards_invalid_inputs():
    with pytest.raises(ValueError, match="must be positive"):
        kopparapu_habitable_zone(0.0, 1.0)

    with pytest.raises(ValueError, match="depth must be non-negative"):
        infer_planet_physics(
            depth=-0.001,
            period_days=1.0,
            stellar_radius_solar=1.0,
            stellar_mass_solar=1.0,
        )


def test_folding_rejects_invalid_period_and_bin_count():
    time = np.linspace(0.0, 1.0, 8)
    flux = np.linspace(1.0, 1.01, 8)

    with pytest.raises(ValueError, match="period must be positive"):
        phase_fold(time, flux, period=0.0, epoch=0.0)

    with pytest.raises(ValueError, match="bins must be greater than 4"):
        bin_phase_curve(time, flux, bins=4)


def test_known_target_helpers_cover_empty_alias_and_no_period_match():
    assert _matches_alias("trappist1", "") is False
    assert resolve_known_target("completely unknown target") is None
    assert match_known_planet(resolve_known_target("TRAPPIST-1"), 100.0) is None


def test_catalog_context_helpers_and_stellar_lookup_edges(monkeypatch):
    from astroquery.mast import Catalogs

    rows = _FakeTable([{"ID": b"123456", "bad": _ValueItemRaises(), "blank": "--", "bad_number": "nan"}])
    payload = _table_rows(rows)
    assert payload[0]["ID"] == "123456"
    assert str(payload[0]["bad"]) == "kept-as-object-text"
    assert _number(payload[0], "missing", "bad_number", "blank") is None
    assert _number({"value": "not-number", "fallback": "2.5"}, "value", "fallback") == 2.5
    assert _text(payload[0], "missing", "blank") is None

    with pytest.raises(RuntimeError, match="numeric TIC ID"):
        _query_nasa_archive_context(None)

    monkeypatch.setattr(Catalogs, "query_object", lambda *args, **kwargs: _FakeTable([]))
    with pytest.raises(RuntimeError, match="returned no rows"):
        query_tic_stellar_context("TIC 123456")

    stellar_rows = _FakeTable(
        [
            {
                "ID": "999999",
                "Teff": "5772",
                "rad": "2.0",
                "mass": "8.0",
                "logg": "4.2",
                "lum": "3.1",
            }
        ]
    )
    monkeypatch.setattr(Catalogs, "query_object", lambda *args, **kwargs: stellar_rows)
    context = query_tic_stellar_context("TIC 123456")

    assert context["target_id"] == 999999
    assert context["query_target_id"] == 123456
    assert context["density_solar"] == pytest.approx(1.0)
    assert context["density_solar_source"] == "derived_from_mass_radius"

    matching_rows = _FakeTable(
        [
            {"ID": "not-a-number", "Teff": "bad", "rad": None, "mass": None, "rho": None},
            {
                "ID": "123456",
                "Teff": "5000",
                "rad": "0.0",
                "mass": "1.0",
                "rho": "5.5",
            },
        ]
    )
    monkeypatch.setattr(Catalogs, "query_object", lambda *args, **kwargs: matching_rows)
    matched = query_tic_stellar_context("TIC 123456")

    assert matched["target_id"] == 123456
    assert matched["density_solar"] == 5.5
    assert matched["density_solar_source"] == "tic_catalog"

    zero_radius_rows = _FakeTable([{"ID": "123456", "rad": "0.0", "mass": "1.0"}])
    monkeypatch.setattr(Catalogs, "query_object", lambda *args, **kwargs: zero_radius_rows)
    zero_radius = query_tic_stellar_context("TIC 123456")
    assert zero_radius["density_solar"] is None

    named_rows = _FakeTable([{"ID": "111111", "Teff": "4100"}])
    monkeypatch.setattr(Catalogs, "query_object", lambda *args, **kwargs: named_rows)
    named = query_tic_stellar_context("TOI-700")
    assert named["target_id"] == 111111
    assert named["query_target_id"] is None


def test_catalog_context_archive_failures_and_bad_catalog_rows(monkeypatch):
    from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive
    from astroquery.mast import Catalogs

    def fail_archive_query(*args, **kwargs):
        raise RuntimeError("archive unavailable")

    monkeypatch.setattr(NasaExoplanetArchive, "query_criteria", fail_archive_query)
    archive = _query_nasa_archive_context(123456)

    assert archive["status"] == "partial"
    assert archive["exofop_toi"]["status"] == "unavailable"
    assert archive["nasa_exoplanet_archive"]["detail"] == "archive unavailable"

    missing_coords = _FakeTable([{"ID": "123456", "Tmag": 10.0}])
    monkeypatch.setattr(Catalogs, "query_object", lambda *args, **kwargs: _FakeTable([]))
    with pytest.raises(RuntimeError, match="returned no rows"):
        query_tic_catalog_context("TIC 123456", observed_depth=0.01)

    monkeypatch.setattr(Catalogs, "query_object", lambda *args, **kwargs: missing_coords)
    with pytest.raises(RuntimeError, match="does not include coordinates"):
        query_tic_catalog_context("TIC 123456", observed_depth=0.01)

    rows = _FakeTable(
        [
            {"ID": "not-a-number", "ra": None, "dec": 21.0, "Tmag": 12.0},
            {"ID": "123456", "ra": 10.0, "dec": 20.0, "Tmag": 10.0},
            {"ID": "654321", "ra": None, "dec": 20.001, "Tmag": 9.0},
        ]
    )
    monkeypatch.setattr(Catalogs, "query_object", lambda *args, **kwargs: rows)
    context = query_tic_catalog_context("TIC 123456", observed_depth=0.0001)

    assert context["status"] == "partial"
    assert context["nearby_sources"] == [
        {
            "tic_id": "123456",
            "gaia_id": None,
            "ra": 10.0,
            "dec": 20.0,
            "separation_arcsec": 0.0,
            "tmag": 10.0,
            "delta_tmag": 0.0,
            "flux_ratio": 1.0,
            "max_diluted_eclipse_depth": 0.5,
            "can_mimic_observed_depth": False,
            "is_target": True,
        }
    ]

    named_catalog_rows = _FakeTable([{"ID": "123456", "ra": 10.0, "dec": 20.0, "Tmag": 10.0}])
    monkeypatch.setattr(Catalogs, "query_object", lambda *args, **kwargs: named_catalog_rows)
    named_context = query_tic_catalog_context("TOI-700", observed_depth=0.0001)
    assert named_context["tic"]["query_target_id"] is None

    fallback_catalog_rows = _FakeTable([{"ID": "999999", "ra": 10.0, "dec": 20.0, "Tmag": 10.0}])
    monkeypatch.setattr(Catalogs, "query_object", lambda *args, **kwargs: fallback_catalog_rows)
    fallback_context = query_tic_catalog_context("TIC 123456", observed_depth=0.0001)
    assert fallback_context["tic"]["target_id"] == 999999


def test_evidence_packet_skips_non_mapping_tce_entries():
    files = build_evidence_packet_files(
        {
            "result_id": "result-1",
            "target_id": "TIC 1",
            "mission": "TESS",
            "tces": ["not-a-tce"],
            "light_curve": {"time": [1, 2], "flux": [1.0, 0.99]},
        }
    )

    assert "manifest.json" in files
    assert not any(path.startswith("tces/") for path in files)

    with_tce = build_evidence_packet_files(
        {
            "result_id": "result-2",
            "tces": [{"candidate_id": "tce-1", "flags": []}],
            "light_curve": {},
            "periodogram": {},
        }
    )
    assert "- none" in with_tce["tces/tce-1/final_disposition.md"]

    with_flag = build_evidence_packet_files(
        {
            "result_id": "result-3",
            "tces": [
                {"candidate_id": "tce-2", "flags": [{"severity": "warning", "code": "unit", "message": "review"}]}
            ],
            "light_curve": {},
            "periodogram": {},
        }
    )
    assert "`warning` `unit`: review" in with_flag["tces/tce-2/final_disposition.md"]


def test_candidate_evidence_scoring_edges():
    candidate = TransitCandidate(period=2.0, epoch=0.0, duration=0.1, depth=0.001, power=1.0, signal_to_noise=9.0)
    config = types.SimpleNamespace(
        borderline_snr_min=5.0,
        promotion_snr=10.0,
        quality_flag_dominance_fraction=0.2,
        red_noise_warning_beta=1.1,
    )

    assert estimate_red_noise_beta(np.ones(8)) == 1.0
    assert estimate_red_noise_beta(np.zeros(80)) == 1.0
    assert estimate_red_noise_beta(np.linspace(-1.0, 1.0, 32)) >= 1.0
    assert phase_coverage_score(np.arange(8), TransitCandidate(0.0, 0.0, 0.1, 0.001, 1.0, 1.0)) == 0.0
    assert phase_coverage_score(np.array([np.nan, np.nan]), candidate) == 0.0
    assert _score_snr(float("nan"), 5.0, 10.0) == 0.0
    assert _ml_probability(None) is None
    assert _ml_probability({"calibrated_ml_probability": "bad", "probability": 1.5}) == 1.0
    assert _ml_probability({"probability": "bad"}) is None

    evidence = build_candidate_evidence(
        candidate=candidate,
        search_time=np.linspace(0.0, 8.0, 400),
        search_flux=1.0 + 0.01 * np.sin(np.linspace(0.0, 80.0, 400)),
        validation={"odd_even_sigma": 0.1, "secondary_snr": 0.1, "centroid_shift_flag": True},
        physics={"stellar_context_source": "solar_like_fallback"},
        flags=[{"severity": "warning", "code": "quality"}],
        ml={"probability": 0.8},
        observed_transits=4,
        quality_flag_fraction=0.1,
        config=config,
    )

    assert evidence.centroid_score == 0.25
    assert evidence.ml_score == 0.8
    assert "Habitability is limited by fallback stellar parameters" in evidence.explanation

    centroid_evidence = build_candidate_evidence(
        candidate=candidate,
        search_time=np.linspace(0.0, 8.0, 400),
        search_flux=1.0 + 0.001 * np.sin(np.linspace(0.0, 8.0, 400)),
        validation={"centroid_significance": 0.3},
        physics={},
        flags=[],
        ml={},
        observed_transits=1,
        quality_flag_fraction=1.0,
        config=config,
    )
    assert centroid_evidence.centroid_score > 0.66

    high_signal_evidence = build_candidate_evidence(
        candidate=TransitCandidate(period=2.0, epoch=0.0, duration=0.1, depth=0.001, power=1.0, signal_to_noise=12.0),
        search_time=np.linspace(0.0, 8.0, 400),
        search_flux=np.ones(400),
        validation={},
        physics={},
        flags=[],
        ml={"probability": "bad"},
        observed_transits=3,
        quality_flag_fraction=0.0,
        config=config,
    )
    assert high_signal_evidence.centroid_score == 1.0
    assert high_signal_evidence.ml_score is None
    assert "Recovered periodic transit-like signal" in high_signal_evidence.explanation
    assert "Red noise reduces effective SNR" not in high_signal_evidence.explanation


def test_red_noise_beta_defensive_no_usable_bins_branch(monkeypatch):
    calls = {"count": 0}
    real_isfinite = evidence_module.math.isfinite

    def reject_observed_after_white_sigma(value):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_isfinite(value)
        return False

    monkeypatch.setattr(evidence_module.math, "isfinite", reject_observed_after_white_sigma)

    assert estimate_red_noise_beta(np.linspace(-1.0, 1.0, 32)) == 1.0


def test_database_parent_helper_and_migration_paths(tmp_path, monkeypatch):
    database._ensure_database_parent("postgresql://localhost/orbitlab")
    database._ensure_database_parent("sqlite:///:memory:")
    database._ensure_database_parent("sqlite:///")

    nested_db = tmp_path / "nested" / "orbitlab.sqlite"
    database._ensure_database_parent(f"sqlite:///{nested_db}")
    assert nested_db.parent.exists()

    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(database, "engine", engine)
    database._ensure_analysis_job_columns()

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE analysis_jobs (job_id VARCHAR(64) PRIMARY KEY)"))
    database._ensure_analysis_job_columns()

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(analysis_jobs)"))}

    assert "artifact_mask_id" in columns
    assert "max_period" in columns


def test_data_quality_rejects_non_real_arrays_and_bad_shapes():
    with pytest.raises(RealDataRequiredError, match="real fetched data"):
        require_real_array("time", np.arange(4, dtype=float))

    with pytest.raises(RealDataRequiredError, match="numeric"):
        require_real_array("flux", np.array(["a"] * 8))

    with pytest.raises(RealDataRequiredError, match="no finite"):
        require_real_array("flux", np.full(8, np.nan))

    time = np.arange(8, dtype=float)
    flux = np.linspace(1.0, 1.07, 8)
    with pytest.raises(ValueError, match="same shape"):
        clean_light_curve(np.arange(9, dtype=float), flux)

    with pytest.raises(ValueError, match="quality must match"):
        clean_light_curve(time, flux, np.zeros(7))

    with pytest.raises(RealDataRequiredError, match="median is invalid"):
        clean_light_curve(time, np.array([-3.0, -2.0, -1.0, 0.0, 0.0, 1.0, 2.0, 3.0]))

    with pytest.raises(ValueError, match="identical shapes"):
        apply_manual_jitter_mask(time, flux, np.zeros(7, dtype=bool), reason="unit test")


def test_detrending_handles_default_cadence_small_inputs_and_nonfinite_outputs(monkeypatch):
    assert _median_cadence_days(np.ones(4)) == pytest.approx(1.0 / 48.0)

    fake_wotan = types.SimpleNamespace(flatten=lambda *args, **kwargs: (np.full(16, np.nan), np.ones(16)))
    monkeypatch.setitem(sys.modules, "wotan", fake_wotan)

    with pytest.raises(ValueError, match="at least 16"):
        detrend_with_wotan(np.arange(8), np.arange(8))

    with pytest.raises(ValueError, match="produced no finite"):
        detrend_with_wotan(np.arange(16), np.linspace(1.0, 1.1, 16))


def test_detrending_reports_no_trend_median_when_wotan_trend_is_nonfinite(monkeypatch):
    def flatten(*args, **kwargs):
        return np.linspace(0.99, 1.01, 16), np.full(16, np.nan)

    monkeypatch.setitem(sys.modules, "wotan", types.SimpleNamespace(flatten=flatten))

    detrended, metadata = detrend_with_wotan(np.arange(16), np.linspace(1.0, 1.1, 16))

    assert np.isfinite(detrended).all()
    assert metadata["trend_median"] is None


def test_detrending_sensitivity_private_helpers_cover_invalid_values():
    assert _finite_float(None) is None
    assert _finite_float("not-a-number") is None
    assert _finite_float(float("inf")) is None
    assert _spread([1.0]) is None
    assert _spread([0.0, 0.0]) is None


def test_detrending_sensitivity_reports_insufficient_and_inconclusive(monkeypatch):
    candidate = TransitCandidate(period=2.0, epoch=0.0, duration=0.1, depth=0.001, power=1.0, signal_to_noise=8.0)

    short = run_detrending_sensitivity(np.arange(16), np.linspace(1.0, 1.1, 16), candidate)
    assert short["status"] == "insufficient_data"

    def fail_detrend(*args, **kwargs):
        raise ImportError("wotan unavailable")

    def fail_bls(*args, **kwargs):
        raise ValueError("no detectable signal")

    monkeypatch.setattr("orbitlab.science.detrending_sensitivity.detrend_with_wotan", fail_detrend)
    monkeypatch.setattr("orbitlab.science.detrending_sensitivity.run_bls", fail_bls)

    inconclusive = run_detrending_sensitivity(
        np.linspace(0.0, 10.0, 128),
        np.linspace(1.0, 1.02, 128),
        candidate,
        window_lengths_days=(0.5,),
    )

    assert inconclusive["status"] == "inconclusive"
    assert {method["status"] for method in inconclusive["methods"]} == {"failed"}


def test_science_config_reports_unknown_profile_and_inactive_keys(tmp_path):
    config = load_science_config()
    with pytest.raises(ValueError, match="unknown search profile"):
        get_search_profile(config, "not-a-profile")

    config_path = tmp_path / "science_config.toml"
    config_path.write_text(
        """
promotion_snr = 8
borderline_snr_min = 5
aperture_percentiles = [85]
max_duration_period_ratio = 0.2
secondary_eclipse_hard_fail_snr = 5
odd_even_hard_fail_sigma = 4
centroid_hard_fail_pixels = 1
quality_flag_dominance_fraction = 0.3
red_noise_warning_beta = 2
forced_period_tolerance_fraction = 0.05
paper_promotion_snr = 10
paper_tls_sde_min = 7
paper_min_transits = 3
paper_ml_threshold = 0.5
paper_sweet_sigma = 3
paper_model_shift_objects = 2
paper_triceratops_fpp_max = 0.01
paper_triceratops_nfpp_max = 0.001
paper_triceratops_samples = 100
paper_catalog_radius_arcsec = 2
unused_future_knob = 1

[search_profiles.fast]
min_period = 0.5
max_period = 10
period_samples = 32
max_period_samples = 64
min_transits = 2
max_search_cadences = 1000
warning = "fast"
""",
        encoding="utf-8",
    )

    from orbitlab.science.science_config import config_usage_audit

    audit = config_usage_audit(config_path)
    assert audit["inactive_science_config_keys"] == ["unused_future_knob"]


def test_validation_helpers_cover_low_information_and_flag_fallback_paths():
    candidate = TransitCandidate(period=2.0, epoch=0.0, duration=0.01, depth=0.001, power=1.0, signal_to_noise=8.0)
    sparse_time = np.array([0.0, 0.2, 0.4, 0.8])
    flat_flux = np.ones_like(sparse_time)

    assert np.isnan(_robust_scatter(np.array([np.nan, np.nan])))
    assert np.isnan(_robust_scatter(np.ones(5)))
    assert np.isnan(odd_even_depth(sparse_time, flat_flux, candidate))
    finite_candidate = TransitCandidate(
        period=2.0,
        epoch=0.0,
        duration=0.2,
        depth=0.001,
        power=1.0,
        signal_to_noise=8.0,
    )
    finite_time = np.linspace(0.0, 8.0, 400)
    finite_flux = np.ones_like(finite_time)
    phase_time = np.abs(
        ((finite_time - finite_candidate.epoch + 0.5 * finite_candidate.period) % finite_candidate.period)
        - 0.5 * finite_candidate.period
    )
    finite_flux[phase_time < finite_candidate.duration / 2] -= finite_candidate.depth
    assert odd_even_depth(finite_time, finite_flux, finite_candidate) >= 0.0
    assert odd_even_significance(0.001, 0.002, float("nan"), 0.0) is None
    assert np.isnan(secondary_eclipse_depth(sparse_time, flat_flux, candidate))
    assert secondary_eclipse_snr(sparse_time, flat_flux, candidate) is None

    flags = false_positive_flags(
        candidate=candidate,
        odd_even_delta=0.001,
        odd_even_sigma=None,
        secondary_depth=0.001,
        secondary_snr=None,
        duration_ok=True,
        harmonic=False,
        centroid_shift_pixels=0.1,
        centroid_significance=2.1,
        sap_pdcsap_agreement=0.2,
    )

    assert "odd_even_depth_mismatch" in flags
    assert "secondary_eclipse" in flags
    assert "centroid_shift" in flags
    assert "sap_pdcsap_disagreement" in flags


def test_validate_candidate_reports_centroid_significance_and_sap_pdcsap_agreement():
    time = np.linspace(0.0, 12.0, 300)
    flux = 1.0 + 0.0001 * np.sin(time)
    candidate = TransitCandidate(period=2.0, epoch=0.1, duration=0.08, depth=0.002, power=8.0, signal_to_noise=9.0)

    result = validate_candidate(
        time,
        flux,
        candidate,
        sap_flux=flux,
        pdcsap_flux=flux[::-1],
        centroid_shift_pixels=0.5,
        centroid_uncertainty_pixels=0.2,
    )

    assert result.centroid_significance == pytest.approx(2.5)
    assert result.centroid_shift_flag is True
    assert result.sap_pdcsap_agreement is not None


def test_tpf_diagnostics_cover_unavailable_insufficient_and_null_centroid_paths():
    candidate = TransitCandidate(period=2.0, epoch=0.0, duration=0.2, depth=0.01, power=12.0, signal_to_noise=9.0)
    invalid_candidate = TransitCandidate(
        period=0.0, epoch=0.0, duration=0.2, depth=0.01, power=1.0, signal_to_noise=1.0
    )
    time = np.linspace(0.0, 4.0, 80)

    assert tpf_finite_float(None) is None
    assert tpf_finite_float(float("inf")) is None
    assert np.isnan(tpf_robust_scatter(np.array([np.nan, np.nan])))
    assert np.isnan(tpf_robust_scatter(np.ones(5)))
    in_transit, out_of_transit = transit_masks(time, invalid_candidate)
    assert not in_transit.any()
    assert out_of_transit.all()
    assert _centroid(np.full((2, 2), np.nan)) is None
    assert _centroid(np.ones((2, 2))) is None
    rows, cols = _centroid_series(np.full((3, 2, 2), np.nan), np.array([True, True, True]))
    assert rows.size == 0
    assert cols.size == 0

    assert difference_image_diagnostics(time=time, pixel_flux=None, candidate=candidate)["status"] == "unavailable"
    bad_shape = difference_image_diagnostics(time=time, pixel_flux=np.ones((4, 2, 2)), candidate=candidate)
    assert bad_shape["reason"] == "target pixel flux cube shape does not match time array"
    sparse = difference_image_diagnostics(
        time=np.array([0.0, 0.05, 0.1]), pixel_flux=np.ones((3, 2, 2)), candidate=candidate
    )
    assert sparse["status"] == "insufficient_data"

    flat_cube = np.ones((time.size, 2, 2))
    no_peak = difference_image_diagnostics(time=time, pixel_flux=flat_cube, candidate=candidate)
    assert no_peak["status"] == "complete"
    assert "peak_pixel" not in no_peak
    assert no_peak["centroid_shift_pixels"] is None

    assert aperture_stability_diagnostics(time=time, pixel_flux=None, candidate=candidate)["status"] == "unavailable"
    assert (
        aperture_stability_diagnostics(time=time, pixel_flux=np.ones((4, 2, 2)), candidate=candidate)["reason"]
        == "target pixel flux cube shape does not match time array"
    )
    no_finite = aperture_stability_diagnostics(
        time=time, pixel_flux=np.full((time.size, 2, 2), np.nan), candidate=candidate
    )
    assert no_finite["reason"] == "median target pixel image has no finite pixels"
    no_snr = aperture_stability_diagnostics(
        time=time,
        pixel_flux=flat_cube,
        candidate=candidate,
        selected_mask=np.zeros((2, 2), dtype=bool),
        percentiles=(50, 50),
    )
    assert no_snr["status"] == "insufficient_data"
    assert _candidate_snr_from_flux(np.array([0.0]), np.array([1.0]), candidate) is None
    bundle = TpfLightCurveBundle(time, np.ones_like(time), None, None, None, None, None, None, None, None)
    assert np.array_equal(bundle_asdict(bundle)["time"], time)


def test_tpf_diagnostics_cover_centroid_uncertainty_and_aperture_branch_edges(monkeypatch):
    candidate = TransitCandidate(period=2.0, epoch=0.0, duration=0.5, depth=0.01, power=12.0, signal_to_noise=9.0)
    time = np.array([0.0, 0.1, 0.6, 0.8])
    in_image = np.array([[1.0, 1.0], [1.0, 4.0]])
    out_image = np.array([[1.0, 1.0], [5.0, 1.0]])
    cube = np.stack([in_image, np.full((2, 2), np.nan), out_image, np.full((2, 2), np.nan)])

    diagnostics = difference_image_diagnostics(time=time, pixel_flux=cube, candidate=candidate, pixel_scale_arcsec=None)

    assert diagnostics["status"] == "complete"
    assert diagnostics["centroid_uncertainty_pixels"] == 0.0
    assert diagnostics["centroid_significance"] is None

    rich_time = np.linspace(0.0, 10.0, 500)
    rich_candidate = TransitCandidate(period=2.0, epoch=0.0, duration=0.2, depth=0.01, power=12.0, signal_to_noise=9.0)
    rich_cube = np.ones((rich_time.size, 3, 3)) * 1000.0
    rich_cube[:, 1, 1] += 500.0
    rich_cube += np.random.default_rng(17).normal(0.0, 2.0, size=rich_cube.shape)
    phase = ((rich_time - rich_candidate.epoch + 0.5 * rich_candidate.period) % rich_candidate.period) - (
        0.5 * rich_candidate.period
    )
    rich_cube[np.abs(phase) <= 0.5 * rich_candidate.duration, 1, 1] -= 80.0
    percentile_only = aperture_stability_diagnostics(
        time=rich_time,
        pixel_flux=rich_cube,
        candidate=rich_candidate,
        selected_mask=None,
        percentiles=(70, 80, 90),
    )

    assert percentile_only["status"] == "complete"
    assert all(row["mask"] != "selected" for row in percentile_only["apertures"])

    monkeypatch.setattr(tpf_module.np, "nanpercentile", lambda *args, **kwargs: float("inf"))
    no_masks = aperture_stability_diagnostics(
        time=rich_time,
        pixel_flux=np.ones((rich_time.size, 2, 2)),
        candidate=rich_candidate,
        selected_mask=None,
        percentiles=(50,),
    )
    assert no_masks["status"] == "insufficient_data"
    assert no_masks["apertures"] == []


def test_sector_consistency_cover_parsers_failures_and_insufficient_paths(monkeypatch):
    candidate = TransitCandidate(period=2.0, epoch=0.1, duration=0.1, depth=0.002, power=9.0, signal_to_noise=10.0)

    assert infer_sector_id(None, fallback="fallback-sector") == "fallback-sector"
    assert infer_sector_id("no-sector-here", fallback="fallback-sector") == "fallback-sector"
    assert sector_finite_float("bad") is None
    assert sector_finite_float(float("nan")) is None
    assert _observed_transit_count(np.arange(4), TransitCandidate(0.0, 0.0, 0.1, 0.001, 1.0, 1.0)) == 0
    assert _observed_transit_count(np.array([np.nan, np.nan]), candidate) == 0
    assert summarize_sector_consistency(candidate, [])["multi_sector_status"] == "insufficient_data"

    short_observations = [
        SectorObservation(sector_id="1", time=np.arange(10), flux=np.ones(10)),
        SectorObservation(sector_id="2", time=np.arange(10), flux=np.ones(10)),
    ]
    assert summarize_sector_consistency(candidate, short_observations)["status"] == "insufficient_data"

    def fail_bls(*args, **kwargs):
        raise RuntimeError("search failed")

    monkeypatch.setattr("orbitlab.science.sector_consistency.run_bls", fail_bls)
    failed = summarize_sector_consistency(
        candidate,
        [
            SectorObservation(sector_id="1", time=np.linspace(0.0, 8.0, 128), flux=np.ones(128)),
            SectorObservation(sector_id="2", time=np.linspace(0.0, 8.0, 128), flux=np.ones(128)),
        ],
    )
    assert failed["status"] == "insufficient_data"
    assert failed["sector_evidence"][0]["status"] == "failed"


def test_triceratops_parsers_binning_and_aperture_guards():
    assert parse_tess_sector(None) is None
    assert parse_tess_sector("no-sector-here") is None
    assert _aperture_pixels(None) is None
    assert _aperture_pixels(np.zeros((2, 2), dtype=bool)) is None
    assert _aperture_pixels(np.array([True, False])) is None

    with pytest.raises(ValueError, match="at least 16"):
        _bin_for_triceratops(np.arange(8), np.ones(8))

    with pytest.raises(ValueError, match="flux error estimate"):
        _bin_for_triceratops(np.linspace(-1.0, 1.0, 32), np.ones(32))


def test_triceratops_wrapper_reports_input_errors_and_calc_depths_detail(monkeypatch):
    class _FakeTarget:
        FPP = 0.3
        NFPP = 0.03
        probs = object()

        def __init__(self, *, ID, sectors):
            self.ID = ID
            self.sectors = sectors

        def calc_depths(self, **kwargs):
            raise RuntimeError("depth geometry unavailable")

        def calc_probs(self, **kwargs):
            self.kwargs = kwargs

    fake_module = types.SimpleNamespace(target=_FakeTarget)
    monkeypatch.setitem(sys.modules, "triceratops", types.ModuleType("triceratops"))
    monkeypatch.setitem(sys.modules, "triceratops.triceratops", fake_module)

    time = np.linspace(0.0, 12.0, 300)
    flux = 1.0 + np.random.default_rng(3).normal(0.0, 1e-4, size=time.size)
    candidate = TransitCandidate(period=2.0, epoch=0.1, duration=0.08, depth=0.002, power=8.0, signal_to_noise=9.0)

    with pytest.raises(ValueError, match="numeric TIC"):
        run_triceratops_fpp(
            target_id="Kepler-10",
            product_uri="tess-s0007-target.fits",
            time=time,
            flux=flux,
            candidate=candidate,
        )

    with pytest.raises(ValueError, match="TESS sector"):
        run_triceratops_fpp(target_id="TIC 12345", product_uri=None, time=time, flux=flux, candidate=candidate)

    result = run_triceratops_fpp(
        target_id="TIC 12345",
        product_uri="tess-s0007-target.fits",
        time=time,
        flux=flux,
        candidate=candidate,
        aperture_mask=np.array([[True, False], [False, False]]),
        samples=10,
        parallel=True,
    )

    assert result["calc_depths_used"] is False
    assert result["calc_depths_detail"] == "depth geometry unavailable"
    assert result["probabilities"] is None
    assert result["parallel"] is True
    assert result["source"] == "TRICERATOPS calc_probs"

    no_aperture = run_triceratops_fpp(
        target_id="TIC 12345",
        product_uri="tess-s0007-target.fits",
        time=time,
        flux=flux,
        candidate=candidate,
        aperture_mask=None,
        samples=10,
    )
    assert no_aperture["aperture_used"] is False
    assert no_aperture["calc_depths_used"] is False


def test_tls_refinement_failure_modes_and_optional_search_parameters(monkeypatch):
    class _FailingTls:
        def __init__(self, time, flux):
            self.time = time
            self.flux = flux

        def power(self, **kwargs):
            raise RuntimeError("tls failed")

    monkeypatch.setitem(
        sys.modules,
        "transitleastsquares",
        types.SimpleNamespace(transitleastsquares=_FailingTls),
    )
    candidate = TransitCandidate(period=2.0, epoch=0.1, duration=0.08, depth=0.002, power=8.0, signal_to_noise=9.0)

    assert refine_with_tls(np.arange(32), np.ones(32), candidate)["status"] == "failed"
    failed = search_with_tls(np.arange(32), np.ones(32), min_period=0.01, max_period=3.0)
    assert failed["status"] == "failed"

    class _RecordingResults:
        period = None
        duration = None
        T0 = None
        depth = None
        snr = "bad-snr"
        SDE = float("nan")
        SDE_raw = None
        FAP = None
        transit_count = None
        distinct_transit_count = "bad-count"
        period_uncertainty = None

    class _RecordingTls:
        seen_kwargs = None

        def __init__(self, time, flux):
            self.time = time
            self.flux = flux

        def power(self, **kwargs):
            _RecordingTls.seen_kwargs = kwargs
            return _RecordingResults()

    monkeypatch.setitem(
        sys.modules,
        "transitleastsquares",
        types.SimpleNamespace(transitleastsquares=_RecordingTls),
    )

    complete = search_with_tls(
        np.arange(32, dtype=float),
        np.linspace(1.0, 1.01, 32),
        min_period=0.01,
        max_period=3.0,
        stellar_radius_solar=0.0,
        stellar_mass_solar=-1.0,
    )

    assert complete["status"] == "complete"
    assert complete["period_range"]["min"] == 0.05
    assert complete["periodogram_period_count"] is None
    assert "R_star" not in _RecordingTls.seen_kwargs
    assert "M_star" not in _RecordingTls.seen_kwargs

    complete_with_stellar_params = search_with_tls(
        np.arange(32, dtype=float),
        np.linspace(1.0, 1.01, 32),
        min_period=0.5,
        max_period=3.0,
        stellar_radius_solar=1.1,
        stellar_mass_solar=0.9,
    )
    assert complete_with_stellar_params["status"] == "complete"
    assert _RecordingTls.seen_kwargs["R_star"] == 1.1
    assert _RecordingTls.seen_kwargs["M_star"] == 0.9
    assert tls_finite_float("bad") is None
    assert tls_finite_float(float("nan")) is None
    assert tls_finite_int(None) is None


def test_tls_search_reports_unavailable_and_small_finite_input(monkeypatch):
    real_tls = sys.modules.pop("transitleastsquares", None)
    monkeypatch.setitem(sys.modules, "transitleastsquares", None)
    try:
        unavailable = search_with_tls(np.arange(32), np.ones(32), min_period=1.0, max_period=2.0)
    finally:
        if real_tls is not None:
            sys.modules["transitleastsquares"] = real_tls
        else:
            sys.modules.pop("transitleastsquares", None)
    assert unavailable["status"] == "unavailable"

    class _NoopTls:
        def __init__(self, time, flux):
            self.time = time
            self.flux = flux

        def power(self, **kwargs):
            raise AssertionError("small input should fail before TLS power")

    monkeypatch.setitem(sys.modules, "transitleastsquares", types.SimpleNamespace(transitleastsquares=_NoopTls))

    failed = search_with_tls(np.arange(8), np.ones(8), min_period=1.0, max_period=2.0)
    assert failed["status"] == "failed"
    assert "at least 16" in failed["detail"]


def test_injection_recovery_edge_helpers_and_skipped_grid(monkeypatch):
    assert _period_recovered(None, 2.0, 0.1) is False
    assert _period_recovered(1.0, 2.0, 0.02) is True
    assert _period_recovered(4.0, 2.0, 0.02) is True
    assert _fractional_error(None, 2.0) is None
    assert _fractional_error(1.0, 0.0) is None

    time = np.linspace(0.0, 1.0, 64)
    flux = np.ones_like(time)
    unchanged = inject_tls_like_transit(
        time, flux, period_days=100.0, depth_ppm=1000, duration_hours=0.1, epoch_days=50
    )
    assert np.array_equal(unchanged, flux.astype(np.float32))

    summary = summarize_recovery(
        [
            InjectionCase(2.0, 100.0, 1.0, "box", True, 2.0, 0.0, 9.0),
            InjectionCase(2.0, 300.0, 1.0, "box", False, None, None, None, failed_gate=None),
        ]
    )
    assert summary["failed_gate_counts"] == {"not_recovered": 1}

    skipped = run_injection_recovery(
        time,
        flux,
        period_days=(100.0,),
        depth_ppm=(100.0,),
        duration_hours=(1.0,),
    )
    assert skipped["status"] == "skipped"

    def fail_bls(*args, **kwargs):
        raise ValueError("no recovery")

    recovery_time = np.linspace(0.0, 10.0, 128)
    monkeypatch.setattr("orbitlab.science.injection_recovery.run_bls", fail_bls)
    failed = run_injection_recovery(
        recovery_time,
        1.0 + 0.001 * np.sin(recovery_time),
        period_days=(2.0,),
        depth_ppm=(500.0,),
        duration_hours=(2.0,),
    )
    assert failed["cases"][0]["failed_gate"] == "ValueError"
