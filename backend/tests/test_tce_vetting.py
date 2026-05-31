import numpy as np
import pytest
from orbitlab.api.main import _analysis_response_payload
from orbitlab.science.bls import TransitCandidate
from orbitlab.science.pipeline import _disposition, _structured_flags, analyze_light_curve_arrays
from orbitlab.science.science_config import load_science_config, science_config_hash
from orbitlab.storage.orm import AnalysisResultRecord


class _UnavailableModel:
    def predict(self, tensors):
        raise FileNotFoundError("model missing in test")


def _light_curve(period=0.9414760262, depth=0.005, noise=0.0008654):
    rng = np.random.default_rng(42)
    time = np.linspace(0, 27, 1600, dtype=np.float32)
    flux = 1.0 + rng.normal(0, noise, size=time.size)
    phase = ((time - 0.12 + 0.5 * period) % period) - 0.5 * period
    flux[np.abs(phase) < 0.035] -= depth
    return time.astype(np.float32), flux.astype(np.float32)


def test_science_config_hash_is_stable_hex():
    digest = science_config_hash()

    assert len(digest) == 64
    int(digest, 16)


def test_tic_like_borderline_signal_is_preserved_as_review_needed(monkeypatch):
    config = load_science_config()
    candidate = TransitCandidate(
        period=0.9414760262,
        epoch=0.1,
        duration=0.07,
        depth=0.005,
        power=12.0,
        signal_to_noise=5.77754,
    )

    class _BlsResult:
        periodogram = {
            "period": np.array([candidate.period], dtype=np.float32),
            "power": np.array([candidate.power], dtype=np.float32),
            "duration": np.array([candidate.duration], dtype=np.float32),
        }
        search_time = np.linspace(0, 27, 256, dtype=np.float32)
        search_flux = 1.0 + 0.001 * np.sin(np.linspace(0, 12, 256, dtype=np.float32))
        clean_time = search_time
        clean_flux = search_flux
        metadata = {"min_period_days": 0.5, "max_period_days": 10.0}

        def __init__(self):
            self.candidate = candidate

    monkeypatch.setattr("orbitlab.science.pipeline.run_bls", lambda *args, **kwargs: _BlsResult())
    monkeypatch.setattr(
        "orbitlab.science.pipeline.find_multi_planet_candidates",
        lambda *args, **kwargs: [candidate],
    )

    time, flux = _light_curve()
    payload = analyze_light_curve_arrays(
        target_id="100100827",
        mission="TESS",
        time=time,
        flux=flux,
        vetting_mode="fast",
        nigraha_service=_UnavailableModel(),
    )

    assert "candidates" not in payload
    assert payload["schema_version"] == "orbitlab.analysis_result.v2"
    assert payload["science_config_hash"] == science_config_hash()
    assert payload["planet_candidates"] == []
    assert payload["tces"][0]["period_days"] == pytest.approx(0.9414760262)
    assert payload["tces"][0]["bls_snr"] == pytest.approx(5.77754)
    assert payload["tces"][0]["disposition"] == "borderline_tce"
    assert payload["tces"][0]["action_label"] == "review_needed"
    assert payload["tces"][0]["signal_to_noise"] < config.promotion_snr


