from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from orbitlab.benchmarks.science_benchmark import (
    BenchmarkCase,
    _BenchmarkUnavailableModel,
    _default_cases,
    benchmark_report_markdown,
    run_science_benchmark,
    write_benchmark_reports,
)
from orbitlab.science.bls import TransitCandidate
from orbitlab.science.detrending_sensitivity import run_detrending_sensitivity
from orbitlab.science.evidence_packet import build_evidence_packet_files, write_evidence_packet
from orbitlab.science.injection_recovery import (
    inject_tls_like_transit,
    run_recovery_grid,
    summarize_recovery,
)
from orbitlab.science.pipeline import _attach_ml_domain_evidence
from orbitlab.science.sector_consistency import (
    SectorObservation,
    infer_sector_id,
    summarize_sector_consistency,
)


def test_recovery_grid_reports_tls_like_sensitivity():
    time = np.linspace(0, 18, 1800, dtype=np.float32)
    flux = 1.0 + 0.0001 * np.sin(time).astype(np.float32)
    injected = inject_tls_like_transit(time, flux, period_days=3.0, depth_ppm=6000, duration_hours=3.0)

    assert float(np.nanmin(injected)) < float(np.nanmedian(flux))

    cases = run_recovery_grid(
        time,
        flux,
        period_days=(3.0,),
        depth_ppm=(6000.0,),
        duration_hours=(3.0,),
        injection_models=("tls_like",),
        tolerance_fraction=0.2,
    )
    summary = summarize_recovery(cases)

    assert len(cases) == 1
    assert cases[0].injection_model == "tls_like"
    assert summary["total_cases"] == 1
    assert summary["minimum_detectable_depth_ppm"] == 6000.0
    assert summary["period_sensitivity"]["3"]["total"] == 1


def test_detrending_sensitivity_flags_stable_methods(monkeypatch):
    candidate = TransitCandidate(period=2.0, epoch=0.1, duration=0.1, depth=0.002, power=9.0, signal_to_noise=10.0)
    time = np.linspace(0, 12, 500)
    flux = np.ones_like(time)

    class _BlsResult:
        def __init__(self):
            self.candidate = candidate

    monkeypatch.setattr(
        "orbitlab.science.detrending_sensitivity.detrend_with_wotan",
        lambda time, flux, **kwargs: (np.asarray(flux), {"status": "complete"}),
    )
    monkeypatch.setattr("orbitlab.science.detrending_sensitivity.run_bls", lambda *args, **kwargs: _BlsResult())

    result = run_detrending_sensitivity(time, flux, candidate)

    assert result["status"] == "passed"
    assert result["methods_tested"] >= 4
    assert result["period_stable"] is True
    assert result["worst_case_result"]["snr"] == 10.0


def test_ml_domain_evidence_marks_vetting_conflict():
    ml = {
        "probability": 0.91,
        "threshold": 0.4,
        "label": "planet-candidate",
        "preprocessing_compatible": True,
        "input_tensor_checksum": "tensor",
    }
    flags = [{"code": "secondary_eclipse", "severity": "hard_fail", "message": "secondary"}]

    enriched = _attach_ml_domain_evidence(
        ml,
        mission_upper="TESS",
        flags=flags,
        physics={"planet_radius_earth": 2.0, "stellar_context_source": "user_supplied"},
    )

    assert enriched["domain_awareness"]["status"] == "passed"
    assert enriched["evidence_conflicts"]["status"] == "inconclusive"
    assert "ml_support_conflicts_with_hard_vetting_flags" in enriched["evidence_conflicts"]["conflicts"]


