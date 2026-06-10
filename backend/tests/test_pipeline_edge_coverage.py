from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import orbitlab.science.pipeline as pipeline
import pytest
from orbitlab.exceptions import ModelArtifactError
from orbitlab.science.bls import BlsResult, TransitCandidate
from orbitlab.science.pipeline import (
    _add_flag,
    _apply_paper_grade_vetting,
    _apply_request_period_window,
    _attach_ml_domain_evidence,
    _baseline_period_note,
    _cadence_days_from_time,
    _candidate_duplicate,
    _candidate_science_readiness,
    _data_quality_payload,
    _disposition,
    _ml_payload_for_candidate,
    _observed_transit_count,
    _paper_grade_status_from_flags,
    _payload_dict,
    _period_alias_code,
    _resolve_secondary_period_alias,
    _structured_flags,
    _summarize_science_readiness,
    _tls_primary_candidate,
)
from orbitlab.science.science_config import get_search_profile, load_science_config
from orbitlab.science.validation import ValidationMetrics


def _candidate(period=2.0, snr=8.0, duration=0.1, depth=0.001):
    return TransitCandidate(period=period, epoch=0.1, duration=duration, depth=depth, power=9.0, signal_to_noise=snr)


def _analysis_time_flux() -> tuple[np.ndarray, np.ndarray]:
    time = np.linspace(0.0, 12.0, 240)
    flux = 1.0 + 0.0001 * np.sin(time * 1.7) + 0.00007 * np.cos(time * 3.1)
    return time, flux


def _bls_result(candidate: TransitCandidate) -> BlsResult:
    time, flux = _analysis_time_flux()
    return BlsResult(
        candidate=candidate,
        periodogram={
            "period": np.asarray([candidate.period], dtype=np.float32),
            "power": np.asarray([candidate.power], dtype=np.float32),
            "duration": np.asarray([candidate.duration], dtype=np.float32),
        },
        search_time=time,
        search_flux=flux,
        clean_time=time,
        clean_flux=flux,
        metadata={
            "min_period_days": 0.5,
            "max_period_days": 10.0,
            "baseline_days": 12.0,
            "cadence_days": 0.05,
            "period_grid_source": "test",
        },
    )


def test_pipeline_helper_edges_for_quality_aliases_windows_and_payloads():
    config = load_science_config()
    profile = get_search_profile(config, "science_standard")
    time = np.linspace(0.0, 4.0, 32)
    flux = np.ones_like(time)
    quality = np.asarray([0, 1] * 16)

    quality_payload = _data_quality_payload(time, flux, quality, time, flux)
    assert quality_payload["quality_flag_fraction"] == pytest.approx(0.5)
    mismatched_quality = _data_quality_payload(time, flux, np.ones(4), time, flux)
    assert mismatched_quality["quality_flag_fraction"] == pytest.approx(0.0)

    flags = [{"code": "low_snr", "severity": "info", "message": "old"}]
    _add_flag(flags, "low_snr", "hard_fail", "new")
    assert flags == [{"code": "low_snr", "severity": "hard_fail", "message": "new"}]

    invalid = _candidate(period=0.0)
    assert _observed_transit_count(time, invalid) == 0
    assert _period_alias_code(invalid, []) is None
    assert _period_alias_code(_candidate(), [invalid]) is None
    assert _candidate_duplicate(invalid, []) is False
    assert _candidate_duplicate(_candidate(), [invalid]) is False
    assert _candidate_duplicate(_candidate(), [_candidate(period=2.01)]) is True
    assert _cadence_days_from_time(np.ones(4)) == pytest.approx(1.0 / 48.0)

    collapsed_profile, collapsed = _apply_request_period_window(
        profile,
        request_min_period=200.0,
        request_max_period=1.0,
    )
    assert collapsed_profile == profile
    assert collapsed["honored"] is False
    assert "collapsed" in collapsed["detail"]
    assert _baseline_period_note(baseline_days=float("nan"), max_period=10.0, min_transits=2) is None
    assert _baseline_period_note(baseline_days=10.0, max_period=10.0, min_transits=0) is None
    assert _baseline_period_note(baseline_days=10.0, max_period=1.0, min_transits=2) is None

    with pytest.raises(RuntimeError, match="did not complete"):
        _tls_primary_candidate({"status": "failed", "detail": "tls down"})
    with pytest.raises(RuntimeError, match="did not return"):
        _tls_primary_candidate({"status": "complete", "period_days": None})

    @dataclass(frozen=True)
    class TinyPayload:
        value: int

    assert _payload_dict(TinyPayload(3)) == {"value": 3}
    assert _payload_dict({"value": 4}) == {"value": 4}
    assert _payload_dict([("value", 5)]) == {"value": 5}