def test_paper_grade_mode_applies_strict_published_thresholds(monkeypatch):
    candidate = TransitCandidate(
        period=2.0,
        epoch=0.1,
        duration=0.08,
        depth=0.002,
        power=12.0,
        signal_to_noise=6.9,
    )

    class _BlsResult:
        periodogram = {
            "period": np.array([candidate.period], dtype=np.float32),
            "power": np.array([candidate.power], dtype=np.float32),
            "duration": np.array([candidate.duration], dtype=np.float32),
        }
        search_time = np.linspace(0, 24, 900, dtype=np.float32)
        search_flux = 1.0 + 0.001 * np.sin(np.linspace(0, 20, 900, dtype=np.float32))
        clean_time = search_time
        clean_flux = search_flux
        metadata = {"min_period_days": 0.5, "max_period_days": 12.0}

        def __init__(self):
            self.candidate = candidate

    class _PaperModel:
        def predict(self, tensors, *, threshold=0.4):
            assert threshold == pytest.approx(0.4)
            return {
                "probability": 0.8,
                "threshold": threshold,
                "label": "planet-candidate",
                "model_version": "test",
                "model_source": "test",
                "input_tensor_checksum": "checksum",
                "preprocessing_compatible": True,
                "citation": "test",
            }

    monkeypatch.setattr("orbitlab.science.pipeline.run_bls", lambda *args, **kwargs: _BlsResult())
    monkeypatch.setattr("orbitlab.science.pipeline.find_multi_planet_candidates", lambda *args, **kwargs: [candidate])
    monkeypatch.setattr(
        "orbitlab.science.pipeline.search_with_tls",
        lambda *args, **kwargs: {
            "status": "complete",
            "period_days": 2.0,
            "epoch_days": 0.1,
            "duration_days": 0.08,
            "depth_fraction": 0.002,
            "snr": 6.9,
            "sde": 8.0,
            "transit_count": 6,
            "distinct_transit_count": 6,
        },
    )
    monkeypatch.setattr(
        "orbitlab.science.pipeline.run_model_shift",
        lambda *args, **kwargs: {"status": "pass", "engine": "dave_model_shift", "hard_fail": False, "flags": []},
    )
    monkeypatch.setattr(
        "orbitlab.science.pipeline.run_sweet_test",
        lambda *args, **kwargs: {"status": "pass", "engine": "sweet", "max_sigma": 0.0},
    )
    monkeypatch.setattr(
        "orbitlab.science.pipeline.run_injection_recovery",
        lambda *args, **kwargs: {"status": "complete", "engine": "box_injection_recovery"},
    )
    monkeypatch.setattr(
        "orbitlab.science.pipeline.query_tic_catalog_context",
        lambda *args, **kwargs: {
            "status": "complete",
            "contamination": {"status": "pass", "capable_neighbor_count": 0},
        },
    )
    monkeypatch.setattr(
        "orbitlab.science.pipeline.run_triceratops_fpp",
        lambda *args, **kwargs: {
            "status": "complete",
            "engine": "triceratops",
            "fpp": 0.001,
            "nfpp": 0.0001,
        },
    )

    time, flux = _light_curve(period=2.0, depth=0.002, noise=0.0002)
    payload = analyze_light_curve_arrays(
        target_id="TIC 123456789",
        mission="TESS",
        product_uri="tess2020000000000-s0001-0000000123456789-tp.fits",
        time=time,
        flux=flux,
        vetting_mode="paper",
        nigraha_service=_PaperModel(),
    )

    tce = payload["tces"][0]
    assert payload["vetting_mode"] == "paper"
    assert payload["search_profile"] == "paper_grade"
    assert payload["planet_candidates"] == []
    assert tce["disposition"] == "rejected_signal"
    assert any(flag["code"] == "paper_low_snr" and flag["severity"] == "hard_fail" for flag in tce["flags"])
    assert tce["ml"]["threshold"] == pytest.approx(0.4)
    assert tce["evidence"]["tls"]["sde"] == 8.0
    assert tce["vetting"]["paper_grade"]["status"] == "fail"


def test_disposition_promotes_clean_snr_at_threshold():
    config = load_science_config()
    candidate = TransitCandidate(2.0, 0.1, 0.08, 0.002, 9.0, config.promotion_snr)
    flags = _structured_flags(
        candidate,
        {"duration_plausible": True, "secondary_depth": 0.0, "odd_even_depth_delta": 0.0},
        config,
    )

    assert _disposition(candidate, flags, config)[0] == "planet_candidate"


def test_hard_fail_secondary_rejects_high_snr_signal():
    config = load_science_config()
    candidate = TransitCandidate(2.0, 0.1, 0.08, 0.002, 9.0, config.promotion_snr + 1.0)
    flags = _structured_flags(
        candidate,
        {"duration_plausible": True, "secondary_depth": 0.002, "odd_even_depth_delta": 0.0},
        config,
    )

    assert any(flag["code"] == "secondary_eclipse" and flag["severity"] == "hard_fail" for flag in flags)
    assert _disposition(candidate, flags, config)[0] == "rejected_signal"