def test_evidence_packet_builds_required_files(tmp_path: Path):
    payload = {
        "result_id": "result-1",
        "target_id": "TIC 1",
        "mission": "TESS",
        "schema_version": "orbitlab.analysis_result.v2",
        "science_config_hash": "abc",
        "vetting_mode": "paper",
        "data_quality": {"baseline_days": 12},
        "light_curve": {"time": [0, 1], "flux": [1.0, 0.99]},
        "periodogram": {"period": [2.0], "power": [12.0], "duration": [0.1]},
        "folded_curves": {"tce-1": {"phase": [0.0], "flux": [0.99]}},
        "planet_candidates": [],
        "tces": [
            {
                "candidate_id": "tce-1",
                "tce_id": "tce-1",
                "period_days": 2.0,
                "epoch_days": 0.1,
                "duration_days": 0.1,
                "depth_ppm": 1000,
                "disposition": "borderline_tce",
                "action_label": "review_needed",
                "detection_metrics": {"effective_snr": 5.0},
                "vetting": {"secondary_eclipse": {"snr": 0.0}},
                "catalog_context": {"status": "passed"},
                "fpp": {"fpp": 0.01},
                "ml": {"probability": 0.5},
                "flags": [],
            }
        ],
    }

    files = build_evidence_packet_files(payload)
    summary = write_evidence_packet(payload, tmp_path)

    assert "manifest.json" in files
    assert "tces/tce-1/final_disposition.md" in files
    assert summary["file_count"] == len(files)
    assert (tmp_path / "tces" / "tce-1" / "ml_evidence.json").exists()


def test_science_benchmark_summary_uses_truth_sets(monkeypatch):
    time = np.linspace(0, 4, 100, dtype=np.float32)
    flux = np.ones_like(time)
    cases = [
        BenchmarkCase(
            case_id="planet",
            group="known_confirmed_planets",
            truth_label="confirmed_planet",
            target_id="TIC 1",
            mission="TESS",
            expected_period_days=2.0,
            expected_disposition="planet_candidate",
            description="planet",
            time=time,
            flux=flux,
        ),
        BenchmarkCase(
            case_id="trap",
            group="known_false_positives",
            truth_label="known_false_positive",
            target_id="TIC 2",
            mission="TESS",
            expected_period_days=None,
            expected_disposition="not_planet_candidate",
            description="trap",
            time=time,
            flux=flux,
        ),
    ]

    def fake_analyze_light_curve_arrays(*, target_id, **kwargs):
        if target_id == "TIC 1":
            candidates = [{"candidate_id": "pc", "period_days": 2.0, "disposition": "planet_candidate"}]
            return {"tces": candidates, "planet_candidates": candidates, "engine_status": {}}
        tces = [{"candidate_id": "fp", "period_days": 1.0, "disposition": "rejected_signal", "flags": []}]
        return {"tces": tces, "planet_candidates": [], "engine_status": {}}

    import orbitlab.benchmarks.science_benchmark as benchmark

    monkeypatch.setattr(benchmark, "analyze_light_curve_arrays", fake_analyze_light_curve_arrays)

    report = run_science_benchmark(cases=cases)
    markdown = benchmark_report_markdown(report)

    assert report["known_planet_recovery_rate"] == 1.0
    assert report["false_positive_rejection_rate"] == 1.0
    assert report["false_alarm_escape_list"] == []
    assert "| planet |" in markdown


def test_science_benchmark_default_cases_and_report_writer(tmp_path):
    cases = _default_cases()
    assert {case.truth_label for case in cases} == {
        "confirmed_planet",
        "known_false_positive",
        "injected_transit",
        "scrambled_control",
    }
    assert all(case.time.shape == case.flux.shape for case in cases)

    with pytest.raises(FileNotFoundError, match="without a registered ML artifact"):
        _BenchmarkUnavailableModel().predict()

    report = {
        "status": "passed",
        "vetting_mode": "fast",
        "case_count": 0,
        "known_planet_recovery_rate": None,
        "false_positive_rejection_rate": None,
        "injected_transit_recovery_rate": None,
        "false_alarm_escape_list": [],
        "missed_known_planets": [],
        "unstable_candidates": [],
        "results": [],
    }
    paths = write_benchmark_reports(report, tmp_path)

    assert Path(paths["json"]).read_text(encoding="utf-8")
    assert "# OrbitLab Science Benchmark Report" in Path(paths["markdown"]).read_text(encoding="utf-8")