def test_science_readiness_and_disposition_edges():
    config = load_science_config()
    ready = _candidate_science_readiness(
        result_kind="analysis",
        vetting_mode="fast",
        flags=[],
        physics={"interpretation_locked": False},
        paper_grade=None,
        fpp=None,
        sector_consistency={"multi_sector_status": "consistent"},
        detrending_sensitivity={"status": "passed"},
        ml={"evidence_conflicts": {"status": "passed"}},
    )
    assert ready["status"] == "ready"

    blocked = _candidate_science_readiness(
        result_kind="analysis",
        vetting_mode="paper",
        flags=[{"code": "hard", "severity": "hard_fail"}],
        physics={"interpretation_locked": True},
        paper_grade={"status": "fail"},
        fpp={"status": "failed"},
        sector_consistency={"multi_sector_status": "inconsistent"},
        detrending_sensitivity={"status": "failed"},
        ml={"evidence_conflicts": {"status": "inconclusive", "conflicts": ["ml_conflict"]}},
    )
    assert blocked["status"] == "blocked"
    assert "fpp_incomplete" in blocked["blockers"]
    assert "detrending_failed" in blocked["warnings"]
    assert "ml_conflict" in blocked["warnings"]

    fpp_blocked = _candidate_science_readiness(
        result_kind="analysis",
        vetting_mode="paper",
        flags=[{"code": "info", "severity": "info"}],
        physics={"interpretation_locked": False},
        paper_grade={"status": "pass"},
        fpp={"status": "failed"},
        sector_consistency={"multi_sector_status": "single_sector_only"},
        detrending_sensitivity={"status": "unstable_result"},
        ml=None,
    )
    assert "fpp_incomplete" in fpp_blocked["blockers"]
    assert "single_sector_only" in fpp_blocked["warnings"]
    assert "detrending_unstable" in fpp_blocked["blockers"]

    assert _summarize_science_readiness([], result_kind="analysis", vetting_mode="fast")["status"] == "no_signal"
    assert (
        _summarize_science_readiness(
            [{"science_readiness": {"status": "ready", "blockers": [], "warnings": [], "evidence_gaps": []}}],
            result_kind="analysis",
            vetting_mode="fast",
        )["status"]
        == "ready"
    )
    assert _paper_grade_status_from_flags([]) == "pass"
    assert _paper_grade_status_from_flags([{"severity": "warning"}]) == "review"

    low_score = _disposition(_candidate(snr=4.0), [], config, {"effective_snr": 4.0, "final_score": 0.2})
    assert low_score[0] == "rejected_signal"
    high_score = _disposition(_candidate(snr=8.0), [], config, {"effective_snr": 8.0, "final_score": 0.85})
    assert high_score[0] == "planet_candidate"


def test_structured_flags_cover_residual_secondary_and_centroid_edges():
    config = load_science_config()
    candidate = _candidate(snr=6.0)

    flags = _structured_flags(
        candidate,
        {
            "duration_plausible": True,
            "secondary_snr": config.secondary_eclipse_hard_fail_snr + 1.0,
            "secondary_depth": candidate.depth * 0.2,
            "odd_even_sigma": config.odd_even_hard_fail_sigma + 1.0,
            "centroid_shift_pixels": config.centroid_hard_fail_pixels + 1.0,
            "false_positive_flags": ("manual_review",),
        },
        config,
        {
            "effective_snr": 4.0,
            "red_noise_beta": config.red_noise_warning_beta,
            "quality_flag_fraction": config.quality_flag_dominance_fraction,
            "observed_transit_count": 1,
            "period_alias_code": "duplicate_period",
            "known_planet": {"allow_planetary_secondary": True},
            "planetary_secondary_allowed": True,
        },
    )
    codes = {flag["code"] for flag in flags}
    assert {
        "quality_flag_dominance",
        "single_transit",
        "duplicate_period",
        "known_period_low_snr",
        "planetary_secondary",
        "odd_even_depth_mismatch",
        "centroid_shift",
        "manual_review",
    } <= codes

    residual_flags = _structured_flags(
        _candidate(snr=8.0),
        {"duration_plausible": True, "secondary_depth": None, "centroid_significance": 2.5},
        config,
        {
            "effective_snr": config.promotion_snr,
            "is_residual": False,
            "candidate_rank": 2,
            "primary_signal_to_noise": config.promotion_snr * 2,
            "period_alias_code": "period_harmonic",
        },
    )
    residual_codes = {flag["code"] for flag in residual_flags}
    assert "period_harmonic" in residual_codes
    assert "weak_residual_signal" in residual_codes
    assert "centroid_shift" in residual_codes