def test_centroid_shift_is_single_review_warning_not_hard_rejection():
    config = load_science_config()
    candidate = TransitCandidate(2.2054, 0.1, 0.08, 0.002, 12.0, 7.89)
    flags = _structured_flags(
        candidate,
        {
            "duration_plausible": True,
            "secondary_depth": 0.0,
            "odd_even_depth_delta": 0.0,
            "centroid_significance": 3.4,
            "false_positive_flags": ("centroid_shift",),
        },
        config,
        {"red_noise_beta": config.red_noise_warning_beta},
    )

    centroid_flags = [flag for flag in flags if flag["code"] == "centroid_shift"]
    assert centroid_flags == [
        {
            "code": "centroid_shift",
            "severity": "warning",
            "message": "Centroid shift exceeds 3 sigma; review source position before promotion.",
        }
    ]
    assert _disposition(candidate, flags, config)[0] == "borderline_tce"


def test_response_aliases_new_and_old_payloads():
    new_record = AnalysisResultRecord(
        id="new",
        job_id="job-new",
        payload_json={
            "result_id": "new",
            "target_id": "tic",
            "mission": "TESS",
            "planet_candidates": [
                {
                    "candidate_id": "pc-1",
                    "period": 1,
                    "epoch": 0,
                    "duration": 0.1,
                    "depth": 0.01,
                    "signal_to_noise": 7,
                }
            ],
            "tces": [],
            "periodogram": {"period": [], "power": []},
            "folded_curves": {},
            "light_curve": {"time": [], "flux": []},
        },
    )
    old_record = AnalysisResultRecord(
        id="old",
        job_id="job-old",
        payload_json={
            "result_id": "old",
            "target_id": "tic",
            "mission": "TESS",
            "candidates": [
                {
                    "candidate_id": "old-1",
                    "period": 1,
                    "epoch": 0,
                    "duration": 0.1,
                    "depth": 0.01,
                    "signal_to_noise": 7,
                }
            ],
            "periodogram": {"period": [], "power": []},
            "folded_curves": {},
            "light_curve": {"time": [], "flux": []},
        },
    )

    assert _analysis_response_payload(new_record)["candidates"][0]["candidate_id"] == "pc-1"
    assert _analysis_response_payload(old_record)["planet_candidates"][0]["candidate_id"] == "old-1"


def test_analysis_uses_solar_like_physics_fallback_when_stellar_context_is_missing(monkeypatch):
    candidate = TransitCandidate(2.0, 0.1, 0.08, 0.0025, 11.0, 9.0)

    class _BlsResult:
        periodogram = {
            "period": np.array([candidate.period], dtype=np.float32),
            "power": np.array([candidate.power], dtype=np.float32),
            "duration": np.array([candidate.duration], dtype=np.float32),
        }
        search_time = np.linspace(0, 20, 800, dtype=np.float32)
        search_flux = 1.0 + 0.001 * np.sin(np.linspace(0, 18, 800, dtype=np.float32))
        clean_time = search_time
        clean_flux = search_flux
        metadata = {"min_period_days": 0.5, "max_period_days": 10.0}

        def __init__(self):
            self.candidate = candidate

    monkeypatch.setattr("orbitlab.science.pipeline.run_bls", lambda *args, **kwargs: _BlsResult())
    monkeypatch.setattr("orbitlab.science.pipeline.find_multi_planet_candidates", lambda *args, **kwargs: [candidate])

    time, flux = _light_curve(period=2.0)
    payload = analyze_light_curve_arrays(
        target_id="fallback-star",
        mission="TESS",
        time=time,
        flux=flux,
        vetting_mode="fast",
        nigraha_service=_UnavailableModel(),
    )

    physics = payload["tces"][0]["physics"]
    assert physics["stellar_context_source"] == "solar_like_fallback"
    assert physics["radius_ratio"] > 0
    assert physics["semi_major_axis_au"] > 0
    assert payload["stellar_context"]["physics_source"] == "solar_like_fallback"


