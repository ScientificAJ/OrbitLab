"""Regression coverage for the 2026-06 scientific-accuracy mission fixes.

Each test pins one of the accuracy bugs found by the hardened truth benchmark:
symmetric sigma clipping deleting deep transits, in-transit red-noise
inflation, floor-based odd/even parity splitting, missing-evidence vs
evidence-against disposition semantics, and broad-grid period smearing.
"""

from __future__ import annotations

import numpy as np
import pytest
from orbitlab.science.bls import TransitCandidate, run_bls, sigma_clip_flux
from orbitlab.science.evidence import estimate_red_noise_beta, out_of_transit_residuals
from orbitlab.science.pipeline import (
    MISSING_EVIDENCE_FLAG_CODES,
    SOFT_REVIEW_WARNING_CODES,
    _disposition,
    _observed_transit_count,
    _supported_transit_count,
)
from orbitlab.science.science_config import load_science_config
from orbitlab.science.validation import odd_even_depths_with_uncertainty, odd_even_significance


def _transit_curve(
    *,
    period: float = 3.0,
    depth: float = 0.01,
    duration: float = 0.12,
    epoch: float = 0.45,
    noise: float = 2.0e-4,
    baseline_days: float = 27.0,
    cadences: int = 1800,
    seed: int = 5,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    time = np.linspace(0.0, baseline_days, cadences)
    flux = 1.0 + rng.normal(0.0, noise, size=time.size)
    phase = ((time - epoch + 0.5 * period) % period) - 0.5 * period
    flux[np.abs(phase) <= 0.5 * duration] -= depth
    return time, flux


def test_sigma_clip_preserves_deep_transits_and_removes_positive_outliers():
    time, flux = _transit_curve(depth=0.008, noise=2.0e-4)  # ~40-sigma-deep transit
    flux_with_flare = flux.copy()
    flux_with_flare[100] += 0.05  # positive outlier must be removed

    clipped_time, clipped_flux = sigma_clip_flux(time, flux_with_flare)

    assert float(np.nanmin(clipped_flux)) < 1.0 - 0.007, "deep transit cadences must survive clipping"
    assert float(np.nanmax(clipped_flux)) < 1.0 + 0.04, "positive flare outlier must be clipped"
    assert clipped_time.size == time.size - 1


def test_red_noise_beta_is_not_inflated_by_the_transit_itself():
    time, flux = _transit_curve(depth=0.01, noise=2.0e-4)
    candidate = TransitCandidate(period=3.0, epoch=0.45, duration=0.12, depth=0.01, power=10.0, signal_to_noise=50.0)

    naive_beta = estimate_red_noise_beta(flux - np.nanmedian(flux))
    oot_beta = estimate_red_noise_beta(out_of_transit_residuals(time, flux, candidate))

    assert naive_beta > 1.5, "sanity: in-transit residuals fake red noise for deep transits"
    assert oot_beta < 1.2, "out-of-transit residuals must show the true white-noise floor"


def test_odd_even_parity_uses_event_centered_numbering():
    # Alternating eclipse depths at exactly the found (half) period: the
    # odd/even discriminator must see two clean depth populations.
    rng = np.random.default_rng(11)
    time = np.linspace(0.0, 27.0, 2700)
    flux = 1.0 + rng.normal(0.0, 4.0e-4, size=time.size)
    period, epoch, duration = 3.2, 0.8, 0.14
    phase = ((time - epoch + 0.5 * period) % period) - 0.5 * period
    event_number = np.round((time - epoch) / period).astype(int)
    in_transit = np.abs(phase) <= 0.5 * duration
    flux[in_transit & (event_number % 2 == 0)] -= 0.005
    flux[in_transit & (event_number % 2 == 1)] -= 0.003

    candidate = TransitCandidate(
        period=period, epoch=epoch, duration=duration, depth=0.004, power=10.0, signal_to_noise=30.0
    )
    odd_depth, even_depth, odd_err, even_err = odd_even_depths_with_uncertainty(time, flux, candidate)
    sigma = odd_even_significance(odd_depth, even_depth, odd_err, even_err)

    assert abs(odd_depth - even_depth) == pytest.approx(0.002, rel=0.25)
    assert sigma is not None and sigma >= 3.0


def test_observed_transit_count_counts_each_event_once():
    period, epoch, duration = 3.0, 0.45, 0.12
    time = np.linspace(0.0, 27.0, 5400)
    candidate = TransitCandidate(
        period=period, epoch=epoch, duration=duration, depth=0.005, power=10.0, signal_to_noise=20.0
    )
    # 27 / 3 = 9 events fit the baseline; epoch-centered events must not be
    # double-counted across the floor boundary.
    assert _observed_transit_count(time, candidate) == 9


def test_supported_transit_count_rejects_single_event_period_alias():
    time = np.linspace(0.0, 27.0, 5400)
    flux = np.ones_like(time)
    flux[(time >= 13.0) & (time <= 13.3)] -= 0.01
    candidate = TransitCandidate(13.5, 13.15, 0.3, 0.01, 10.0, 20.0)

    assert _observed_transit_count(time, candidate) >= 2
    assert _supported_transit_count(time, flux, candidate, min_depth_fraction=0.5) == 1


def test_disposition_missing_evidence_blocks_promotion_without_rejection():
    config = load_science_config()
    candidate = TransitCandidate(2.0, 0.1, 0.08, 0.002, 9.0, 12.0)
    missing_only = [
        {"code": "triceratops_required", "severity": "hard_fail", "message": "engine unavailable"},
        {"code": "nigraha_required", "severity": "hard_fail", "message": "weights absent"},
    ]
    disposition, action, _, score = _disposition(
        candidate, missing_only, config, {"effective_snr": 12.0, "final_score": 0.9}
    )
    assert disposition == "borderline_tce"
    assert action == "review_needed"
    assert score <= 0.64

    evidence_against = missing_only + [
        {"code": "secondary_eclipse", "severity": "hard_fail", "message": "secondary detected"}
    ]
    assert _disposition(candidate, evidence_against, config, {"effective_snr": 12.0, "final_score": 0.9})[0] == (
        "rejected_signal"
    )
    assert set(MISSING_EVIDENCE_FLAG_CODES) >= {"triceratops_required", "nigraha_required"}


def test_disposition_allows_strong_signal_with_only_soft_warnings():
    config = load_science_config()
    candidate = TransitCandidate(2.0, 0.1, 0.08, 0.002, 9.0, 40.0)
    soft_flags = [
        {"code": "red_noise", "severity": "warning", "message": "beta already deflates effective SNR"},
        {"code": "catalog_contamination", "severity": "warning", "message": "crowded field"},
    ]
    disposition, *_ = _disposition(candidate, soft_flags, config, {"effective_snr": 20.0, "final_score": 0.88})
    assert disposition == "planet_candidate"
    assert "red_noise" in SOFT_REVIEW_WARNING_CODES

    hard_warning = soft_flags + [{"code": "low_snr", "severity": "warning", "message": "weak"}]
    disposition, *_ = _disposition(candidate, hard_warning, config, {"effective_snr": 20.0, "final_score": 0.88})
    assert disposition == "borderline_tce"


def test_run_bls_refines_period_to_fine_grid_accuracy():
    time, flux = _transit_curve(period=2.0, depth=0.008, duration=0.15, epoch=0.4, noise=5.0e-4, seed=3)

    result = run_bls(time, flux, min_period=0.5, max_period=10.0, period_samples=4096)

    assert result.metadata["period_refinement"]["applied"] is True
    assert abs(result.candidate.period - 2.0) / 2.0 < 5e-4, "refined period must beat broad-grid spacing"
    assert result.candidate.depth == pytest.approx(0.008, rel=0.2)


def test_odd_even_hard_fail_requires_real_sampling():
    from orbitlab.science.pipeline import _structured_flags

    config = load_science_config()
    candidate = TransitCandidate(3.69, 0.5, 0.04, 0.0015, 10.0, 18.0)
    base_validation = {
        "duration_plausible": True,
        "odd_even_sigma": config.odd_even_hard_fail_sigma + 0.5,
        "secondary_depth": 0.0,
    }

    sparse = _structured_flags(
        candidate,
        base_validation | {"odd_even_min_points": 2, "odd_even_min_events": 2},
        config,
        {"effective_snr": 15.0},
    )
    sparse_flag = next(flag for flag in sparse if flag["code"] == "odd_even_depth_mismatch")
    assert sparse_flag["severity"] == "warning", "1-2 points per event cannot support a hard binary verdict"

    sampled = _structured_flags(
        candidate,
        base_validation | {"odd_even_min_points": 12, "odd_even_min_events": 4},
        config,
        {"effective_snr": 15.0},
    )
    sampled_flag = next(flag for flag in sampled if flag["code"] == "odd_even_depth_mismatch")
    assert sampled_flag["severity"] == "hard_fail"


def test_odd_even_sampling_counts_points_and_events():
    from orbitlab.science.validation import odd_even_sampling

    time = np.linspace(0.0, 24.0, 1152)  # 30-minute cadence
    flux = np.ones_like(time)
    candidate = TransitCandidate(3.69, 0.5, 0.04, 0.0015, 10.0, 18.0)
    min_points, min_events = odd_even_sampling(time, flux, candidate)
    assert min_events >= 2
    assert min_points <= 8, "30-minute cadence yields only a couple of in-transit points per event"


def test_odd_even_uncertainty_respects_event_to_event_depth_variation():
    rng = np.random.default_rng(29)
    period, epoch, duration = 3.2, 0.8, 0.16
    time = np.linspace(0.0, 27.0, 5400)
    flux = 1.0 + rng.normal(0.0, 2.0e-4, size=time.size)
    event_number = np.round((time - epoch) / period).astype(int)
    phase = ((time - epoch + 0.5 * period) % period) - 0.5 * period
    in_transit = np.abs(phase) <= 0.5 * duration
    # Both parity populations describe the same planet-depth distribution,
    # but ordinary transit-to-transit variability makes their sample medians
    # differ. Pooled-cadence errors would become overconfident here.
    event_offsets = {event: rng.normal(0.0, 4.0e-4) for event in np.unique(event_number[in_transit])}
    for event, offset in event_offsets.items():
        flux[in_transit & (event_number == event)] -= 0.004 + offset

    candidate = TransitCandidate(period, epoch, duration, 0.004, 10.0, 30.0)
    odd_depth, even_depth, odd_err, even_err = odd_even_depths_with_uncertainty(time, flux, candidate)
    sigma = odd_even_significance(odd_depth, even_depth, odd_err, even_err)

    assert sigma is not None and sigma < 3.0


def test_large_pooled_odd_even_effect_still_rejects_binary():
    from orbitlab.science.pipeline import _structured_flags

    config = load_science_config()
    candidate = TransitCandidate(2.0, 0.4, 0.1, 0.01, 10.0, 30.0)
    flags = _structured_flags(
        candidate,
        {
            "duration_plausible": True,
            "secondary_depth": 0.0,
            "odd_even_depth_delta": 0.0025,
            "odd_even_sigma": 1.8,
            "odd_even_pooled_sigma": 5.7,
            "odd_even_min_points": 70,
            "odd_even_min_events": 7,
        },
        config,
        {"effective_snr": 20.0},
    )
    flag = next(flag for flag in flags if flag["code"] == "odd_even_depth_mismatch")
    assert flag["severity"] == "hard_fail"


def test_triceratops_tic_fallback_from_product_uri():
    from orbitlab.science.triceratops_fpp import parse_tic_from_product_uri

    hlsp = (
        "mast:HLSP/tess-spoc/s0008/target/0000/0003/0721/0830/"
        "hlsp_tess-spoc_tess_phot_0000000307210830-s0008_tess_v1_tp.fits"
    )
    spoc = "mast:TESS/product/tess2018234235059-s0002-0000000307210830-0121-s_tp.fits"
    assert parse_tic_from_product_uri(hlsp) == 307210830
    assert parse_tic_from_product_uri(spoc) == 307210830
    assert parse_tic_from_product_uri("no-tic-here.fits") is None
    assert parse_tic_from_product_uri(None) is None


def test_model_shift_engine_failure_degrades_to_missing_evidence(tmp_path):
    from orbitlab.science.dave_vetting import run_model_shift

    time = np.linspace(0.0, 10.0, 500)
    flux = np.ones_like(time)
    candidate = TransitCandidate(2.0, 0.4, 0.1, 0.002, 9.0, 10.0)
    report = run_model_shift(time, flux, candidate, modshift_binary=tmp_path / "missing-binary")

    assert report["status"] == "failed"
    assert "missing" in report["detail"].lower() or "RuntimeError" in report["detail"]


def test_product_cadence_inference_and_ranking():
    from orbitlab.science.mast import ProductSummary, infer_cadence_seconds, rank_products_by_cadence

    hlsp = "mast:HLSP/tess-spoc/s0008/target/.../hlsp_tess-spoc_tess_phot_0000000307210830-s0008_tess_v1_tp.fits"
    spoc_2min = "mast:TESS/product/tess2018234235059-s0002-0000000307210830-0121-s_tp.fits"
    kepler_lc = "mast:Kepler/url/.../kplr011904151-2009131105131_lpd-targ.fits.gz"

    assert infer_cadence_seconds(hlsp) == 1800.0
    assert infer_cadence_seconds(spoc_2min) == 120.0
    assert infer_cadence_seconds(kepler_lc) == 1800.0
    assert infer_cadence_seconds("unknown.fits") is None
    assert infer_cadence_seconds("unknown.fits", exptime=120.0) == 120.0

    def _product(uri, cadence):
        return ProductSummary(
            product_id=uri, mission="TESS", description="", size=None, product_uri=uri, cadence_seconds=cadence
        )

    ranked = rank_products_by_cadence(
        [_product(hlsp, 1800.0), _product("u.fits", None), _product(spoc_2min, 120.0)]
    )
    assert [item.cadence_seconds for item in ranked] == [120.0, 1800.0, None]


def test_nigraha_out_of_domain_cadence_is_missing_evidence_not_a_low_score():
    from orbitlab.science.evidence import _ml_probability
    from orbitlab.science.pipeline import _apply_paper_grade_vetting

    config = load_science_config()
    candidate = TransitCandidate(3.69, 0.5, 0.04, 0.0015, 10.0, 18.0)
    flags: list[dict] = []
    _apply_paper_grade_vetting(
        flags=flags,
        candidate=candidate,
        config=config,
        support={"effective_snr": 18.0, "observed_transit_count": 6},
        tls={"status": "complete", "sde": 18.0, "distinct_transit_count": 6},
        model_shift={"status": "pass", "hard_fail": False},
        sweet={"status": "pass"},
        ml={"probability": 0.0009, "cadence_out_of_domain": True},
        catalog_context={},
        fpp={"status": "complete", "fpp": 0.001, "nfpp": 0.0001},
        mission_upper="TESS",
    )
    codes = {flag["code"]: flag["severity"] for flag in flags}
    assert codes.get("nigraha_out_of_domain") == "hard_fail"
    assert "nigraha_low_probability" not in codes
    assert "nigraha_out_of_domain" in MISSING_EVIDENCE_FLAG_CODES

    assert _ml_probability({"probability": 0.0009, "cadence_out_of_domain": True}) is None
    assert _ml_probability({"probability": 0.7}) == pytest.approx(0.7)


def test_triceratops_inconclusive_zone_is_review_not_rejection():
    from orbitlab.science.pipeline import _apply_paper_grade_vetting

    config = load_science_config()
    candidate = TransitCandidate(3.2876, 0.5, 0.1, 0.0063, 12.0, 30.0)

    def gate(fpp_payload):
        flags: list[dict] = []
        _apply_paper_grade_vetting(
            flags=flags,
            candidate=candidate,
            config=config,
            support={"effective_snr": 30.0, "observed_transit_count": 8},
            tls={"status": "complete", "sde": 25.0, "distinct_transit_count": 8},
            model_shift={"status": "pass", "hard_fail": False},
            sweet={"status": "pass"},
            ml={"probability": 0.9},
            catalog_context={},
            fpp=fpp_payload,
            mission_upper="TESS",
        )
        return {flag["code"]: flag["severity"] for flag in flags}

    # WASP-126 b live values (confirmed planet): the Giacalone et al. 2021
    # gray zone withholds validation but is not evidence against.
    codes = gate({"status": "complete", "fpp": 0.0704, "nfpp": 0.0278})
    assert codes.get("triceratops_fpp_inconclusive") == "warning"
    assert codes.get("triceratops_nfpp_inconclusive") == "warning"
    assert "triceratops_fpp" not in codes
    assert "triceratops_nfpp" not in codes

    # The rejection zone still hard-fails outright.
    assert gate({"status": "complete", "fpp": 0.62, "nfpp": 0.0})["triceratops_fpp"] == "hard_fail"
    assert gate({"status": "complete", "fpp": 0.001, "nfpp": 0.2})["triceratops_nfpp"] == "hard_fail"

    # The validation zone adds no TRICERATOPS flags at all.
    validated = gate({"status": "complete", "fpp": 0.001, "nfpp": 0.0001})
    assert not any(code.startswith("triceratops") for code in validated)

    # A partial payload is missing evidence, never a false-positive verdict.
    assert gate({"status": "complete", "fpp": 0.001, "nfpp": None})["triceratops_required"] == "hard_fail"

    # Inconclusive warnings are soft review context: a strong candidate stays
    # promotable instead of being rejected on a gray-zone statistic.
    assert {"triceratops_fpp_inconclusive", "triceratops_nfpp_inconclusive"} <= SOFT_REVIEW_WARNING_CODES
    soft_flags = [
        {"code": "triceratops_fpp_inconclusive", "severity": "warning", "message": "gray zone"},
        {"code": "triceratops_nfpp_inconclusive", "severity": "warning", "message": "gray zone"},
    ]
    disposition, *_ = _disposition(candidate, soft_flags, config, {"effective_snr": 30.0, "final_score": 0.9})
    assert disposition == "planet_candidate"


def test_trilegal_ca_bundle_failure_is_tolerated(monkeypatch, tmp_path):
    import orbitlab.science.triceratops_fpp as tf

    monkeypatch.setattr(tf, "_calibration_dir", lambda: tmp_path)

    def _refuse(*args, **kwargs):
        raise OSError("no network")

    monkeypatch.setattr(tf.urllib.request, "urlopen", _refuse)
    assert tf.ensure_trilegal_ca_bundle() is None

    prebuilt = tmp_path / "trilegal-ca-bundle.pem"
    prebuilt.write_text("# already built", encoding="utf-8")
    assert tf.ensure_trilegal_ca_bundle() == prebuilt


def test_repaired_ca_environment_sets_and_restores(monkeypatch, tmp_path):
    import os

    import orbitlab.science.triceratops_fpp as tf

    bundle = tmp_path / "bundle.pem"
    bundle.write_text("x", encoding="utf-8")
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    with tf._repaired_ca_environment(bundle):
        assert os.environ["REQUESTS_CA_BUNDLE"] == str(bundle)
        assert os.environ["SSL_CERT_FILE"] == str(bundle)
    assert "REQUESTS_CA_BUNDLE" not in os.environ
    with tf._repaired_ca_environment(None):
        assert "REQUESTS_CA_BUNDLE" not in os.environ


def test_cached_trilegal_file_is_passed_to_triceratops(monkeypatch, tmp_path):
    import sys
    import types

    import orbitlab.science.triceratops_fpp as tf

    monkeypatch.setattr(tf, "_calibration_dir", lambda: tmp_path)
    cached = tmp_path / "trilegal" / "307210830_TRILEGAL.csv"
    cached.parent.mkdir(parents=True)
    cached.write_text("stars", encoding="utf-8")

    captured: dict = {}

    class _FakeTarget:
        FPP = 0.005
        NFPP = 0.0001
        probs = None

        def __init__(self, **kwargs):
            captured.update(kwargs)

        def calc_probs(self, **kwargs):
            captured["calc_probs"] = True

    fake_module = types.ModuleType("triceratops.triceratops")
    fake_module.target = _FakeTarget
    monkeypatch.setitem(sys.modules, "triceratops", types.ModuleType("triceratops"))
    monkeypatch.setitem(sys.modules, "triceratops.triceratops", fake_module)

    time = np.linspace(0.0, 10.0, 600)
    flux = 1.0 + np.random.default_rng(3).normal(0.0, 3.0e-4, time.size)
    candidate = TransitCandidate(2.0, 0.4, 0.1, 0.002, 9.0, 10.0)
    report = tf.run_triceratops_fpp(
        target_id="L 98-59",
        product_uri="hlsp_tess-spoc_tess_phot_0000000307210830-s0008_tess_v1_tp.fits",
        time=time,
        flux=flux,
        candidate=candidate,
        samples=1000,
    )

    assert captured["trilegal_fname"] == str(cached)
    assert captured["calc_probs"] is True
    assert report["status"] == "complete"
    assert report["target_id"] == 307210830, "TIC must be recovered from the product URI for name searches"
    assert report["trilegal_source"] == "cached_file"


def test_triceratops_retries_alternate_monte_carlo_path_and_rejects_nonfinite(monkeypatch, tmp_path):
    import sys
    import types

    import orbitlab.science.triceratops_fpp as tf

    monkeypatch.setattr(tf, "_calibration_dir", lambda: tmp_path)
    cached = tmp_path / "trilegal" / "307210830_TRILEGAL.csv"
    cached.parent.mkdir(parents=True)
    cached.write_text("stars", encoding="utf-8")

    attempts: list[bool] = []

    class _RetryTarget:
        FPP = 0.01
        NFPP = 0.0001
        probs = None

        def __init__(self, **kwargs):
            pass

        def calc_probs(self, **kwargs):
            attempts.append(kwargs["parallel"])
            if len(attempts) == 1:
                raise IndexError("invalid index to scalar variable")

    fake_module = types.ModuleType("triceratops.triceratops")
    fake_module.target = _RetryTarget
    monkeypatch.setitem(sys.modules, "triceratops", types.ModuleType("triceratops"))
    monkeypatch.setitem(sys.modules, "triceratops.triceratops", fake_module)
    candidate = TransitCandidate(2.0, 0.4, 0.1, 0.002, 9.0, 10.0)
    time = np.linspace(0.0, 10.0, 600)
    flux = np.ones_like(time)

    report = tf.run_triceratops_fpp(
        target_id="L 98-59",
        product_uri="hlsp_tess-spoc_tess_phot_0000000307210830-s0008_tess_v1_tp.fits",
        time=time,
        flux=flux + np.random.default_rng(4).normal(0.0, 3.0e-4, time.size),
        candidate=candidate,
        samples=1000,
        parallel=True,
    )
    assert attempts == [True, False]
    assert report["parallel"] is False

    _RetryTarget.FPP = float("nan")
    with pytest.raises(RuntimeError, match="non-finite FPP/NFPP"):
        tf.run_triceratops_fpp(
            target_id="L 98-59",
            product_uri="hlsp_tess-spoc_tess_phot_0000000307210830-s0008_tess_v1_tp.fits",
            time=time,
            flux=flux + np.random.default_rng(5).normal(0.0, 3.0e-4, time.size),
            candidate=candidate,
            samples=1000,
        )


def test_detrending_sensitivity_masked_variant_keeps_the_transit():
    from orbitlab.science.detrending_sensitivity import run_detrending_sensitivity

    rng = np.random.default_rng(9)
    time = np.linspace(0.0, 27.0, 2700)
    trend = 1.0 + 0.002 * np.sin(2.0 * np.pi * time / 11.0)
    flux = trend + rng.normal(0.0, 3.0e-4, size=time.size)
    period, epoch, duration = 3.0, 0.45, 0.12
    phase = ((time - epoch + 0.5 * period) % period) - 0.5 * period
    flux[np.abs(phase) <= 0.5 * duration] -= 0.006

    candidate = TransitCandidate(
        period=period, epoch=epoch, duration=duration, depth=0.006, power=10.0, signal_to_noise=25.0
    )
    report = run_detrending_sensitivity(time, flux, candidate)

    assert report["status"] == "passed", report
    masked = [m for m in report["methods"] if m.get("label") == "transit_masked_wotan_biweight_0.75d"]
    assert masked and masked[0]["status"] == "passed"
    assert masked[0]["period_error_fraction"] is not None and masked[0]["period_error_fraction"] <= 0.02


def test_sweet_requires_amplitude_comparable_to_depth():
    from orbitlab.science.dave_vetting import run_sweet_test

    rng = np.random.default_rng(7)
    time = np.linspace(0.0, 27.0, 18000)

    # Deep planet on a star with a real-but-tiny sinusoid (56 ppm vs 6000 ppm
    # depth): the WASP-126 b live false-warning case. Statistically the sine
    # is many sigma, but it cannot be what the search detected.
    cand = TransitCandidate(3.2872, 0.5, 0.15, 0.006, 12.0, 30.0)
    phase = ((time - cand.epoch + 0.5 * cand.period) % cand.period) - 0.5 * cand.period
    flux = 1.0 + rng.normal(0, 4e-4, time.size) + 6e-5 * np.sin(2 * np.pi * time / (cand.period / 2))
    flux[np.abs(phase) <= 0.5 * cand.duration] -= cand.depth
    report = run_sweet_test(time, flux, cand)
    assert report["status"] == "pass"
    assert report["variability_detected"] is True
    assert report["max_sigma"] > 3.0
    assert all("amplitude_depth_ratio" in row for row in report["periods"])

    # A sinusoid masquerading as the candidate itself (amplitude == reported
    # depth) is the genuine Robovetter sine-wave-event signature: still warns.
    amp = 0.002
    flux2 = 1.0 + rng.normal(0, 3e-4, time.size) + amp * np.sin(2 * np.pi * time / 2.0)
    cand2 = TransitCandidate(2.0, 0.5, 0.2, amp, 12.0, 9.0)
    report2 = run_sweet_test(time, flux2, cand2)
    assert report2["status"] == "warning"
    ratios = {row["period_label"]: row["amplitude_depth_ratio"] for row in report2["periods"]}
    assert ratios["period"] == pytest.approx(1.0, abs=0.15)


def test_sweet_variability_note_is_info_not_blocking():
    from orbitlab.science.pipeline import _apply_paper_grade_vetting

    config = load_science_config()
    candidate = TransitCandidate(3.2876, 0.5, 0.1, 0.006, 12.0, 30.0)
    flags: list[dict] = []
    _apply_paper_grade_vetting(
        flags=flags,
        candidate=candidate,
        config=config,
        support={"effective_snr": 30.0, "observed_transit_count": 8},
        tls={"status": "complete", "sde": 25.0, "distinct_transit_count": 8},
        model_shift={"status": "pass", "hard_fail": False},
        sweet={"status": "pass", "variability_detected": True},
        ml={"probability": 0.9},
        catalog_context={},
        fpp={"status": "complete", "fpp": 0.001, "nfpp": 0.0001},
        mission_upper="TESS",
    )
    codes = {flag["code"]: flag["severity"] for flag in flags}
    assert codes.get("stellar_variability_note") == "info"
    assert "sweet_sinusoid" not in codes

    # Info flags must not block a strong promotion.
    info_flags = [{"code": "stellar_variability_note", "severity": "info", "message": "context"}]
    disposition, *_ = _disposition(candidate, info_flags, config, {"effective_snr": 30.0, "final_score": 0.9})
    assert disposition == "planet_candidate"


def test_nigraha_depth_features_use_tls_flux_convention():
    from orbitlab.ml.nigraha_adapter import build_nigraha_tensors

    rng = np.random.default_rng(5)
    time = np.linspace(0.0, 27.0, 6000)
    depth = 0.006
    cand = TransitCandidate(3.2872, 0.8, 0.12, depth, 12.0, 30.0)
    phase = ((time - cand.epoch + 0.5 * cand.period) % cand.period) - 0.5 * cand.period
    flux = 1.0 + rng.normal(0, 3e-4, time.size)
    flux[np.abs(phase) <= 0.5 * cand.duration] -= depth

    tensors = build_nigraha_tensors(time, flux, cand, stellar_teff=5800.0, stellar_radius_solar=1.0)

    # Upstream training catalog (period_info-tces-dl3.csv) stores these as the
    # TLS mean in-transit flux: 1 - depth_fraction, observed range ~0.27..1.0.
    assert float(tensors.scalar_features["Depth"][0, 0]) == pytest.approx(1.0 - depth, abs=1e-6)
    for name in ("Depth", "DepthEven", "DepthOdd"):
        value = float(tensors.scalar_features[name][0, 0])
        assert 0.27 <= value <= 1.0, f"{name}={value} outside the upstream training range"


@pytest.mark.skipif(
    not __import__("pathlib").Path(".orbitlab/models/nigraha/global_nodropout").exists(),
    reason="Nigraha ensemble weights not present (run from repo root)",
)
def test_nigraha_scores_deep_and_shallow_planets_in_domain():
    from orbitlab.ml.nigraha_adapter import build_nigraha_tensors
    from orbitlab.ml.nigraha_service import NigrahaService

    rng = np.random.default_rng(11)
    time = np.linspace(0.0, 27.0, 18000)
    service = NigrahaService()

    def probability(depth):
        cand = TransitCandidate(3.2872, 0.8, 0.12, depth, 12.0, 30.0)
        phase = ((time - cand.epoch + 0.5 * cand.period) % cand.period) - 0.5 * cand.period
        flux = 1.0 + rng.normal(0, 3e-4, time.size)
        in_transit = np.abs(phase) <= 0.5 * cand.duration
        flux[in_transit] -= depth * np.clip(
            (0.5 * cand.duration - np.abs(phase[in_transit])) / (0.1 * cand.duration), 0, 1
        )
        tensors = build_nigraha_tensors(time, flux, cand, stellar_teff=5800.0, stellar_radius_solar=1.0)
        return service.predict(tensors).probability

    deep = probability(0.006)  # hot-Jupiter class; scored 0.31 before the units fix
    shallow = probability(0.001)
    assert deep > 0.5, f"deep transit must score in-domain, got {deep}"
    assert shallow > 0.5, f"shallow transit must keep scoring well, got {shallow}"

    # Discrimination must survive the fix: a no-signal curve scores near zero.
    noise_cand = TransitCandidate(3.2872, 0.8, 0.12, 0.002, 12.0, 30.0)
    noise_tensors = build_nigraha_tensors(
        time, 1.0 + rng.normal(0, 3e-4, time.size), noise_cand, stellar_teff=5800.0, stellar_radius_solar=1.0
    )
    assert service.predict(noise_tensors).probability < 0.1


def test_sibling_tce_masking_unblocks_multiplanet_members():
    from orbitlab.science.dave_vetting import run_model_shift
    from orbitlab.science.pipeline import _vetting_arrays_for_candidate

    rng = np.random.default_rng(17)
    time = np.linspace(0.0, 27.0, 19440)
    flux = 1.0 + rng.normal(0, 2e-4, time.size)
    inner = TransitCandidate(3.6907, 1.2, 0.045, 0.0005, 12.0, 16.0)
    outer = TransitCandidate(7.4513, 3.0, 0.05, 0.0004, 9.0, 9.0)
    for planet in (inner, outer):
        phase = ((time - planet.epoch + 0.5 * planet.period) % planet.period) - 0.5 * planet.period
        flux[np.abs(phase) <= 0.5 * planet.duration] -= planet.depth

    vetting_time, vetting_flux, masked = _vetting_arrays_for_candidate(time, flux, outer, [inner, outer])
    assert masked == 1
    assert vetting_time.size < time.size

    # The live L 98-59 d failure mode: the sibling's transits read as a
    # significant secondary and hard-fail a real planet.
    contaminated = run_model_shift(time, flux, outer, objects_evaluated=20000)
    assert contaminated["hard_fail"] is True
    assert "sig_sec_in_model_shift" in contaminated["flags"]

    cleaned = run_model_shift(vetting_time, vetting_flux, outer, objects_evaluated=20000)
    assert cleaned["hard_fail"] is False
    assert cleaned["flags"] == []

    # Pathological masking (commensurate windows) falls back to unmasked
    # rather than gutting the candidate's own transits.
    twin = TransitCandidate(outer.period, outer.epoch, outer.duration, 0.0006, 9.0, 9.0)
    fallback_time, _, fallback_masked = _vetting_arrays_for_candidate(time, flux, outer, [twin, outer])
    assert fallback_masked == 0
    assert fallback_time.size == time.size