def test_paper_grade_vetting_threshold_and_pass_edges():
    config = load_science_config()
    candidate = _candidate(snr=5.0)
    flags: list[dict] = []
    paper = _apply_paper_grade_vetting(
        flags=flags,
        candidate=candidate,
        config=config,
        support={"effective_snr": 5.0, "observed_transit_count": 1},
        tls={"status": "complete", "sde": 1.0, "distinct_transit_count": 1},
        model_shift={"status": "fail", "hard_fail": True, "flags": ["secondary"]},
        sweet={"status": "warning"},
        ml={"probability": None},
        catalog_context={"contamination": {"capable_neighbor_count": 1}},
        fpp={"status": "complete", "fpp": 1.0, "nfpp": 1.0},
        mission_upper="TESS",
    )
    codes = {flag["code"] for flag in flags}
    assert paper["status"] == "fail"
    assert {
        "paper_low_snr",
        "paper_min_transits",
        "paper_tls_sde",
        "paper_tls_transit_count",
        "dave_secondary",
        "sweet_sinusoid",
        "nigraha_required",
        "triceratops_fpp",
        "triceratops_nfpp",
        "catalog_contamination",
    } <= codes

    flags = []
    review = _apply_paper_grade_vetting(
        flags=flags,
        candidate=_candidate(snr=9.0),
        config=config,
        support={"effective_snr": 9.0, "observed_transit_count": 3},
        tls={"status": "complete", "sde": 20.0, "distinct_transit_count": 3},
        model_shift={"status": "pass", "hard_fail": False},
        sweet={"status": "pass"},
        ml={"probability": config.paper_ml_threshold - 0.01},
        catalog_context={},
        fpp={"status": "complete", "fpp": 0.0, "nfpp": 0.0},
        mission_upper="TESS",
    )
    assert review["status"] == "review"
    assert {flag["code"] for flag in flags} == {"nigraha_low_probability"}

    flags = []
    passed = _apply_paper_grade_vetting(
        flags=flags,
        candidate=_candidate(snr=9.0),
        config=config,
        support={"effective_snr": 9.0, "observed_transit_count": 3},
        tls={"status": "complete", "sde": 20.0, "distinct_transit_count": 3},
        model_shift={"status": "pass", "hard_fail": False},
        sweet={"status": "pass"},
        ml={"probability": None},
        catalog_context=None,
        fpp={},
        mission_upper="KEPLER",
    )
    assert passed["status"] == "pass"

    flags = []
    required = _apply_paper_grade_vetting(
        flags=flags,
        candidate=_candidate(snr=9.0),
        config=config,
        support={"effective_snr": 9.0, "observed_transit_count": 3},
        tls={"status": "failed"},
        model_shift={"status": "skipped", "hard_fail": False},
        sweet={"status": "skipped"},
        ml={"probability": 0.9},
        catalog_context={},
        fpp={"status": "complete", "fpp": 0.0, "nfpp": 0.0},
        mission_upper="TESS",
    )
    assert required["status"] == "fail"
    assert {"paper_tls_required", "dave_model_shift_required", "sweet_required"} <= {flag["code"] for flag in flags}