def test_harmonic_residual_signal_stays_in_tce_ledger_but_is_not_promoted(monkeypatch):
    primary = TransitCandidate(2.0, 0.1, 0.08, 0.0025, 11.0, 9.0)
    harmonic = TransitCandidate(4.0, 0.1, 0.08, 0.0019, 10.0, 8.5)

    class _BlsResult:
        periodogram = {
            "period": np.array([primary.period, harmonic.period], dtype=np.float32),
            "power": np.array([primary.power, harmonic.power], dtype=np.float32),
            "duration": np.array([primary.duration, harmonic.duration], dtype=np.float32),
        }
        search_time = np.linspace(0, 24, 900, dtype=np.float32)
        search_flux = 1.0 + 0.001 * np.sin(np.linspace(0, 20, 900, dtype=np.float32))
        clean_time = search_time
        clean_flux = search_flux
        metadata = {"min_period_days": 0.5, "max_period_days": 12.0}

        def __init__(self):
            self.candidate = primary

    monkeypatch.setattr("orbitlab.science.pipeline.run_bls", lambda *args, **kwargs: _BlsResult())
    monkeypatch.setattr(
        "orbitlab.science.pipeline.find_multi_planet_candidates",
        lambda *args, **kwargs: [primary, harmonic],
    )

    time, flux = _light_curve(period=2.0)
    payload = analyze_light_curve_arrays(
        target_id="single-known-planet",
        mission="TESS",
        time=time,
        flux=flux,
        vetting_mode="fast",
        nigraha_service=_UnavailableModel(),
    )

    assert payload["planet_candidates"] == []
    assert len(payload["tces"]) == 2
    assert payload["tces"][0]["disposition"] == "borderline_tce"
    assert payload["tces"][0]["effective_snr"] < payload["tces"][0]["raw_snr"]
    assert payload["tces"][1]["disposition"] == "rejected_signal"
    assert "period_harmonic" in payload["tces"][1]["alias_flags"]


def test_science_config_audit_exposes_active_keys():
    from orbitlab.science.science_config import config_usage_audit

    audit = config_usage_audit()

    assert "red_noise_warning_beta" in audit["active_science_config_keys"]
    assert "quality_flag_dominance_fraction" in audit["active_science_config_keys"]
    assert "forced_period_tolerance_fraction" in audit["active_science_config_keys"]
    assert audit["inactive_science_config_keys"] == []


def test_solar_like_fallback_disables_habitability_claim(monkeypatch):
    candidate = TransitCandidate(2.0, 0.1, 0.08, 0.0025, 11.0, 9.0)

    class _BlsResult:
        periodogram = {
            "period": np.array([candidate.period], dtype=np.float32),
            "power": np.array([candidate.power], dtype=np.float32),
            "duration": np.array([candidate.duration], dtype=np.float32),
        }
        search_time = np.linspace(0, 20, 800, dtype=np.float32)
        search_flux = (1.0 + 0.001 * np.sin(np.linspace(0, 10, 800, dtype=np.float32))).astype(np.float32)
        clean_time = search_time
        clean_flux = search_flux
        metadata = {"min_period_days": 0.5, "max_period_days": 10.0}

        def __init__(self):
            self.candidate = candidate

    monkeypatch.setattr("orbitlab.science.pipeline.run_bls", lambda *args, **kwargs: _BlsResult())
    monkeypatch.setattr("orbitlab.science.pipeline.find_multi_planet_candidates", lambda *args, **kwargs: [candidate])

    time, flux = _light_curve(period=2.0)
    payload = analyze_light_curve_arrays(
        target_id="fallback-star",
        mission="TESS",
        time=time,
        flux=flux,
        vetting_mode="fast",
        nigraha_service=_UnavailableModel(),
    )

    assert payload["tces"][0]["physics"]["habitability"]["status"] == "insufficient_stellar_data"
    assert payload["tces"][0]["physics"]["is_in_habitable_zone"] is None


def test_known_hot_jupiter_secondary_is_reviewable_not_rejected():
    config = load_science_config()
    candidate = TransitCandidate(2.204736, 0.1, 0.16, 0.006, 18.0, 8.2)

    flags = _structured_flags(
        candidate,
        {
            "duration_plausible": True,
            "secondary_depth": 0.00045,
            "secondary_snr": 6.1,
            "odd_even_depth_delta": 0.0,
            "false_positive_flags": ("secondary_eclipse",),
        },
        config,
        {
            "observed_transit_count": 10,
            "known_planet": {"planet": "HAT-P-7 b", "allow_planetary_secondary": True},
            "planetary_secondary_allowed": True,
        },
    )

    assert any(flag["code"] == "planetary_secondary" and flag["severity"] == "warning" for flag in flags)
    assert not any(flag["code"] == "secondary_eclipse" and flag["severity"] == "hard_fail" for flag in flags)
    assert _disposition(candidate, flags, config)[0] != "rejected_signal"


