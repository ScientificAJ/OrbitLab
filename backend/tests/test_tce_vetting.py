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
        nigraha_service=_UnavailableModel(),
    )

    assert payload["tces"][0]["physics"]["habitability"]["status"] == "insufficient_stellar_data"
    assert payload["tces"][0]["physics"]["is_in_habitable_zone"] is None