def test_resolve_secondary_alias_edges(monkeypatch):
    config = load_science_config()
    candidate = _candidate(period=2.0, snr=8.0)
    clean = ValidationMetrics(
        odd_even_depth_delta=0.0,
        odd_even_sigma=None,
        secondary_depth=0.0,
        secondary_snr=None,
        duration_plausible=True,
        harmonic_flag=False,
        sap_pdcsap_agreement=None,
        centroid_shift_pixels=None,
        centroid_uncertainty_pixels=None,
        centroid_significance=None,
        centroid_shift_flag=False,
        false_positive_flags=(),
    )
    secondary = ValidationMetrics(**{**clean.__dict__, "false_positive_flags": ("secondary_eclipse",)})

    monkeypatch.setattr(pipeline, "validate_candidate", lambda *args, **kwargs: clean)
    assert (
        _resolve_secondary_period_alias(np.arange(64), np.ones(64), candidate, config, min_period=0.1, max_period=5.0)
        is candidate
    )

    monkeypatch.setattr(pipeline, "validate_candidate", lambda *args, **kwargs: secondary)
    assert (
        _resolve_secondary_period_alias(np.arange(64), np.ones(64), candidate, config, min_period=1.5, max_period=5.0)
        is candidate
    )
    assert (
        _resolve_secondary_period_alias(np.arange(64), np.ones(64), candidate, config, min_period=1.0, max_period=1.0)
        is candidate
    )

    monkeypatch.setattr(pipeline, "run_bls", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no alias")))
    assert (
        _resolve_secondary_period_alias(np.arange(64), np.ones(64), candidate, config, min_period=0.1, max_period=5.0)
        is candidate
    )

    weak_alias = _candidate(period=1.0, snr=1.0)
    monkeypatch.setattr(
        pipeline,
        "run_bls",
        lambda *args, **kwargs: BlsResult(weak_alias, {}, np.arange(64), np.ones(64), np.arange(64), np.ones(64), {}),
    )
    assert (
        _resolve_secondary_period_alias(np.arange(64), np.ones(64), candidate, config, min_period=0.1, max_period=5.0)
        is candidate
    )

    strong_alias = _candidate(period=1.0, snr=7.0)
    monkeypatch.setattr(
        pipeline,
        "run_bls",
        lambda *args, **kwargs: BlsResult(strong_alias, {}, np.arange(64), np.ones(64), np.arange(64), np.ones(64), {}),
    )
    assert (
        _resolve_secondary_period_alias(np.arange(64), np.ones(64), candidate, config, min_period=0.1, max_period=5.0)
        is strong_alias
    )


def test_ml_payload_mission_branches_and_domain_conflicts(monkeypatch):
    candidate = _candidate()
    time = np.linspace(0.0, 4.0, 64)
    flux = np.ones_like(time)
    physics = {"planet_radius_earth": 40.0, "stellar_context_source": "user_supplied"}

    class ThresholdlessTessService:
        def predict(self, tensors):
            return {"probability": 0.3, "threshold": 0.5, "label": "not-transit-like", "preprocessing_compatible": True}

    monkeypatch.setattr(pipeline, "build_nigraha_tensors", lambda *args, **kwargs: object())
    ml, _service, tess_service, _k2 = _ml_payload_for_candidate(
        mission_upper="TESS",
        clean_time=time,
        clean_flux=flux,
        candidate=candidate,
        physics=physics,
        stellar_teff=None,
        stellar_radius_solar=None,
        stellar_logg=None,
        stellar_mass_solar=None,
        stellar_luminosity_solar=None,
        stellar_density_solar=None,
        service=None,
        tess_service=ThresholdlessTessService(),
        k2_service=None,
        nigraha_threshold=0.4,
    )
    assert tess_service is not None
    assert ml["threshold"] == 0.4
    assert ml["label"] == "not-transit-like"

    class NoProbabilityTessService:
        def predict(self, tensors):
            return {"probability": None, "threshold": 0.5, "label": "ml-unavailable", "preprocessing_compatible": False}

    none_ml, *_ = _ml_payload_for_candidate(
        mission_upper="TESS",
        clean_time=time,
        clean_flux=flux,
        candidate=candidate,
        physics=physics,
        stellar_teff=None,
        stellar_radius_solar=None,
        stellar_logg=None,
        stellar_mass_solar=None,
        stellar_luminosity_solar=None,
        stellar_density_solar=None,
        service=None,
        tess_service=NoProbabilityTessService(),
        k2_service=None,
        nigraha_threshold=0.4,
    )
    assert none_ml["threshold"] == 0.4

    class FakeKeplerService:
        def predict(self, tensors):
            return {"probability": 0.9, "threshold": 0.5, "label": "planet-candidate", "preprocessing_compatible": True}

    monkeypatch.setattr(pipeline, "build_astronet_tensors", lambda *args, **kwargs: object())
    monkeypatch.setattr(pipeline, "KeplerAstroNetService", lambda: FakeKeplerService())
    kepler_ml, service, _tess, _k2 = _ml_payload_for_candidate(
        mission_upper="KEPLER",
        clean_time=time,
        clean_flux=flux,
        candidate=candidate,
        physics=physics,
        stellar_teff=None,
        stellar_radius_solar=None,
        stellar_logg=None,
        stellar_mass_solar=None,
        stellar_luminosity_solar=None,
        stellar_density_solar=None,
        service=None,
        tess_service=None,
        k2_service=None,
    )
    assert service is not None
    assert kepler_ml["probability"] == pytest.approx(0.9)
    provided_kepler_ml, provided_service, _tess, _k2 = _ml_payload_for_candidate(
        mission_upper="KEPLER",
        clean_time=time,
        clean_flux=flux,
        candidate=candidate,
        physics=physics,
        stellar_teff=None,
        stellar_radius_solar=None,
        stellar_logg=None,
        stellar_mass_solar=None,
        stellar_luminosity_solar=None,
        stellar_density_solar=None,
        service=FakeKeplerService(),
        tess_service=None,
        k2_service=None,
    )
    assert provided_service is not None
    assert provided_kepler_ml["probability"] == pytest.approx(0.9)

    class FakeExomacService:
        def predict(self, features):
            return {"probability": 0.8, "threshold": 0.5, "label": "candidate", "preprocessing_compatible": True}

    monkeypatch.setattr(pipeline, "ExoMACService", lambda: FakeExomacService())
    k2_ml, _service, _tess, k2_service = _ml_payload_for_candidate(
        mission_upper="K2",
        clean_time=time,
        clean_flux=flux,
        candidate=candidate,
        physics=physics,
        stellar_teff=5000.0,
        stellar_radius_solar=1.0,
        stellar_logg=4.5,
        stellar_mass_solar=1.0,
        stellar_luminosity_solar=1.0,
        stellar_density_solar=1.0,
        service=None,
        tess_service=None,
        k2_service=None,
    )
    assert k2_service is not None
    assert k2_ml["probability"] == pytest.approx(0.8)

    monkeypatch.setattr(
        pipeline, "build_nigraha_tensors", lambda *args, **kwargs: (_ for _ in ()).throw(ModelArtifactError("missing"))
    )
    unavailable, *_ = _ml_payload_for_candidate(
        mission_upper="TESS",
        clean_time=time,
        clean_flux=flux,
        candidate=candidate,
        physics=physics,
        stellar_teff=None,
        stellar_radius_solar=None,
        stellar_logg=None,
        stellar_mass_solar=None,
        stellar_luminosity_solar=None,
        stellar_density_solar=None,
        service=None,
        tess_service=ThresholdlessTessService(),
        k2_service=None,
    )
    assert unavailable["label"] == "ml-unavailable"

    with pytest.raises(AssertionError):
        _ml_payload_for_candidate(
            mission_upper="UNKNOWN",
            clean_time=time,
            clean_flux=flux,
            candidate=candidate,
            physics=physics,
            stellar_teff=None,
            stellar_radius_solar=None,
            stellar_logg=None,
            stellar_mass_solar=None,
            stellar_luminosity_solar=None,
            stellar_density_solar=None,
            service=None,
            tess_service=None,
            k2_service=None,
        )

    aware = _attach_ml_domain_evidence(
        {"probability": 0.9, "threshold": 0.5, "label": "planet-candidate", "preprocessing_compatible": True},
        mission_upper="TESS",
        flags=[],
        physics=physics,
    )
    assert "ml_support_conflicts_with_implausible_planet_radius" in aware["evidence_conflicts"]["conflicts"]
    ood = _attach_ml_domain_evidence(
        {
            "probability": None,
            "label": "not-transit-like",
            "preprocessing_compatible": False,
            "imputed_features": ("a", "b", "c", "d"),
        },
        mission_upper="K2",
        flags=[],
        physics={"stellar_context_source": "solar_like_fallback"},
    )
    assert set(ood["domain_awareness"]["out_of_distribution_reasons"]) == {
        "preprocessing_incompatible",
        "many_imputed_stellar_features",
        "no_model_score",
        "fallback_stellar_context",
    }
    low_without_hard = _attach_ml_domain_evidence(
        {"probability": 0.2, "threshold": 0.5, "label": "not-transit-like", "preprocessing_compatible": True},
        mission_upper="KEPLER",
        flags=[],
        physics={"stellar_context_source": "user_supplied"},
    )
    assert "ml_low_score_without_hard_vetting_failure" in low_without_hard["evidence_conflicts"]["conflicts"]


def _patch_common_analysis(monkeypatch, *, primary, residuals, guided=None, sector_status="single_sector_only"):
    bls = _bls_result(primary)
    monkeypatch.setattr(pipeline, "_select_primary_candidate", lambda *args, **kwargs: (primary, bls, guided or []))
    monkeypatch.setattr(pipeline, "find_multi_planet_candidates", lambda *args, **kwargs: residuals)
    monkeypatch.setattr(
        pipeline,
        "_ml_payload_for_candidate",
        lambda **kwargs: (
            {
                "probability": 0.9,
                "threshold": 0.5,
                "label": "planet-candidate",
                "preprocessing_compatible": True,
                "input_tensor_checksum": "unit",
            },
            kwargs.get("service"),
            kwargs.get("tess_service"),
            kwargs.get("k2_service"),
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "summarize_sector_consistency",
        lambda *args, **kwargs: {"status": sector_status, "multi_sector_status": sector_status, "sector_evidence": []},
    )
    monkeypatch.setattr(pipeline, "run_injection_recovery", lambda *args, **kwargs: {"status": "passed"})
    monkeypatch.setattr(
        pipeline, "config_usage_audit", lambda: {"active_science_config_keys": [], "inactive_science_config_keys": []}
    )
    monkeypatch.setattr(pipeline, "science_config_hash", lambda: "unit-hash")


def test_analyze_search_profile_unsupported_mission_and_empty_ledger(monkeypatch):
    primary = _candidate(snr=9.0)
    _patch_common_analysis(monkeypatch, primary=primary, residuals=[])

    payload = pipeline.analyze_light_curve_arrays(
        target_id="TIC 123",
        mission="TESS",
        time=_analysis_time_flux()[0],
        flux=_analysis_time_flux()[1],
        stellar_radius_solar=1.0,
        stellar_mass_solar=1.0,
        stellar_teff=5778.0,
        vetting_mode="fast",
        search_profile="preview_fast",
    )
    assert payload["search_profile"] == "preview_fast"
    assert payload["science_readiness"]["status"] == "no_signal"
    assert payload["engine_status"]["sector_consistency"]["status"] == "skipped"

    _patch_common_analysis(monkeypatch, primary=primary, residuals=[primary])
    with pytest.raises(ValueError, match="unsupported mission"):
        pipeline.analyze_light_curve_arrays(
            target_id="TIC 123",
            mission="GAIA",
            time=_analysis_time_flux()[0],
            flux=_analysis_time_flux()[1],
            vetting_mode="fast",
        )


def test_analyze_ledger_limits_duplicate_paths_and_promotion(monkeypatch):
    primary = _candidate(period=2.0, snr=9.0)
    guided = _candidate(period=3.0, snr=8.5)
    duplicate = _candidate(period=3.01, snr=8.0)
    residual = _candidate(period=5.0, snr=8.2)

    duplicate_results = iter([False, True, False])
    _patch_common_analysis(
        monkeypatch,
        primary=primary,
        residuals=[primary, duplicate, residual],
        guided=[primary, guided],
        sector_status="consistent",
    )
    monkeypatch.setattr(pipeline, "_candidate_duplicate", lambda *args, **kwargs: next(duplicate_results))
    monkeypatch.setattr(
        pipeline, "_disposition", lambda *args, **kwargs: ("planet_candidate", "follow_up_needed", "high", 0.9)
    )

    payload = pipeline.analyze_light_curve_arrays(
        target_id="TIC 123",
        mission="TESS",
        time=_analysis_time_flux()[0],
        flux=_analysis_time_flux()[1],
        stellar_radius_solar=1.0,
        stellar_mass_solar=1.0,
        stellar_teff=5778.0,
        vetting_mode="fast",
        max_candidates=4,
    )
    assert len(payload["tces"]) == 3
    assert len(payload["planet_candidates"]) >= 1
    assert payload["engine_status"]["sector_consistency"]["status"] == "consistent"

    _patch_common_analysis(monkeypatch, primary=primary, residuals=[primary, residual], guided=[primary, guided])
    monkeypatch.setattr(pipeline, "_candidate_duplicate", lambda *args, **kwargs: False)
    limited = pipeline.analyze_light_curve_arrays(
        target_id="TIC 123",
        mission="TESS",
        time=_analysis_time_flux()[0],
        flux=_analysis_time_flux()[1],
        stellar_radius_solar=1.0,
        stellar_mass_solar=1.0,
        stellar_teff=5778.0,
        vetting_mode="fast",
        max_candidates=1,
    )
    assert len(limited["tces"]) == 1

    _patch_common_analysis(monkeypatch, primary=primary, residuals=[primary], guided=[primary, guided])
    monkeypatch.setattr(pipeline, "_candidate_duplicate", lambda *args, **kwargs: True)
    duplicate_guided = pipeline.analyze_light_curve_arrays(
        target_id="TIC 123",
        mission="TESS",
        time=_analysis_time_flux()[0],
        flux=_analysis_time_flux()[1],
        stellar_radius_solar=1.0,
        stellar_mass_solar=1.0,
        stellar_teff=5778.0,
        vetting_mode="fast",
        max_candidates=4,
    )
    assert len(duplicate_guided["tces"]) == 1


def test_analyze_deep_vetting_statuses_and_blocked_demotion(monkeypatch):
    primary = _candidate(snr=9.0)
    _patch_common_analysis(monkeypatch, primary=primary, residuals=[primary], sector_status="inconsistent")
    monkeypatch.setattr(pipeline, "refine_with_tls", lambda *args, **kwargs: {"status": "failed"})
    monkeypatch.setattr(pipeline, "run_detrending_sensitivity", lambda *args, **kwargs: {"status": "passed"})
    monkeypatch.setattr(
        pipeline, "_disposition", lambda *args, **kwargs: ("planet_candidate", "follow_up_needed", "high", 0.9)
    )
    monkeypatch.setattr(
        pipeline,
        "_candidate_science_readiness",
        lambda **kwargs: {
            "status": "blocked",
            "result_kind": "analysis",
            "vetting_mode": "deep",
            "blockers": ["unit"],
            "warnings": [],
            "evidence_gaps": [],
            "interpretation": "blocked",
        },
    )

    blocked = pipeline.analyze_light_curve_arrays(
        target_id="TIC 123",
        mission="TESS",
        time=_analysis_time_flux()[0],
        flux=_analysis_time_flux()[1],
        stellar_radius_solar=1.0,
        stellar_mass_solar=1.0,
        stellar_teff=5778.0,
        vetting_mode="deep",
    )
    assert blocked["tces"][0]["disposition"] == "borderline_tce"
    assert blocked["engine_status"]["tls"]["status"] == "failed"
    assert blocked["engine_status"]["detrending_sensitivity"]["status"] == "passed"
    assert blocked["engine_status"]["sector_consistency"]["status"] == "inconsistent"
    assert "tls_refinement" in blocked["deep_mode_progress"]["steps"]

    _patch_common_analysis(monkeypatch, primary=primary, residuals=[primary], sector_status="consistent")
    monkeypatch.setattr(pipeline, "refine_with_tls", lambda *args, **kwargs: {"status": "complete", "sde": 10.0})
    monkeypatch.setattr(
        pipeline,
        "_candidate_science_readiness",
        lambda **kwargs: {
            "status": "review",
            "result_kind": "analysis",
            "vetting_mode": "deep",
            "blockers": [],
            "warnings": ["unit"],
            "evidence_gaps": [],
            "interpretation": "review",
        },
    )
    monkeypatch.setattr(
        pipeline,
        "run_detrending_sensitivity",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("sensitivity failed")),
    )
    failed_sensitivity = pipeline.analyze_light_curve_arrays(
        target_id="TIC 123",
        mission="TESS",
        time=_analysis_time_flux()[0],
        flux=_analysis_time_flux()[1],
        stellar_radius_solar=1.0,
        stellar_mass_solar=1.0,
        stellar_teff=5778.0,
        vetting_mode="deep",
    )
    assert failed_sensitivity["engine_status"]["detrending_sensitivity"]["status"] == "failed"

    _patch_common_analysis(monkeypatch, primary=primary, residuals=[primary], sector_status="single_sector_only")
    monkeypatch.setattr(pipeline, "refine_with_tls", lambda *args, **kwargs: {"status": "complete", "sde": 10.0})
    monkeypatch.setattr(pipeline, "run_detrending_sensitivity", lambda *args, **kwargs: {"status": "inconclusive"})
    inconclusive = pipeline.analyze_light_curve_arrays(
        target_id="TIC 123",
        mission="TESS",
        time=_analysis_time_flux()[0],
        flux=_analysis_time_flux()[1],
        stellar_radius_solar=1.0,
        stellar_mass_solar=1.0,
        stellar_teff=5778.0,
        vetting_mode="deep",
    )
    assert inconclusive["engine_status"]["detrending_sensitivity"]["status"] == "inconclusive"
    assert inconclusive["engine_status"]["sector_consistency"]["status"] == "single_sector_only"

    _patch_common_analysis(monkeypatch, primary=primary, residuals=[], sector_status="single_sector_only")
    no_tces = pipeline.analyze_light_curve_arrays(
        target_id="TIC 123",
        mission="TESS",
        time=_analysis_time_flux()[0],
        flux=_analysis_time_flux()[1],
        stellar_radius_solar=1.0,
        stellar_mass_solar=1.0,
        stellar_teff=5778.0,
        vetting_mode="deep",
    )
    assert no_tces["engine_status"]["tls"]["status"] == "skipped"
    assert no_tces["engine_status"]["detrending_sensitivity"]["status"] == "skipped"


def test_analyze_paper_non_tess_skips_tess_specific_engines(monkeypatch):
    primary = _candidate(snr=9.0)
    _patch_common_analysis(monkeypatch, primary=primary, residuals=[primary], sector_status="insufficient_data")
    monkeypatch.setattr(
        pipeline, "detrend_with_wotan", lambda time, flux, **kwargs: (flux, {"status": "complete", "engine": "wotan"})
    )
    monkeypatch.setattr(
        pipeline,
        "search_with_tls",
        lambda *args, **kwargs: {
            "status": "complete",
            "period_days": primary.period,
            "epoch_days": primary.epoch,
            "duration_days": primary.duration,
            "depth_fraction": primary.depth,
            "snr": primary.signal_to_noise,
            "sde": 12.0,
            "distinct_transit_count": 3,
        },
    )
    monkeypatch.setattr(pipeline, "run_model_shift", lambda *args, **kwargs: {"status": "pass", "hard_fail": False})
    monkeypatch.setattr(pipeline, "run_sweet_test", lambda *args, **kwargs: {"status": "pass"})
    monkeypatch.setattr(pipeline, "run_detrending_sensitivity", lambda *args, **kwargs: {"status": "unstable_result"})

    payload = pipeline.analyze_light_curve_arrays(
        target_id="Kepler-10",
        mission="KEPLER",
        time=_analysis_time_flux()[0],
        flux=_analysis_time_flux()[1],
        stellar_radius_solar=1.0,
        stellar_mass_solar=1.0,
        stellar_teff=5778.0,
        vetting_mode="paper",
    )

    assert payload["engine_status"]["triceratops"]["status"] == "not_applicable"
    assert payload["engine_status"]["detrending_sensitivity"]["status"] == "unstable_result"
    assert payload["engine_status"]["sector_consistency"]["status"] == "insufficient_data"
    assert "paper_thresholds" in payload["deep_mode_progress"]["steps"]