def test_weak_residual_signal_is_hard_rejected():
    config = load_science_config()
    candidate = TransitCandidate(1.775, 0.2, 0.03, 0.002, 9.0, 5.2)

    flags = _structured_flags(
        candidate,
        {"duration_plausible": True, "secondary_depth": 0.0, "odd_even_depth_delta": 0.0},
        config,
        {
            "observed_transit_count": 8,
            "candidate_rank": 2,
            "primary_signal_to_noise": 6.0,
            "effective_snr": 5.2,
            "is_residual": True,
        },
    )

    assert any(flag["code"] == "weak_residual_signal" and flag["severity"] == "hard_fail" for flag in flags)
    assert _disposition(candidate, flags, config)[0] == "rejected_signal"


def test_guided_known_trappist_period_preempts_short_artifact(monkeypatch):
    artifact = TransitCandidate(0.20217, 0.1, 0.16, 0.001, 30.0, 8.1)
    trappist_b = TransitCandidate(1.51087, 0.25, 0.035, 0.002, 18.0, 5.5)

    class _BlsResult:
        def __init__(self, candidate):
            self.candidate = candidate
            self.periodogram = {
                "period": np.array([candidate.period], dtype=np.float32),
                "power": np.array([candidate.power], dtype=np.float32),
                "duration": np.array([candidate.duration], dtype=np.float32),
            }
            self.search_time = np.linspace(0, 24, 1200, dtype=np.float32)
            self.search_flux = 1.0 + 0.001 * np.sin(np.linspace(0, 18, 1200, dtype=np.float32))
            self.clean_time = self.search_time
            self.clean_flux = self.search_flux
            self.metadata = {"min_period_days": 0.2, "max_period_days": 12.0}

    def fake_run_bls(clean_time, clean_flux, **kwargs):
        del clean_time, clean_flux
        min_period = kwargs.get("min_period", 0.0)
        max_period = kwargs.get("max_period", 99.0)
        if min_period <= trappist_b.period <= max_period and max_period < 2.0:
            return _BlsResult(trappist_b)
        if min_period <= artifact.period <= max_period and max_period >= 10.0:
            return _BlsResult(artifact)
        raise ValueError("no guided signal in this window")

    monkeypatch.setattr("orbitlab.science.pipeline.run_bls", fake_run_bls)
    monkeypatch.setattr(
        "orbitlab.science.pipeline.find_multi_planet_candidates",
        lambda clean_time, clean_flux, max_candidates, initial_candidate, min_period, max_period, **kwargs: [
            initial_candidate
        ],
    )

    time, flux = _light_curve(period=trappist_b.period)
    payload = analyze_light_curve_arrays(
        target_id="TRAPPIST-1",
        mission="TESS",
        time=time,
        flux=flux,
        vetting_mode="fast",
        nigraha_service=_UnavailableModel(),
    )

    assert payload["tces"][0]["period_days"] == pytest.approx(trappist_b.period)
    assert payload["tces"][0]["period_source"] == "known_ephemeris"
    assert payload["tces"][0]["catalog_match"]["planet"] == "TRAPPIST-1 b"