def test_science_benchmark_records_misses_escapes_unstable_periods_and_engine_failures(monkeypatch):
    time = np.linspace(0, 4, 100, dtype=np.float32)
    flux = 1.0 + 0.001 * np.sin(time).astype(np.float32)
    cases = [
        BenchmarkCase(
            case_id="missed-planet",
            group="known_confirmed_planets",
            truth_label="confirmed_planet",
            target_id="TIC 10",
            mission="TESS",
            expected_period_days=2.0,
            expected_disposition="planet_candidate",
            description="missed",
            time=time,
            flux=flux,
        ),
        BenchmarkCase(
            case_id="escaped-false-positive",
            group="known_false_positives",
            truth_label="known_false_positive",
            target_id="TIC 20",
            mission="TESS",
            expected_period_days=None,
            expected_disposition="not_planet_candidate",
            description="escape",
            time=time,
            flux=flux,
        ),
        BenchmarkCase(
            case_id="injected-with-hard-fail",
            group="synthetic_injections",
            truth_label="injected_transit",
            target_id="TIC 30",
            mission="TESS",
            expected_period_days=3.0,
            expected_disposition="planet_candidate",
            description="hard fail",
            time=time,
            flux=flux,
        ),
    ]

    def fake_analyze_light_curve_arrays(*, target_id, **kwargs):
        if target_id == "TIC 10":
            tce = {"candidate_id": "miss", "period_days": 3.0, "disposition": "borderline_tce", "flags": []}
            return {
                "tces": [tce],
                "planet_candidates": [],
                "engine_status": {"tls": {"status": "unstable_result"}},
            }
        if target_id == "TIC 20":
            tce = {"candidate_id": "escape", "period_days": 1.0, "disposition": "planet_candidate", "flags": []}
            return {"tces": [tce], "planet_candidates": [tce], "engine_status": {}}
        tce = {
            "candidate_id": "hard",
            "period_days": 3.0,
            "disposition": "planet_candidate",
            "flags": [{"severity": "hard_fail", "code": "unit"}],
        }
        return {"tces": [tce], "planet_candidates": [tce], "engine_status": {"dave": {"status": "failed"}}}

    import orbitlab.benchmarks.science_benchmark as benchmark

    monkeypatch.setattr(benchmark, "analyze_light_curve_arrays", fake_analyze_light_curve_arrays)

    report = run_science_benchmark(cases=cases)

    assert report["known_planet_recovery_rate"] == 0.0
    assert report["injected_transit_recovery_rate"] == 0.0
    assert report["false_positive_rejection_rate"] == 0.0
    assert report["false_alarm_escape_list"] == ["escaped-false-positive"]
    assert report["missed_known_planets"] == ["missed-planet", "injected-with-hard-fail"]
    assert report["unstable_candidates"] == ["missed-planet"]
    assert report["engine_failure_summary"] == {"tls": 1, "dave": 1}


def test_sector_consistency_reports_single_sector_only(monkeypatch):
    candidate = TransitCandidate(period=2.0, epoch=0.1, duration=0.1, depth=0.002, power=9.0, signal_to_noise=10.0)
    observation = SectorObservation(
        sector_id=infer_sector_id("mast:TESS/product/tess2020000000000-s0031-target.fits.gz"),
        time=np.linspace(0, 8, 400),
        flux=np.ones(400),
    )

    class _BlsResult:
        def __init__(self, found: TransitCandidate):
            self.candidate = found

    monkeypatch.setattr("orbitlab.science.sector_consistency.run_bls", lambda *args, **kwargs: _BlsResult(candidate))

    report = summarize_sector_consistency(candidate, [observation])

    assert observation.sector_id == "31"
    assert report["multi_sector_status"] == "single_sector_only"
    assert report["sector_evidence"][0]["period_support"] == 1.0


def test_sector_consistency_flags_period_drift(monkeypatch):
    candidate = TransitCandidate(period=2.0, epoch=0.1, duration=0.1, depth=0.002, power=9.0, signal_to_noise=10.0)
    observations = [
        SectorObservation(sector_id="1", time=np.linspace(0, 8, 400), flux=np.ones(400)),
        SectorObservation(sector_id="2", time=np.linspace(0, 8, 400), flux=np.ones(400)),
    ]
    found_periods = iter((2.0, 2.2))

    class _BlsResult:
        def __init__(self, period: float):
            self.candidate = TransitCandidate(
                period=period,
                epoch=0.1,
                duration=0.1,
                depth=0.002,
                power=9.0,
                signal_to_noise=10.0,
            )

    monkeypatch.setattr(
        "orbitlab.science.sector_consistency.run_bls",
        lambda *args, **kwargs: _BlsResult(next(found_periods)),
    )

    report = summarize_sector_consistency(candidate, observations)

    assert report["multi_sector_status"] == "inconsistent"
    assert report["period_spread_fraction"] == pytest.approx(0.1)