def test_bls_preview_uses_target_id_for_known_kepler_period_and_preserves_low_snr(monkeypatch):
    from orbitlab.api.main import bls_preview
    from orbitlab.api.schemas import BlsPreviewCreate

    kepler_b = TransitCandidate(0.837491331, 0.2, 0.04, 0.00015, 7.0, 3.2)
    artifact = TransitCandidate(0.61, 0.1, 0.08, 0.001, 30.0, 8.1)

    class _BlsResult:
        def __init__(self, candidate):
            self.candidate = candidate
            self.periodogram = {
                "period": np.array([candidate.period], dtype=np.float32),
                "power": np.array([candidate.power], dtype=np.float32),
                "duration": np.array([candidate.duration], dtype=np.float32),
            }
            self.search_time = np.linspace(0, 12, 900, dtype=np.float32)
            self.search_flux = 1.0 + 0.001 * np.sin(np.linspace(0, 18, 900, dtype=np.float32))
            self.clean_time = self.search_time
            self.clean_flux = self.search_flux
            self.metadata = {"min_period_days": 0.5, "max_period_days": 2.0}

    def fake_run_bls(clean_time, clean_flux, **kwargs):
        del clean_time, clean_flux
        min_period = kwargs.get("min_period", 0.0)
        max_period = kwargs.get("max_period", 99.0)
        if min_period <= kepler_b.period <= max_period and max_period < 1.0:
            return _BlsResult(kepler_b)
        if min_period <= artifact.period <= max_period:
            return _BlsResult(artifact)
        raise ValueError("no signal in this window")

    time, flux = _light_curve(period=kepler_b.period, depth=0.00015, noise=0.0002)
    monkeypatch.setattr(
        "orbitlab.api.main.extract_light_curve_from_tpf",
        lambda product_uri, aperture_mask="pipeline": (time, flux, None),
    )
    monkeypatch.setattr("orbitlab.api.main.run_bls", fake_run_bls)

    payload = bls_preview(
        BlsPreviewCreate(
            product_uri="mast:test-product-without-kepler-name",
            target_id="Kepler-10",
            mission="Kepler",
            min_period=0.5,
            max_period=2.0,
            max_candidates=1,
        ),
        db=None,
    )

    assert payload["tces"][0]["period_days"] == pytest.approx(kepler_b.period)
    assert payload["tces"][0]["period_source"] == "known_ephemeris"
    assert payload["tces"][0]["catalog_match"]["planet"] == "Kepler-10 b"
    assert any(flag["code"] == "known_period_low_snr" for flag in payload["tces"][0]["flags"])
    assert payload["candidates"] == []


def test_bls_preview_returns_tce_ledger_without_promoting_weak_residual(monkeypatch):
    from orbitlab.api.main import bls_preview
    from orbitlab.api.schemas import BlsPreviewCreate

    primary = TransitCandidate(1.51087, 0.2, 0.035, 0.002, 18.0, 5.8)
    residual = TransitCandidate(1.77503, 0.3, 0.03, 0.0015, 9.0, 5.0)

    class _BlsResult:
        candidate = primary
        periodogram = {
            "period": np.array([primary.period, residual.period], dtype=np.float32),
            "power": np.array([primary.power, residual.power], dtype=np.float32),
            "duration": np.array([primary.duration, residual.duration], dtype=np.float32),
        }
        search_time = np.linspace(0, 24, 1200, dtype=np.float32)
        search_flux = 1.0 + 0.001 * np.sin(np.linspace(0, 18, 1200, dtype=np.float32))
        clean_time = search_time
        clean_flux = search_flux
        metadata = {"min_period_days": 0.5, "max_period_days": 12.0}

    time, flux = _light_curve(period=primary.period)

    monkeypatch.setattr(
        "orbitlab.api.main.extract_light_curve_from_tpf",
        lambda product_uri, aperture_mask="pipeline": (time, flux, None),
    )
    monkeypatch.setattr(
        "orbitlab.api.main._select_primary_candidate",
        lambda clean_time, clean_flux, known_target, config, profile, **kwargs: (primary, _BlsResult(), []),
    )
    monkeypatch.setattr(
        "orbitlab.api.main.find_multi_planet_candidates",
        lambda clean_time, clean_flux, max_candidates, initial_candidate, min_period, max_period, **kwargs: [
            initial_candidate,
            residual,
        ],
    )

    payload = bls_preview(
        BlsPreviewCreate(
            product_uri="tess2023263165758-s0070-0000000278892590-0265-a_fast-tp.fits",
            mission="TESS",
            min_period=0.5,
            max_period=12.0,
            max_candidates=4,
        ),
        db=None,
    )

    assert len(payload["tces"]) == 2
    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["period_days"] == pytest.approx(primary.period)
    assert payload["tces"][1]["disposition"] == "rejected_signal"
    assert any(flag["code"] == "weak_residual_signal" for flag in payload["tces"][1]["flags"])
